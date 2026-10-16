"""Per-unit optimizer context shared by all modes: archetypes, artifact hints,
opening-turn capabilities, speed leads and baseline (current) assignments."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from desktop_app.domain.artifact_effects import artifact_effect_is_legacy
from desktop_app.i18n import tr


_ARTIFACT_HINT_CACHE_VERSION = "2026-02-19.2"
ARTIFACT_TOP_EFFECT_COUNT = 4
_HINT_SLOT_KEYS = (
    "bomb_slots",
    "guaranteed_crit_slots",
    "recovery_slots",
    "debuff_slots",
    "preferred_crit_slots",
    "preferred_recovery_slots",
    "preferred_debuff_slots",
)
_HINT_TOP_EFFECT_KEYS = ("top_sub_effect_ids", "top_attribute_effect_ids", "top_type_effect_ids")
_HINT_KEYS = _HINT_SLOT_KEYS + ("preferred_effect_ids",) + _HINT_TOP_EFFECT_KEYS


def user_facing_result_message(window, ok: bool, detailed: str) -> str:
    if bool(getattr(window, "_show_extra_info_enabled", lambda: False)()):
        return str(detailed or "")
    return tr("opt.ok") if bool(ok) else tr("opt.partial_fail")


def store_compare_snapshot_from_build_dialog(window, mode: str, dlg) -> None:
    mode_key = str(mode or "").strip().lower()
    if not mode_key:
        return
    store = dict(getattr(window, "_loaded_current_runes_compare_by_mode", {}) or {})
    snap = dlg.loaded_current_runes_snapshot()
    if not isinstance(snap, dict):
        store.pop(mode_key, None)
        window._loaded_current_runes_compare_by_mode = store
        return
    runes_by_unit: Dict[int, Dict[int, int]] = {}
    artifacts_by_unit: Dict[int, Dict[int, int]] = {}
    for uid, by_slot in dict(snap.get("runes_by_unit") or {}).items():
        ui = int(uid or 0)
        if ui <= 0:
            continue
        clean_slots = {
            int(slot): int(rid)
            for slot, rid in dict(by_slot or {}).items()
            if 1 <= int(slot or 0) <= 6 and int(rid or 0) > 0
        }
        if clean_slots:
            runes_by_unit[int(ui)] = clean_slots
    for uid, by_type in dict(snap.get("artifacts_by_unit") or {}).items():
        ui = int(uid or 0)
        if ui <= 0:
            continue
        clean_types = {
            int(art_type): int(aid)
            for art_type, aid in dict(by_type or {}).items()
            if int(art_type or 0) in (1, 2) and int(aid or 0) > 0
        }
        if clean_types:
            artifacts_by_unit[int(ui)] = clean_types
    if runes_by_unit or artifacts_by_unit:
        store[mode_key] = {
            "runes_by_unit": runes_by_unit,
            "artifacts_by_unit": artifacts_by_unit,
        }
    else:
        store.pop(mode_key, None)
    window._loaded_current_runes_compare_by_mode = store


def baseline_assignments_for_mode(
    window, mode: str, unit_ids: List[int]
) -> Tuple[Dict[int, Dict[int, int]], Dict[int, Dict[int, int]]]:
    mode_key = str(mode or "").strip().lower()
    if not mode_key:
        return {}, {}
    unit_set = {int(uid) for uid in (unit_ids or []) if int(uid) > 0}
    if not unit_set:
        return {}, {}
    compare_store = dict(getattr(window, "_loaded_current_runes_compare_by_mode", {}) or {})
    snap = dict(compare_store.get(mode_key, {}) or {})
    runes_by_unit: Dict[int, Dict[int, int]] = {}
    for uid, by_slot in dict(snap.get("runes_by_unit") or {}).items():
        ui = int(uid or 0)
        if ui <= 0 or ui not in unit_set:
            continue
        slots = {
            int(slot): int(rid)
            for slot, rid in dict(by_slot or {}).items()
            if 1 <= int(slot or 0) <= 6 and int(rid or 0) > 0
        }
        if slots:
            runes_by_unit[int(ui)] = slots
    arts_by_unit: Dict[int, Dict[int, int]] = {}
    for uid, by_type in dict(snap.get("artifacts_by_unit") or {}).items():
        ui = int(uid or 0)
        if ui <= 0 or ui not in unit_set:
            continue
        types = {
            int(t): int(aid)
            for t, aid in dict(by_type or {}).items()
            if int(t or 0) in (1, 2) and int(aid or 0) > 0
        }
        if types:
            arts_by_unit[int(ui)] = types
    return runes_by_unit, arts_by_unit


def team_has_spd_buff_by_uid(window, teams: List[List[int]]) -> Dict[int, bool]:
    out: Dict[int, bool] = {}
    mdb = getattr(window, "monster_db", None)
    account = getattr(window, "account", None)
    if mdb is None or account is None:
        return out
    units_by_id = dict(getattr(account, "units_by_id", {}) or {})
    for team in (teams or []):
        ids = [int(uid) for uid in (team or []) if int(uid or 0) > 0]
        if not ids:
            continue
        has_spd = False
        for uid in ids:
            unit = units_by_id.get(int(uid))
            master_id = int(getattr(unit, "unit_master_id", 0) or 0) if unit is not None else 0
            if master_id > 0 and bool(dict(mdb.turn_effect_capability_for(int(master_id)) or {}).get("has_spd_buff", False)):
                has_spd = True
                break
        for uid in ids:
            out[int(uid)] = bool(has_spd)
    return out


def _normalize_hint_payload(raw: Dict[str, Any] | None) -> Dict[str, List[int]]:
    data = dict(raw or {})
    out: Dict[str, List[int]] = {}
    for key in _HINT_KEYS:
        vals: List[int] = []
        seen: Set[int] = set()
        for x in (data.get(key) or []):
            try:
                value = int(x or 0)
            except Exception:
                continue
            if key in _HINT_SLOT_KEYS:
                if not 1 <= value <= 4:
                    continue
            elif value <= 0 or artifact_effect_is_legacy(int(value)):
                continue
            if value in seen:
                continue
            seen.add(value)
            vals.append(value)
            if key in _HINT_TOP_EFFECT_KEYS and len(vals) >= ARTIFACT_TOP_EFFECT_COUNT:
                break
        out[key] = vals[:ARTIFACT_TOP_EFFECT_COUNT] if key in _HINT_TOP_EFFECT_KEYS else sorted(vals)
    return out


def _hint_payload_has_values(payload: Dict[str, List[int]] | None) -> bool:
    data = dict(payload or {})
    return any(bool(data.get(k)) for k in _HINT_KEYS)


def _load_monster_artifact_preferences(path: Path) -> Dict[int, Dict[str, List[int]]]:
    try:
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        by_id = raw.get("by_com2us_id", raw) if isinstance(raw, dict) else None
        if not isinstance(by_id, dict):
            return {}
        out: Dict[int, Dict[str, List[int]]] = {}
        for k, v in by_id.items():
            try:
                mid = int(k or 0)
            except Exception:
                continue
            if mid <= 0 or not isinstance(v, dict):
                continue
            base_stars = int(v.get("base_stars", 0) or 0)
            awaken_level = int(v.get("awaken_level", 1) or 0)
            if 0 < base_stars <= 1 or awaken_level <= 0:
                continue
            payload = _normalize_hint_payload(dict(v))
            if _hint_payload_has_values(payload):
                out[int(mid)] = payload
        return out
    except Exception:
        return {}


def _load_artifact_skill_hint_cache(path: Path) -> Dict[int, Dict[str, List[int]]]:
    try:
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        # Only the current versioned format; legacy flat caches carry stale hint semantics.
        if not isinstance(raw, dict) or "hints" not in raw:
            return {}
        if str(raw.get("version") or "").strip() != _ARTIFACT_HINT_CACHE_VERSION:
            return {}
        out: Dict[int, Dict[str, List[int]]] = {}
        for k, v in dict(raw.get("hints") or {}).items():
            try:
                mid = int(k or 0)
            except Exception:
                continue
            if mid <= 0:
                continue
            payload = _normalize_hint_payload(dict(v or {}))
            if _hint_payload_has_values(payload):
                out[int(mid)] = payload
        return out
    except Exception:
        return {}


def _merge_hint_payloads(*payloads: Dict[str, List[int]]) -> Dict[str, List[int]]:
    merged_set: Dict[str, Set[int]] = {}
    merged_top: Dict[str, List[int]] = {k: [] for k in _HINT_TOP_EFFECT_KEYS}
    for p in payloads:
        for key, vals in _normalize_hint_payload(p).items():
            if key in _HINT_TOP_EFFECT_KEYS:
                for v in (vals or []):
                    vi = int(v or 0)
                    if vi <= 0 or vi in merged_top[key]:
                        continue
                    merged_top[key].append(vi)
                    if len(merged_top[key]) >= ARTIFACT_TOP_EFFECT_COUNT:
                        break
                continue
            merged_set.setdefault(key, set()).update(int(v) for v in (vals or []) if int(v) > 0)
    out = {k: sorted(v) for k, v in merged_set.items()}
    for key in _HINT_TOP_EFFECT_KEYS:
        if merged_top.get(key):
            out[key] = list(merged_top[key][:ARTIFACT_TOP_EFFECT_COUNT])
    return out


def _master_ids(window, unit_ids: List[int]) -> Dict[int, int]:
    out: Dict[int, int] = {}
    if not window.account:
        return out
    for uid in [int(x) for x in (unit_ids or []) if int(x) > 0]:
        unit = window.account.units_by_id.get(int(uid))
        mid = int(unit.unit_master_id or 0) if unit is not None else 0
        if mid > 0:
            out[int(uid)] = mid
    return out


def optimizer_artifact_hints_by_uid(window, unit_ids: List[int]) -> Dict[int, Dict[str, List[int]]]:
    config_dir = Path(window.config_dir)
    cache = _load_artifact_skill_hint_cache(config_dir / "artifact_skill_hints_cache.json")
    local_pref_by_mid = _load_monster_artifact_preferences(config_dir / "monster_artifact_preferences.json")
    out: Dict[int, Dict[str, List[int]]] = {}
    for uid, mid in _master_ids(window, unit_ids).items():
        hints = _normalize_hint_payload(
            _merge_hint_payloads(
                dict(local_pref_by_mid.get(int(mid), {}) or {}),
                dict(cache.get(int(mid), {}) or {}),
            )
        )
        if _hint_payload_has_values(hints):
            out[int(uid)] = dict(hints)
    return out


def _load_archetype_cache(path: Path) -> Dict[int, str]:
    try:
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        out: Dict[int, str] = {}
        for k, v in dict(raw or {}).items():
            try:
                mid = int(k or 0)
            except Exception:
                continue
            archetype = str(v or "").strip()
            if mid > 0 and archetype:
                out[int(mid)] = archetype
        return out
    except Exception:
        return {}


def optimizer_archetype_by_uid(window, unit_ids: List[int]) -> Dict[int, str]:
    # File name kept for existing user data.
    cache = _load_archetype_cache(Path(window.config_dir) / "arena_archetype_cache.json")
    out: Dict[int, str] = {}
    for uid, mid in _master_ids(window, unit_ids).items():
        archetype = str(window.monster_db.archetype_for(int(mid)) or "").strip()
        if (not archetype or archetype.lower() == "unknown") and int(mid) in cache:
            archetype = str(cache.get(int(mid), "") or "").strip()
        if archetype:
            out[int(uid)] = archetype
    return out


def effect_capabilities_by_unit(window, unit_ids: List[int]) -> Dict[int, Dict[str, object]]:
    """Opening-turn skills per unit (SPD buff, ATB boost) for the turn-effect controls."""
    out: Dict[int, Dict[str, object]] = {}
    for uid, mid in _master_ids(window, unit_ids).items():
        base = dict(window.monster_db.turn_effect_capability_for(mid) or {})
        has_atb_boost = bool(base.get("has_atb_boost", False))
        max_atb_boost_pct = int(base.get("max_atb_boost_pct", 0) or 0)
        if has_atb_boost and max_atb_boost_pct <= 0:
            max_atb_boost_pct = 100
        out[int(uid)] = {
            "has_spd_buff": bool(base.get("has_spd_buff", False)),
            "has_atb_boost": has_atb_boost,
            "max_atb_boost_pct": int(max_atb_boost_pct),
            "spd_buff_skill_icon": str(base.get("spd_buff_skill_icon", "") or ""),
            "atb_boost_skill_icon": str(base.get("atb_boost_skill_icon", "") or ""),
        }
    return out


def speed_leader_bonus_map(
    window,
    team_unit_ids: List[int],
    leader_uid: int = 0,
    lead_pct_override: int = 0,
) -> Dict[int, int]:
    """Flat SPD each unit gets from the team's speed lead (override % or the leader's own skill)."""
    out: Dict[int, int] = {}
    ids = [int(uid) for uid in (team_unit_ids or []) if int(uid) > 0]
    if not ids or not window.account:
        return out
    candidate_leader_uid = int(leader_uid or 0)
    if candidate_leader_uid <= 0 or candidate_leader_uid not in ids:
        candidate_leader_uid = int(ids[0])
    pct = int(lead_pct_override or 0)
    if pct <= 0:
        leader = window.account.units_by_id.get(int(candidate_leader_uid))
        if leader is None:
            return out
        ls = window.monster_db.leader_skill_for(int(leader.unit_master_id))
        if not ls or str(ls.stat) != "SPD%" or str(ls.area) not in ("Arena", "General"):
            return out
        pct = int(ls.amount or 0)
    if pct <= 0:
        return out
    for uid in ids:
        u = window.account.units_by_id.get(int(uid))
        if u is not None:
            out[int(uid)] = int(int(u.base_spd or 0) * pct / 100)
    return out
