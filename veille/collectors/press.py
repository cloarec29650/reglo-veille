"""Presse & tendances : flux RSS filtrés par thèmes."""

import time
from datetime import datetime, timezone

import feedparser

from ..classify import CompetitorMatcher, Theme, classify
from ..http import PoliteSession, describe_error
from ..storage import Store
from ..text import strip_html, title_key, truncate


def _published(entry) -> str | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc).replace(microsecond=0).isoformat()


def parse_entries(content: bytes, source: str, snippet_chars: int) -> list[dict]:
    """Transforme un flux RSS/Atom en articles bruts (titre, lien, date, extrait court)."""
    feed = feedparser.parse(content)
    articles = []
    for entry in feed.entries:
        title = strip_html(entry.get("title", ""))
        link = entry.get("link", "")
        if not title or not link:
            continue
        summary = strip_html(entry.get("summary", "") or entry.get("description", ""))
        articles.append({
            "key": title_key(title),
            "title": title,
            "url": link,
            "source": source,
            "published_at": _published(entry),
            "snippet": truncate(summary, snippet_chars) if summary else "",
            "_text": f"{title}. {summary}",
        })
    return articles


def collect_press(cfg: dict, http: PoliteSession, store: Store,
                  themes: list[Theme], competitors: list[CompetitorMatcher]) -> dict:
    report = {}
    snippet_chars = cfg["press"].get("snippet_chars", 280)
    for feed in cfg["press"]["feeds"]:
        name = feed["name"]
        try:
            resp = http.get(feed["url"])
            entries = parse_entries(resp.content, name, snippet_chars)
            kept = new = 0
            for article in entries:
                c = classify(article.pop("_text"), themes, competitors)
                if not c.relevant:
                    continue
                kept += 1
                new += store.add_article({**article, "themes": c.themes, "competitors": c.competitors, "score": c.score})
            report[name] = {"ok": True, "lus": len(entries), "retenus": kept, "nouveaux": new}
        except Exception as e:  # une source en panne ne bloque pas les autres
            report[name] = {"ok": False, "erreur": describe_error(e)}
    return report
