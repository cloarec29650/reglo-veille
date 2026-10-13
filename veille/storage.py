"""Stockage SQLite : historique de la veille (articles, concurrents, indicateurs, avis)."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    key           TEXT PRIMARY KEY,      -- titre normalisé (déduplication inter-sources)
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    source        TEXT NOT NULL,
    published_at  TEXT,
    snippet       TEXT,
    themes        TEXT NOT NULL,         -- JSON : identifiants de thèmes
    competitors   TEXT NOT NULL,         -- JSON : concurrents cités
    score         REAL NOT NULL,
    first_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS competitor_snapshots (
    url         TEXT NOT NULL,
    competitor  TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    lines       TEXT NOT NULL,           -- JSON : lignes de texte visibles de la page
    PRIMARY KEY (url, fetched_at)
);
CREATE TABLE IF NOT EXISTS competitor_changes (
    url          TEXT NOT NULL,
    competitor   TEXT NOT NULL,
    detected_at  TEXT NOT NULL,
    added        TEXT NOT NULL,          -- JSON
    removed      TEXT NOT NULL,          -- JSON
    price_change INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS indicators (
    name       TEXT NOT NULL,
    period     TEXT NOT NULL,
    dimension  TEXT NOT NULL,
    label      TEXT,
    value      REAL,
    source     TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (name, period, dimension)
);
CREATE TABLE IF NOT EXISTS tenders (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    buyer        TEXT,
    nature       TEXT,
    published_at TEXT,
    deadline     TEXT,
    winners      TEXT,
    url          TEXT,
    first_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_events (
    id          TEXT PRIMARY KEY,        -- identifiant BODACC
    competitor  TEXT NOT NULL,
    siren       TEXT NOT NULL,
    published_at TEXT NOT NULL,
    family      TEXT,                    -- ex. « Dépôts des comptes », « Ventes et cessions »
    detail      TEXT,
    url         TEXT,
    first_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    started_at  TEXT PRIMARY KEY,
    finished_at TEXT,
    report      TEXT                     -- JSON : statut par source
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Mises à niveau des bases créées par une version antérieure."""
        columns = {r["name"] for r in self.db.execute("PRAGMA table_info(articles)")}
        if "source_type" not in columns:
            self.db.execute("ALTER TABLE articles ADD COLUMN source_type TEXT NOT NULL DEFAULT 'presse'")
            self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ── Articles ──
    def add_article(self, a: dict) -> bool:
        """Insère un article s'il est nouveau. Renvoie True si ajouté."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO articles (key, title, url, source, published_at, snippet, themes, competitors, "
            "score, first_seen_at, source_type) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (a["key"], a["title"], a["url"], a["source"], a.get("published_at"), a.get("snippet"),
             json.dumps(a["themes"]), json.dumps(a["competitors"]), a["score"], now_iso(),
             a.get("source_type", "presse")),
        )
        self.db.commit()
        return cur.rowcount == 1

    def articles_since(self, since_iso: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM articles WHERE COALESCE(published_at, first_seen_at) >= ? ORDER BY score DESC, published_at DESC",
            (since_iso,),
        ).fetchall()
        return [{**dict(r), "themes": json.loads(r["themes"]), "competitors": json.loads(r["competitors"])} for r in rows]

    # ── Concurrents ──
    def latest_snapshot(self, url: str) -> list[str] | None:
        row = self.db.execute(
            "SELECT lines FROM competitor_snapshots WHERE url = ? ORDER BY fetched_at DESC LIMIT 1", (url,)
        ).fetchone()
        return json.loads(row["lines"]) if row else None

    def add_snapshot(self, url: str, competitor: str, lines: list[str]) -> None:
        self.db.execute("INSERT OR REPLACE INTO competitor_snapshots VALUES (?,?,?,?)",
                        (url, competitor, now_iso(), json.dumps(lines, ensure_ascii=False)))
        self.db.commit()

    def add_change(self, url: str, competitor: str, added: list[str], removed: list[str], price_change: bool) -> None:
        self.db.execute("INSERT INTO competitor_changes VALUES (?,?,?,?,?,?)",
                        (url, competitor, now_iso(), json.dumps(added, ensure_ascii=False),
                         json.dumps(removed, ensure_ascii=False), int(price_change)))
        self.db.commit()

    def changes_since(self, since_iso: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM competitor_changes WHERE detected_at >= ? ORDER BY price_change DESC, detected_at DESC",
            (since_iso,),
        ).fetchall()
        return [{**dict(r), "added": json.loads(r["added"]), "removed": json.loads(r["removed"])} for r in rows]

    def tracked_pages(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT competitor, url, MIN(fetched_at) AS first, MAX(fetched_at) AS last, COUNT(*) AS n "
            "FROM competitor_snapshots GROUP BY competitor, url ORDER BY competitor"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Indicateurs ──
    def put_indicator(self, name: str, period: str, dimension: str, value: float | None, source: str, label: str = "") -> None:
        self.db.execute("INSERT OR REPLACE INTO indicators VALUES (?,?,?,?,?,?,?)",
                        (name, period, dimension, label, value, source, now_iso()))

    def commit(self) -> None:
        self.db.commit()

    def indicators(self, name: str, period: str | None = None) -> list[dict]:
        if period is None:
            period = self.latest_period(name)
        rows = self.db.execute("SELECT * FROM indicators WHERE name = ? AND period = ? ORDER BY dimension",
                               (name, period)).fetchall()
        return [dict(r) for r in rows]

    def periods(self, name: str) -> list[str]:
        rows = self.db.execute("SELECT DISTINCT period FROM indicators WHERE name = ? ORDER BY period DESC", (name,))
        return [r["period"] for r in rows]

    def latest_period(self, name: str) -> str | None:
        periods = self.periods(name)
        return periods[0] if periods else None

    # ── Annonces légales des concurrents ──
    def add_company_event(self, e: dict) -> bool:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO company_events VALUES (?,?,?,?,?,?,?,?)",
            (e["id"], e["competitor"], e["siren"], e["published_at"], e.get("family"), e.get("detail"),
             e.get("url"), now_iso()),
        )
        self.db.commit()
        return cur.rowcount == 1

    def company_events_since(self, since_date: str) -> list[dict]:
        rows = self.db.execute("SELECT * FROM company_events WHERE published_at >= ? ORDER BY published_at DESC",
                               (since_date,))
        return [dict(r) for r in rows]

    # ── Appels d'offres ──
    def add_tender(self, t: dict) -> bool:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO tenders VALUES (?,?,?,?,?,?,?,?,?)",
            (t["id"], t["title"], t.get("buyer"), t.get("nature"), t.get("published_at"), t.get("deadline"),
             t.get("winners"), t.get("url"), now_iso()),
        )
        self.db.commit()
        return cur.rowcount == 1

    def tenders_since(self, since_date: str) -> list[dict]:
        rows = self.db.execute("SELECT * FROM tenders WHERE published_at >= ? ORDER BY published_at DESC", (since_date,))
        return [dict(r) for r in rows]

    # ── Exécutions ──
    def save_run(self, started_at: str, report: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?)",
                        (started_at, now_iso(), json.dumps(report, ensure_ascii=False)))
        self.db.commit()

    def source_status(self) -> tuple[str | None, dict]:
        """État le plus récent de chaque source, toutes exécutions confondues (une collecte partielle
        avec --only ne masque pas les autres sources). Renvoie (date de la dernière collecte, états)."""
        merged: dict[str, dict] = {}
        last = None
        for row in self.db.execute("SELECT started_at, report FROM runs ORDER BY started_at"):
            last = row["started_at"]
            for volet, sources in json.loads(row["report"]).items():
                for name, status in sources.items():
                    merged.setdefault(volet, {})[name] = {**status, "_at": row["started_at"]}
        return last, merged
