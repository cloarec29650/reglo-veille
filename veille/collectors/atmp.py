"""Sinistralité AT/MP par secteur (Assurance Maladie, open data)."""

from ..http import PoliteSession
from ..storage import Store
from .market import AMELI_SOURCE, latest_year, ods_export

RISKS = {"Accidents du travail": "at", "Maladies professionnelles": "mp"}


def collect_atmp(cfg: dict, http: PoliteSession, store: Store) -> dict:
    base, dataset = cfg["market"]["ameli_base"], cfg["atmp"]["dataset"]
    year = latest_year(http, base, dataset)
    risks = ", ".join(f'"{r}"' for r in RISKS)
    rows = ods_export(
        http, base, dataset,
        select="annee, risque, code_naf1, libelle_naf1, nb_sinistres_int, nb_salaries_int, indice_frequence_int",
        # ODSQL n'accepte pas « year(...) in (...) » : comparaison explicite des deux années.
        where=(f'(year(annee)={year} or year(annee)={year - 1}) and code_naf5="TOUS" '
               f'and risque in ({risks}) and code_naf1!="x"'),
    )
    for r in rows:
        y, risk = str(r["annee"])[:4], RISKS[r["risque"]]
        dim, label = f"naf1:{r['code_naf1']}", r["libelle_naf1"]
        sinistres, salaries = r["nb_sinistres_int"], r["nb_salaries_int"]
        # Indice de fréquence = sinistres pour 1 000 salariés (recalculé s'il n'est pas publié).
        freq = r["indice_frequence_int"]
        if freq is None and sinistres is not None and salaries:
            freq = round(sinistres / salaries * 1000, 1)
        store.put_indicator(f"{risk}_sinistres", y, dim, sinistres, AMELI_SOURCE, label)
        store.put_indicator(f"{risk}_indice_frequence", y, dim, freq, AMELI_SOURCE, label)
        store.put_indicator(f"{risk}_salaries", y, dim, salaries, AMELI_SOURCE, label)
    store.commit()
    return {"ok": True, "annee": year, "lignes": len(rows)}
