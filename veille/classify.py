"""Classement des articles par thèmes et détection des concurrents, sans LLM.

Méthode : correspondance de mots-clés (mots entiers) sur le texte normalisé.
Score = 2 points par mot-clé distinct d'un thème « coeur », 1 point sinon, 3 points par concurrent cité.
Un article est retenu s'il touche un thème coeur (ou cite un concurrent) ET atteint le score minimal.
"""

import re
from dataclasses import dataclass

from .text import normalize


@dataclass(frozen=True)
class Theme:
    id: str
    label: str
    core: bool
    patterns: tuple[tuple[str, re.Pattern], ...]


@dataclass(frozen=True)
class CompetitorMatcher:
    name: str
    patterns: tuple[re.Pattern, ...]
    # Nom courant (homonymes) : la mention ne compte que si l'article touche aussi un thème métier.
    ambiguous: bool = False


@dataclass(frozen=True)
class Classification:
    themes: list[str]
    competitors: list[str]
    score: float
    relevant: bool


def _word_pattern(keyword: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(normalize(keyword)) + r"(?![a-z0-9])")


def compile_themes(themes_cfg: dict) -> list[Theme]:
    return [
        Theme(
            id=theme_id,
            label=t["label"],
            core=bool(t.get("core", False)),
            patterns=tuple((kw, _word_pattern(kw)) for kw in t["keywords"]),
        )
        for theme_id, t in themes_cfg.items()
    ]


def compile_competitors(competitors_cfg: list[dict]) -> list[CompetitorMatcher]:
    return [
        CompetitorMatcher(c["name"], tuple(_word_pattern(a) for a in c.get("aliases") or [c["name"]]),
                          bool(c.get("ambiguous")))
        for c in competitors_cfg
    ]


def classify(text: str, themes: list[Theme], competitors: list[CompetitorMatcher],
             min_score: float = 0) -> Classification:
    """min_score : score minimal pour retenir l'article (écarte les mentions isolées d'un mot générique)."""
    norm = normalize(text)
    matched: list[tuple[Theme, int]] = []
    score = 0.0
    for theme in themes:
        hits = sum(1 for _, pattern in theme.patterns if pattern.search(norm))
        if hits:
            matched.append((theme, hits))
            score += hits * (2 if theme.core else 1)

    has_core = any(theme.core for theme, _ in matched)
    cited = [c.name for c in competitors
             if any(p.search(norm) for p in c.patterns) and (has_core or not c.ambiguous)]
    score += 3 * len(cited)

    # Thème principal en premier : celui qui a le plus de correspondances.
    matched.sort(key=lambda m: (m[1], m[0].core), reverse=True)
    relevant = (bool(cited) or any(theme.core for theme, _ in matched)) and score >= min_score
    return Classification([t.id for t, _ in matched], cited, score, relevant)
