"""Nettoyage et normalisation de texte."""

import html
import re
import unicodedata

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# Mention automatique ajoutée par WordPress à la fin des extraits RSS.
_WP_FOOTER_RE = re.compile(r"\s*The post .{0,300}? appeared first on .{0,100}$", re.IGNORECASE | re.DOTALL)


def strip_html(value: str) -> str:
    """Retire les balises HTML, décode les entités et enlève la mention WordPress."""
    text = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", value or ""))).strip()
    return _WP_FOOTER_RE.sub("", text).strip()


def normalize(value: str) -> str:
    """Minuscules, sans accents, espaces simples : base de toutes les comparaisons."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _WS_RE.sub(" ", without_accents.lower().replace("’", "'")).strip()


def truncate(value: str, max_chars: int) -> str:
    """Coupe proprement à la fin d'un mot."""
    if len(value) <= max_chars:
        return value
    cut = value[:max_chars].rsplit(" ", 1)[0]
    return cut.rstrip(",;:.") + "…"


def title_key(title: str) -> str:
    """Clé de déduplication : le même titre repris par deux sources ne compte qu'une fois."""
    return re.sub(r"[^a-z0-9]+", " ", normalize(title)).strip()
