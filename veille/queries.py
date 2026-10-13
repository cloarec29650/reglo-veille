"""Lecture de l'historique SQLite en DataFrames pour le dashboard (aucune requête réseau)."""

import json

import pandas as pd

from .storage import Store

UNKNOWN_SECTOR = "naf1:x"


def articles(store: Store) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM articles", store.db)
    if df.empty:
        return df.assign(theme_principal=pd.Series(dtype=str), date=pd.Series(dtype="datetime64[ns, UTC]"))
    df["themes"] = df["themes"].map(json.loads)
    df["competitors"] = df["competitors"].map(json.loads)
    df["theme_principal"] = df["themes"].map(lambda t: t[0] if t else "autres")
    df["date"] = pd.to_datetime(df["published_at"].fillna(df["first_seen_at"]), utc=True, format="ISO8601")
    return df.sort_values(["date", "score"], ascending=False)


def competitor_changes(store: Store) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM competitor_changes ORDER BY detected_at DESC", store.db)
    if not df.empty:
        df["added"] = df["added"].map(json.loads)
        df["removed"] = df["removed"].map(json.loads)
        df["detected_at"] = pd.to_datetime(df["detected_at"], utc=True, format="ISO8601")
        df["price_change"] = df["price_change"].astype(bool)
    return df


def tracked_pages(store: Store) -> pd.DataFrame:
    return pd.DataFrame(store.tracked_pages())


def tenders(store: Store) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM tenders ORDER BY published_at DESC", store.db)
    if not df.empty:
        df["published_at"] = pd.to_datetime(df["published_at"])
    return df


def sources(store: Store) -> pd.DataFrame:
    _, by_volet = store.source_status()
    rows = []
    for volet, srcs in by_volet.items():
        for name, s in srcs.items():
            detail = s.get("erreur") or s.get("statut") or ", ".join(
                f"{k} {v}" for k, v in s.items() if k not in ("ok", "_at"))
            rows.append({"Volet": volet, "Source": name,
                         "État": {True: "✅ OK", False: "❌ Échec", None: "⏸ Non configuré"}[s.get("ok")],
                         "Détail": detail, "Relevé le": s["_at"][:10]})
    return pd.DataFrame(rows)


def _indicator(store: Store, name: str, period: str | None = None) -> pd.DataFrame:
    return pd.DataFrame(store.indicators(name, period), columns=["name", "period", "dimension", "label", "value", "source", "fetched_at"])


def market_by_size(store: Store) -> tuple[str | None, pd.DataFrame]:
    """Entreprises et salariés par tranche d'effectif (dernière année) + évolution sur un an."""
    period = store.latest_period("entreprises")
    if period is None:
        return None, pd.DataFrame()
    cur = _indicator(store, "entreprises", period)
    prev = _indicator(store, "entreprises", str(int(period) - 1)).set_index("dimension")["value"]
    sal = _indicator(store, "salaries", period).set_index("dimension")["value"]
    df = pd.DataFrame({
        "ordre": cur["dimension"].str.split(":").str[1].astype(int),
        "tranche": cur["label"],
        "entreprises": cur["value"],
        "salaries": cur["dimension"].map(sal),
        "evolution": cur["value"] / cur["dimension"].map(prev) - 1,
    })
    return period, df.sort_values("ordre").reset_index(drop=True)


def addressable_market(by_size: pd.DataFrame, prices: dict[int, float]) -> float:
    """Marché adressable = somme des entreprises des tranches ciblées × prix annuel de la tranche."""
    return float(sum(by_size.loc[by_size["ordre"] == o, "entreprises"].sum() * p for o, p in prices.items()))


def segmentation(store: Store) -> pd.DataFrame:
    """Par secteur : entreprises et salariés ciblés, croisés avec la sinistralité AT/MP."""
    target = _indicator(store, "entreprises_cible")
    if target.empty:
        return pd.DataFrame()
    def by_dim(name):
        return _indicator(store, name).set_index("dimension")["value"]
    df = pd.DataFrame({
        "naf": target["dimension"].str.split(":").str[1],
        "secteur": target["label"],
        "entreprises_cibles": target["value"],
        "salaries_cibles": target["dimension"].map(by_dim("salaries_cible")),
        "indice_frequence_at": target["dimension"].map(by_dim("at_indice_frequence")),
        "accidents_travail": target["dimension"].map(by_dim("at_sinistres")),
        "maladies_pro": target["dimension"].map(by_dim("mp_sinistres")),
    })
    df = df[(target["dimension"] != UNKNOWN_SECTOR).values & (df["entreprises_cibles"] > 0).values]
    return df.sort_values("entreprises_cibles", ascending=False).reset_index(drop=True)


def atmp(store: Store) -> tuple[str | None, pd.DataFrame, dict]:
    """Indice de fréquence AT par secteur (dernière année et précédente) + chiffres nationaux."""
    period = store.latest_period("at_indice_frequence")
    if period is None:
        return None, pd.DataFrame(), {}
    prev = str(int(period) - 1)
    cur = _indicator(store, "at_indice_frequence", period)
    def series(name, p):
        return _indicator(store, name, p).set_index("dimension")["value"]
    if_prev, at_n, mp_n, mp_prev = (series("at_indice_frequence", prev), series("at_sinistres", period),
                                    series("mp_sinistres", period), series("mp_sinistres", prev))
    df = pd.DataFrame({
        "dimension": cur["dimension"],
        "naf": cur["dimension"].str.split(":").str[1],
        "secteur": cur["label"],
        "indice_frequence_at": cur["value"],
        "evolution_if": cur["value"] - cur["dimension"].map(if_prev),
        "accidents_travail": cur["dimension"].map(at_n),
        "maladies_pro": cur["dimension"].map(mp_n),
    })
    national_row = df[df["dimension"] == "naf1:TOUS"]
    national = {}
    if not national_row.empty:
        r = national_row.iloc[0]
        national = {
            "indice_frequence_at": r["indice_frequence_at"],
            "accidents_travail": r["accidents_travail"],
            "maladies_pro": r["maladies_pro"],
            "evolution_mp": (r["maladies_pro"] / mp_prev.get("naf1:TOUS") - 1) if mp_prev.get("naf1:TOUS") else None,
        }
    sectors = df[~df["dimension"].isin(["naf1:TOUS", UNKNOWN_SECTOR])].dropna(subset=["indice_frequence_at"])
    sectors = sectors[sectors["accidents_travail"] > 0]
    return period, sectors.drop(columns="dimension").sort_values("indice_frequence_at", ascending=False), national
