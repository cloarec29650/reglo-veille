"""Réglementation européenne : nouveaux actes et propositions publiés sur EUR-Lex (SPARQL Cellar)."""

from datetime import date, timedelta

from ..classify import CompetitorMatcher, Theme, classify
from ..http import PoliteSession, describe_error
from ..storage import Store
from ..text import title_key, truncate

QUERY = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex ?date ?title WHERE {{
  ?work cdm:resource_legal_id_celex ?celex ;
        cdm:work_date_document ?date .
  ?expr cdm:expression_belongs_to_work ?work ;
        cdm:expression_title ?title ;
        cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/FRA> .
  FILTER(?date >= "{since}"^^xsd:date)
  FILTER(REGEX(STR(?celex), "^[35]"))
  FILTER(REGEX(?title, "{pattern}", "i"))
  {exclude}
}}
ORDER BY DESC(?date)
LIMIT 200
"""

# Lettre de type de document dans le numéro CELEX (secteur 3 : législation, 5 : travaux préparatoires).
CELEX_KINDS = {"R": "Règlement", "L": "Directive", "D": "Décision", "PC": "Proposition", "DC": "Communication",
               "SC": "Document de travail", "XC": "Communication", "H": "Recommandation"}


def _regex(patterns: list[str]) -> str:
    # Expressions combinées en une seule ; antislashs doublés et guillemets retirés pour la requête SPARQL.
    return "|".join(f"({p})" for p in patterns).replace("\\", "\\\\").replace('"', "")


def build_query(patterns: list[str], since: date, exclude: list[str] | None = None) -> str:
    exclude_filter = f'FILTER(!REGEX(?title, "{_regex(exclude)}", "i"))' if exclude else ""
    return QUERY.format(since=since.isoformat(), pattern=_regex(patterns), exclude=exclude_filter)


def celex_kind(celex: str) -> str:
    body = celex[5:]  # ex. 32026R2241 → « R2241 »
    for code in sorted(CELEX_KINDS, key=len, reverse=True):
        if body.startswith(code):
            return CELEX_KINDS[code]
    return "Acte"


def collect_regulation(cfg: dict, http: PoliteSession, store: Store,
                       themes: list[Theme], competitors: list[CompetitorMatcher]) -> dict:
    reg = cfg["regulation"]
    since = date.today() - timedelta(days=reg.get("lookback_days", 120))
    params = {"query": build_query(reg["title_patterns"], since, reg.get("title_exclude")),
              "format": "application/sparql-results+json"}
    rows, error = None, None
    # Le point d'accès SPARQL est parfois lent : délai long et une seconde tentative.
    for _ in range(2):
        try:
            resp = http.get(reg["sparql_url"], check_robots=False, params=params, timeout=reg.get("timeout_s", 90))
            rows = resp.json()["results"]["bindings"]
            break
        except Exception as e:
            error = e
    if rows is None:
        return {"EUR-Lex": {"ok": False, "erreur": describe_error(error)}}

    new = 0
    seen: set[str] = set()
    for row in rows:
        celex, title = row["celex"]["value"], " ".join(row["title"]["value"].replace("#", " ").split())
        # Un même titre peut exister sous plusieurs CELEX (résumés de décisions répétés) : un seul suffit.
        if celex in seen or title_key(title) in seen:
            continue
        seen.update({celex, title_key(title)})
        c = classify(title, themes, competitors)
        themes_ids = c.themes if "reglementation" in c.themes else ["reglementation", *c.themes]
        new += store.add_article({
            "key": f"celex-{celex}-{title_key(title)[:60]}",
            "title": truncate(title, 300),
            "url": f"https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:{celex}",
            "source": f"EUR-Lex ({celex_kind(celex)})",
            "source_type": "officiel",
            "published_at": f"{row['date']['value'][:10]}T00:00:00+00:00",
            "snippet": f"CELEX {celex}",
            "themes": themes_ids,
            "competitors": c.competitors,
            # Texte officiel : priorité haute dans le digest, quel que soit le score des mots-clés.
            "score": c.score + 6,
        })
    return {"EUR-Lex": {"ok": True, "actes": len(seen) // 2, "nouveaux": new}}
