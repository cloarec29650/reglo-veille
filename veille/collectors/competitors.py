"""Concurrents : détection des changements de contenu sur leurs pages publiques."""

import re
from html.parser import HTMLParser

from ..http import PoliteSession, describe_error
from ..storage import Store

_SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe", "head"}
_BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "br", "tr", "td",
               "th", "header", "footer", "nav", "a", "button", "span", "label", "dt", "dd", "blockquote"}
# Lignes sans intérêt ou qui changent à chaque visite (années, compteurs…).
_NOISE_RE = re.compile(r"^[\d\s.,:/%°©|–—-]*$|^©|cookie|tous droits reserves|all rights reserved", re.IGNORECASE)
PRICE_RE = re.compile(r"\d[\d\s.,]*\s?(€|eur\b|euros?\b)|€\s?\d|\bht\s*/\s*mois|/\s*mois|par mois|/\s*an\b", re.IGNORECASE)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self.chunks.append(data)


def page_lines(html: str) -> list[str]:
    """Texte visible d'une page, une ligne par bloc, sans doublons ni bruit."""
    parser = _TextExtractor()
    parser.feed(html)
    seen: set[str] = set()
    lines = []
    for raw in "".join(parser.chunks).split("\n"):
        line = " ".join(raw.split())
        if len(line) < 3 or _NOISE_RE.search(line) or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines


def diff_lines(old: list[str], new: list[str]) -> tuple[list[str], list[str]]:
    """Lignes apparues et disparues (l'ordre de la page est conservé)."""
    old_set, new_set = set(old), set(new)
    return [l for l in new if l not in old_set], [l for l in old if l not in new_set]


def mentions_price(lines: list[str]) -> bool:
    return any(PRICE_RE.search(l) for l in lines)


def collect_competitors(cfg: dict, http: PoliteSession, store: Store) -> dict:
    report = {}
    for comp in cfg["competitors"]:
        for url in comp["urls"]:
            key = f"{comp['name']} ({url})"
            try:
                lines = page_lines(http.get(url).text)
                previous = store.latest_snapshot(url)
                if previous is None:
                    store.add_snapshot(url, comp["name"], lines)
                    report[key] = {"ok": True, "statut": "référence enregistrée", "lignes": len(lines)}
                    continue
                added, removed = diff_lines(previous, lines)
                if added or removed:
                    store.add_snapshot(url, comp["name"], lines)
                    store.add_change(url, comp["name"], added, removed, mentions_price(added + removed))
                report[key] = {"ok": True, "statut": "modifiée" if (added or removed) else "inchangée",
                               "ajouts": len(added), "retraits": len(removed)}
            except Exception as e:
                report[key] = {"ok": False, "erreur": describe_error(e)}
    return report
