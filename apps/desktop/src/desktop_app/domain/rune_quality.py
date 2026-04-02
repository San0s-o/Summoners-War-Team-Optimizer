"""Domain helpers for rune and artifact quality classification."""
from __future__ import annotations

from typing import List

from desktop_app.domain.models import Artifact, Rune


def rune_quality_class(rune: Rune) -> int:
    """Effective quality class of a rune (respects origin_class for ancient runes)."""
    origin = int(getattr(rune, "origin_class", 0) or 0)
    return origin if origin else int(rune.rune_class or 0)


def rune_quality_tier_key(rune: Rune) -> str:
    """Named quality tier: 'legend', 'hero', 'rare', 'magic', 'normal', or 'other'."""
    cls_id = rune_quality_class(rune)
    if cls_id in (5, 6, 15, 16):
        return "legend"
    if cls_id in (4, 14):
        return "hero"
    if cls_id in (3, 13):
        return "rare"
    if cls_id in (2, 12):
        return "magic"
    if cls_id in (1, 11):
        return "normal"
    return "other"


def artifact_quality_tier_key(art: Artifact) -> str:
    """Named quality tier for an artifact."""
    base_rank = int(getattr(art, "original_rank", 0) or 0)
    if base_rank <= 0:
        base_rank = int(art.rank or 0)
    if base_rank >= 5:
        return "legend"
    if base_rank == 4:
        return "hero"
    if base_rank == 3:
        return "rare"
    if base_rank == 2:
        return "magic"
    if base_rank == 1:
        return "normal"
    return "other"


def relevant_runes(runes: List[Rune]) -> List[Rune]:
    """Runes upgraded to +12 or higher (standard analysis threshold)."""
    return [r for r in runes if int(r.upgrade_curr or 0) >= 12]
