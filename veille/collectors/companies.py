"""Annonces légales des concurrents (BODACC) : comptes, modifications, cessions, procédures, radiations."""

import json
from datetime import date, timedelta

from ..http import PoliteSession, describe_error
from ..storage import Store


def event_detail(record: dict) -> str:
    """Résumé lisible de l'annonce à partir des blocs JSON du BODACC."""
    parts = []
    for field in ("modificationsgenerales", "depot", "jugement", "acte", "radiationaurcs", "divers"):
        raw = record.get(field)
        if not raw:
            continue
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            parts.append(str(raw))
            continue
        if isinstance(data, dict):
            parts += [f"{v}" for k, v in data.items() if isinstance(v, str) and v.strip() and k != "dateCommencementActivite"]
        else:
            parts.append(str(data))
    return " ; ".join(dict.fromkeys(parts))[:400] if parts else ""


def collect_companies(cfg: dict, http: PoliteSession, store: Store) -> dict:
    since = date.today() - timedelta(days=cfg["companies"].get("lookback_days", 365))
    report = {}
    for comp in cfg["competitors"]:
        siren = comp.get("siren")
        if not siren:
            continue
        key = f"BODACC {comp['name']}"
        try:
            rows = http.get(cfg["companies"]["bodacc_url"], check_robots=False, params={
                "where": f'search(registre, "{siren}") and dateparution >= date\'{since.isoformat()}\'',
                "order_by": "dateparution desc",
                "limit": 50,
            }).json()
            new = 0
            for r in rows.get("results", []):
                new += store.add_company_event({
                    "id": r["id"], "competitor": comp["name"], "siren": siren,
                    "published_at": r["dateparution"], "family": r.get("familleavis_lib"),
                    "detail": event_detail(r), "url": r.get("url_complete"),
                })
            report[key] = {"ok": True, "annonces": rows.get("total_count", 0), "nouvelles": new}
        except Exception as e:
            report[key] = {"ok": False, "erreur": describe_error(e)}
    return report
