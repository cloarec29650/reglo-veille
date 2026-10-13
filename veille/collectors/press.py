"""Presse & tendances : flux RSS spécialisés + recherches d'actualité Bing News, filtrés par thèmes."""

import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import feedparser

from ..classify import CompetitorMatcher, Theme, classify
from ..http import PoliteSession, describe_error
from ..storage import Store
from ..text import looks_english, strip_html, title_key, truncate

BING_NEWS_URL = "https://www.bing.com/news/search"


def _published(entry) -> str | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc).replace(microsecond=0).isoformat()


def resolve_link(link: str) -> str:
    """Les liens Bing News passent par une redirection (apiclick.aspx?…&url=<lien réel>) : on garde le lien réel."""
    parts = urlsplit(link)
    if parts.netloc.endswith("bing.com") and "apiclick" in parts.path:
        real = parse_qs(parts.query).get("url", [""])[0]
        if real.startswith(("http://", "https://")):
            return real
    return link


def parse_entries(content: bytes, source: str, snippet_chars: int, source_type: str = "presse") -> list[dict]:
    """Transforme un flux RSS/Atom en articles bruts (titre, lien, date, extrait court)."""
    feed = feedparser.parse(content)
    articles = []
    for entry in feed.entries:
        title = strip_html(entry.get("title", ""))
        link = resolve_link(entry.get("link", ""))
        if not title or not link:
            continue
        summary = strip_html(entry.get("summary", "") or entry.get("description", ""))
        articles.append({
            "key": title_key(title),
            "title": title,
            "url": link,
            # Bing indique le média d'origine dans <News:Source>.
            "source": entry.get("news_source") or source,
            "source_type": source_type,
            "published_at": _published(entry),
            "snippet": truncate(summary, snippet_chars) if summary else "",
            "_text": f"{title}. {summary}",
        })
    return articles


def too_old(article: dict, max_age_days: int | None, now: datetime | None = None) -> bool:
    if not max_age_days or not article.get("published_at"):
        return False
    now = now or datetime.now(timezone.utc)
    return datetime.fromisoformat(article["published_at"]) < now - timedelta(days=max_age_days)


def bing_queries(cfg: dict) -> list[tuple[str, bool]]:
    """Requêtes métier de la config + une requête par concurrent (nom exact). (requête, est_concurrent)"""
    queries = [(q, False) for q in cfg["press"].get("bing_queries") or []]
    queries += [(c.get("search") or f'"{c["name"]}"', True) for c in cfg["competitors"]]
    return queries


def _ingest(entries: list[dict], store: Store, themes, competitors, min_score: float, max_age: int | None,
            french_only: bool = False) -> tuple[int, int]:
    kept = new = 0
    for article in entries:
        text = article.pop("_text")
        if too_old(article, max_age) or (french_only and looks_english(text)):
            continue
        c = classify(text, themes, competitors, min_score)
        # Un article d'un blog concurrent est toujours gardé : c'est le discours du concurrent.
        if not c.relevant and article["source_type"] != "concurrent":
            continue
        kept += 1
        new += store.add_article({**article, "themes": c.themes, "competitors": c.competitors, "score": c.score})
    return kept, new


def collect_press(cfg: dict, http: PoliteSession, store: Store,
                  themes: list[Theme], competitors: list[CompetitorMatcher]) -> dict:
    report = {}
    press = cfg["press"]
    snippet_chars = press.get("snippet_chars", 280)
    max_age = press.get("max_age_days")
    relevance = cfg.get("relevance") or {}
    min_score = relevance.get("min_score", 0)
    search_min = relevance.get("search_min_score", min_score)
    competitor_age = relevance.get("competitor_max_age_days", max_age)
    french_only = relevance.get("french_only", False)

    for feed in press["feeds"]:
        name = feed["name"]
        try:
            entries = parse_entries(http.get(feed["url"]).content, name, snippet_chars, feed.get("type", "presse"))
            kept, new = _ingest(entries, store, themes, competitors, min_score, max_age, french_only)
            report[name] = {"ok": True, "lus": len(entries), "retenus": kept, "nouveaux": new}
        except Exception as e:  # une source en panne ne bloque pas les autres
            report[name] = {"ok": False, "erreur": describe_error(e)}

    totals = {"requêtes": 0, "lus": 0, "retenus": 0, "nouveaux": 0, "échecs": 0}
    for query, is_competitor in bing_queries(cfg):
        try:
            resp = http.get(BING_NEWS_URL, params={"q": query, "format": "rss", "setlang": "fr", "cc": "FR", "mkt": "fr-FR"})
            entries = parse_entries(resp.content, "Bing News", snippet_chars, "recherche")
            kept, new = _ingest(entries, store, themes, competitors, search_min,
                                competitor_age if is_competitor else max_age, french_only)
            totals["requêtes"] += 1
            totals["lus"] += len(entries)
            totals["retenus"] += kept
            totals["nouveaux"] += new
        except Exception as e:
            totals["échecs"] += 1
            totals["dernière erreur"] = describe_error(e)
    report["Bing News (recherches)"] = {"ok": totals["requêtes"] > 0, **totals}
    return report
