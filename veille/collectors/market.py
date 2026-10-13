"""Indicateurs marché : taille du marché (Assurance Maladie), appels d'offres (BOAMP), offres d'emploi (France Travail)."""

import os
from datetime import date, timedelta

from ..http import PoliteSession
from ..storage import Store

COMPANIES_DATASET = "entreprises-et-salaries-par-taille-d-entreprise-et-secteur-d-activite-naf-1-et-naf-5"
AMELI_SOURCE = "Assurance Maladie, data.ameli.fr (régime général)"


def ods_export(http: PoliteSession, base: str, dataset: str, **params) -> list[dict]:
    """Export JSON complet d'un jeu Opendatasoft (pas de limite de 100 lignes)."""
    # API ouverte documentée : pas de contrôle robots.txt (il vise les pages web).
    return http.get(f"{base}/{dataset}/exports/json", params=params, check_robots=False).json()


def latest_year(http: PoliteSession, base: str, dataset: str) -> int:
    resp = http.get(f"{base}/{dataset}/records", params={"select": "annee", "order_by": "annee desc", "limit": 1},
                    check_robots=False).json()
    return int(str(resp["results"][0]["annee"])[:4])


def collect_market_size(cfg: dict, http: PoliteSession, store: Store) -> dict:
    """Entreprises et salariés par tranche d'effectif et par secteur (NAF niveau 1)."""
    base = cfg["market"]["ameli_base"]
    year = latest_year(http, base, COMPANIES_DATASET)
    for y in (year, year - 1):
        by_size = ods_export(
            http, base, COMPANIES_DATASET,
            select="ordre_taille_entreprise, taille_entreprise, nb_entreprises_int, nb_salaries_int",
            where=f'year(annee)={y} and code_naf1="TOUS" and ordre_taille_entreprise is not null',
        )
        for r in by_size:
            dim = f"taille:{r['ordre_taille_entreprise']}"
            label = str(r["taille_entreprise"]).lstrip("'")
            store.put_indicator("entreprises", str(y), dim, r["nb_entreprises_int"], AMELI_SOURCE, label)
            store.put_indicator("salaries", str(y), dim, r["nb_salaries_int"], AMELI_SOURCE, label)

    targets = ",".join(str(o) for o in cfg["market"]["target_size_orders"])
    by_sector = ods_export(
        http, base, COMPANIES_DATASET,
        select="code_naf1, libelle_naf1, sum(nb_entreprises_int) as n, sum(nb_salaries_int) as s",
        where=(f'year(annee)={year} and code_naf1!="TOUS" and code_naf5!="TOUS" '
               f"and ordre_taille_entreprise in ({targets})"),
        group_by="code_naf1, libelle_naf1",
    )
    for r in by_sector:
        store.put_indicator("entreprises_cible", str(year), f"naf1:{r['code_naf1']}", r["n"], AMELI_SOURCE, r["libelle_naf1"])
        store.put_indicator("salaries_cible", str(year), f"naf1:{r['code_naf1']}", r["s"], AMELI_SOURCE, r["libelle_naf1"])
    store.commit()
    return {"ok": True, "annee": year, "secteurs": len(by_sector)}


def boamp_where(keywords: list[str], since: date) -> str:
    terms = " or ".join(f'search(objet, "{k}")' for k in keywords)
    return f"({terms}) and dateparution >= date'{since.isoformat()}'"


def collect_tenders(cfg: dict, http: PoliteSession, store: Store, days: int) -> dict:
    """Avis BOAMP récents dont l'objet contient un mot-clé QHSE / RSE."""
    # Historique plus long que la période du digest : les avis restent consultables dans le dashboard.
    since = date.today() - timedelta(days=max(days, cfg["tenders"].get("lookback_days", days)))
    rows = http.get(cfg["tenders"]["boamp_url"], check_robots=False, params={
        "where": boamp_where(cfg["tenders"]["keywords"], since),
        "select": "idweb, objet, nomacheteur, nature_libelle, dateparution, datelimitereponse, titulaire, url_avis",
        "order_by": "dateparution desc",
        "limit": 100,
    }).json()
    new = 0
    for r in rows.get("results", []):
        winners = r.get("titulaire")
        new += store.add_tender({
            "id": r["idweb"], "title": r.get("objet") or "", "buyer": r.get("nomacheteur"),
            "nature": r.get("nature_libelle"), "published_at": r.get("dateparution"),
            "deadline": r.get("datelimitereponse"), "url": r.get("url_avis"),
            "winners": ", ".join(dict.fromkeys(winners)) if isinstance(winners, list) else winners,
        })
    return {"ok": True, "avis": rows.get("total_count", 0), "nouveaux": new}


FT_TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
FT_SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"


def collect_jobs(cfg: dict, http: PoliteSession, store: Store, days: int) -> dict:
    """Nombre d'offres d'emploi publiées par mot-clé (signal de demande). Optionnel."""
    client_id, secret = os.environ.get("FT_CLIENT_ID"), os.environ.get("FT_CLIENT_SECRET")
    if not (client_id and secret):
        return {"ok": None, "statut": "non configuré (FT_CLIENT_ID / FT_CLIENT_SECRET absents)"}
    token = http.session.post(FT_TOKEN_URL, timeout=http.timeout_s, data={
        "grant_type": "client_credentials", "client_id": client_id, "client_secret": secret,
        "scope": "api_offresdemploiv2 o2dsoffre",
    })
    token.raise_for_status()
    headers = {"Authorization": f"Bearer {token.json()['access_token']}", "Accept": "application/json"}
    period = date.today().isoformat()
    counts = {}
    for kw in cfg["jobs"]["keywords"]:
        # publieeDepuis accepte 1, 3, 7, 14 ou 31 jours.
        since = min((d for d in (1, 3, 7, 14, 31) if d >= days), default=31)
        resp = http.get(FT_SEARCH_URL, check_robots=False, headers=headers,
                        params={"motsCles": kw, "publieeDepuis": since, "range": "0-0"})
        # Content-Range : « offres 0-0/1234 » → total après le « / ».
        total = int(resp.headers.get("Content-Range", "0/0").rsplit("/", 1)[-1] or 0)
        store.put_indicator("offres_emploi", period, f"mot:{kw}", total, "France Travail, API Offres d'emploi", kw)
        counts[kw] = total
    store.commit()
    return {"ok": True, **counts}
