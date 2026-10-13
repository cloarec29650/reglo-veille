"""Ligne de commande.

    python -m veille run                  collecte tout + digest des 7 derniers jours
    python -m veille run --only press,competitors
    python -m veille digest --days 14     régénère le digest sans collecter
"""

import argparse
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

import yaml

from .classify import compile_competitors, compile_themes
from .collectors.atmp import collect_atmp
from .collectors.companies import collect_companies
from .collectors.competitors import collect_competitors
from .collectors.market import collect_jobs, collect_market_size, collect_tenders
from .collectors.press import collect_press
from .collectors.regulation import collect_regulation
from .digest import build_digest
from .html_export import render_html
from .http import PoliteSession, describe_error
from .storage import Store, now_iso

ROOT = Path(__file__).resolve().parent.parent
VOLETS = ("press", "regulation", "competitors", "market", "atmp")


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_collect(cfg: dict, store: Store, volets: list[str], days: int) -> dict:
    http = PoliteSession(cfg["http"]["user_agent"], cfg["http"]["timeout_s"], cfg["http"]["min_delay_s"])
    report: dict[str, dict] = {}

    def safe(fn):
        try:
            return fn()
        except Exception as e:
            return {"ok": False, "erreur": describe_error(e)}

    if "press" in volets:
        print("· Presse…", flush=True)
        report["Presse"] = collect_press(cfg, http, store, compile_themes(cfg["themes"]), compile_competitors(cfg["competitors"]))
    if "regulation" in volets:
        print("· Réglementation (EUR-Lex)…", flush=True)
        report["Réglementation"] = collect_regulation(cfg, http, store, compile_themes(cfg["themes"]),
                                                      compile_competitors(cfg["competitors"]))
    if "competitors" in volets:
        print("· Concurrents…", flush=True)
        report["Concurrents"] = {**collect_competitors(cfg, http, store), **collect_companies(cfg, http, store)}
    if "market" in volets:
        print("· Marché…", flush=True)
        report["Marché"] = {
            "Assurance Maladie (taille du marché)": safe(lambda: collect_market_size(cfg, http, store)),
            "BOAMP (appels d'offres)": safe(lambda: collect_tenders(cfg, http, store, days)),
            "France Travail (offres d'emploi)": safe(lambda: collect_jobs(cfg, http, store, days)),
        }
    if "atmp" in volets:
        print("· Sinistralité AT/MP…", flush=True)
        report["AT/MP"] = {"Assurance Maladie (sinistralité)": safe(lambda: collect_atmp(cfg, http, store))}
    return report


def write_digest(cfg: dict, store: Store, days: int, out_dir: Path) -> list[Path]:
    """Écrit le digest en Markdown et en HTML autonome (même nom, deux extensions)."""
    today = date.today()
    out_dir.mkdir(parents=True, exist_ok=True)
    year, week, _ = today.isocalendar()
    base = out_dir / f"veille-{year}-S{week:02d}"
    md_text = build_digest(store, cfg, days, today)
    md_path, html_path = base.with_suffix(".md"), base.with_suffix(".html")
    md_path.write_text(md_text, encoding="utf-8")
    html_path.write_text(render_html(md_text, datetime.now().strftime("%d/%m/%Y à %H:%M")), encoding="utf-8")
    return [md_path, html_path]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="veille", description="Veille marché QHSE / RSE de Reglo")
    parser.add_argument("command", choices=["run", "digest"])
    parser.add_argument("--days", type=int, default=7, help="période couverte par le digest (jours)")
    parser.add_argument("--only", help=f"volets à collecter, séparés par des virgules : {','.join(VOLETS)}")
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "veille.sqlite")
    parser.add_argument("--out", type=Path, default=ROOT / "reports")
    parser.add_argument("--open", action="store_true", help="ouvre le digest HTML dans le navigateur")
    args = parser.parse_args(argv)
    # Console Windows : forcer l'UTF-8 pour les accents et symboles.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cfg = load_config(args.config)
    store = Store(args.db)
    try:
        if args.command == "run":
            volets = args.only.split(",") if args.only else list(VOLETS)
            unknown = set(volets) - set(VOLETS)
            if unknown:
                parser.error(f"volet(s) inconnu(s) : {', '.join(sorted(unknown))}")
            started = now_iso()
            report = run_collect(cfg, store, volets, args.days)
            store.save_run(started, report)
            failed = [f"{v} / {n}" for v, s in report.items() for n, r in s.items() if r.get("ok") is False]
            if failed:
                print(f"⚠ {len(failed)} source(s) en échec : " + "; ".join(failed))
        for path in write_digest(cfg, store, args.days, args.out):
            print(f"Digest : {path}")
        if args.open:
            webbrowser.open(path.resolve().as_uri())
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
