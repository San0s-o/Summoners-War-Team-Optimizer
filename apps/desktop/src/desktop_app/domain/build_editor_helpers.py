from __future__ import annotations

from itertools import combinations, product
from math import ceil
from typing import TYPE_CHECKING, Any, Dict, List, Set, Tuple

from desktop_app.domain.artifact_effects import ARTIFACT_EFFECT_IDS_BY_ARTIFACT_TYPE
from desktop_app.domain.models import AccountData
from desktop_app.domain.presets import (
    MAINSTAT_KEYS,
    SET_NAMES,
    SET_SIZES,
)
from desktop_app.domain.speed_ticks import max_spd_for_tick, min_spd_for_tick

if TYPE_CHECKING:
    from desktop_app.services.cloud_learning_service import BuildPreferenceTrend

_MIN_BASE_STATS = ("SPD", "HP", "ATK", "DEF")
_MIN_BASE_AWARE_STATS = ("SPD", "HP", "ATK", "DEF", "CR", "CD", "RES", "ACC")


def unit_master_id_for_unit(account: AccountData | None, unit_id: int) -> int:
    uid = int(unit_id or 0)
    if uid <= 0:
        return 0
    if account:
        u = account.units_by_id.get(int(uid))
        if u is not None and int(getattr(u, "unit_master_id", 0) or 0) > 0:
            return int(getattr(u, "unit_master_id", 0) or 0)
    return int(uid)


def unit_base_stats_for_min(account: AccountData | None, unit_id: int) -> Dict[str, int]:
    empty: Dict[str, int] = {"SPD": 0, "HP": 0, "ATK": 0, "DEF": 0, "CR": 0, "CD": 0, "RES": 0, "ACC": 0}
    if not account:
        return empty
    unit = account.units_by_id.get(int(unit_id))
    if unit is None:
        return empty
    return {
        "SPD": int(unit.base_spd or 0),
        "HP": int((unit.base_con or 0) * 15),
        "ATK": int(unit.base_atk or 0),
        "DEF": int(unit.base_def or 0),
        "CR": int(unit.crit_rate or 15),
        "CD": int(unit.crit_dmg or 50),
        "RES": int(unit.base_res or 15),
        "ACC": int(unit.base_acc or 0),
    }


def min_mode_for_build(min_cfg: Dict[str, int]) -> str:
    for key in _MIN_BASE_STATS:
        if int(min_cfg.get(f"{key}_NO_BASE", 0) or 0) > 0:
            return "without_base"
    return "with_base"


def min_value_for_build(min_cfg: Dict[str, int], key: str, mode: str, base_stats: Dict[str, int]) -> int:
    stat_key = str(key).upper()
    if str(mode) == "without_base" and stat_key in _MIN_BASE_STATS:
        return int(min_cfg.get(f"{stat_key}_NO_BASE", 0) or 0)
    if str(mode) == "with_base" and stat_key in _MIN_BASE_AWARE_STATS:
        raw_total = int(min_cfg.get(stat_key, 0) or 0)
        base_val = int(base_stats.get(stat_key, 0) or 0)
        return max(0, raw_total - base_val)
    return int(min_cfg.get(stat_key, 0) or 0)


def element_name_for_master_id(master_id: int) -> str:
    elem_map = {1: "Water", 2: "Fire", 3: "Wind", 4: "Light", 5: "Dark"}
    m = int(master_id or 0)
    if m <= 0:
        return ""
    return str(elem_map.get(int(m % 10), "") or "")


def normalize_mainstat_pref_key(value: Any) -> str:
    raw = str(value or "").strip().upper().replace(" ", "")
    if not raw:
        return ""
    mapping = {
        "HP": "HP%",
        "HP%": "HP%",
        "HPP": "HP%",
        "ATK": "ATK%",
        "ATK%": "ATK%",
        "ATKP": "ATK%",
        "DEF": "DEF%",
        "DEF%": "DEF%",
        "DEFP": "DEF%",
        "SPD": "SPD",
        "CR": "CR",
        "CD": "CD",
        "RES": "RES",
        "ACC": "ACC",
    }
    key = mapping.get(raw, raw)
    return str(key) if str(key) in MAINSTAT_KEYS else ""


def parse_set_options_to_slot_ids(set_options: List[List[str]]) -> Tuple[List[int], List[int], List[int]]:
    parsed: List[List[int]] = []
    for opt in (set_options or []):
        if not isinstance(opt, list):
            continue
        row: List[int] = []
        for name in opt:
            sid = next((int(k) for k, sname in SET_NAMES.items() if sname == str(name)), 0)
            if sid > 0:
                row.append(int(sid))
        if row:
            parsed.append(row)

    if not parsed:
        return [], [], []

    lengths = {len(r) for r in parsed if r}
    if len(lengths) == 1 and 1 <= next(iter(lengths)) <= 3:
        width = int(next(iter(lengths)))
        slots: List[List[int]] = []
        for pos in range(width):
            vals: List[int] = []
            seen: Set[int] = set()
            for row in parsed:
                sid = int(row[pos])
                if sid <= 0 or sid in seen:
                    continue
                seen.add(sid)
                vals.append(sid)
            slots.append(vals)
        while len(slots) < 3:
            slots.append([])
        return slots[0], slots[1], slots[2]

    first = [int(x) for x in (parsed[0] if parsed else [])]
    while len(first) < 3:
        first.append(0)
    return [first[0]] if first[0] > 0 else [], [first[1]] if first[1] > 0 else [], [first[2]] if first[2] > 0 else []


def rune_pref_slot_set_ids(entry: Dict[str, Any]) -> Tuple[List[int], List[int], List[int]]:
    combos_raw = list(entry.get("top_set_combos") or []) + list(entry.get("preferred_set_combos") or [])
    combos: List[List[int]] = []
    seen_combo_keys: Set[Tuple[int, ...]] = set()
    for combo in combos_raw:
        if not isinstance(combo, (list, tuple)):
            continue
        row: List[int] = []
        for x in list(combo)[:3]:
            sid = int(x or 0)
            if sid > 0 and sid in SET_NAMES:
                row.append(int(sid))
        if row:
            key = tuple(int(v) for v in row)
            if key in seen_combo_keys:
                continue
            seen_combo_keys.add(key)
            combos.append(row)

    # Fallback: derive coverage-friendly combos from top/preferred set IDs.
    if not combos:
        ranked_ids: List[int] = []
        for sid in [int(x) for x in (entry.get("top_set_ids") or []) + (entry.get("preferred_set_ids") or [])]:
            if sid > 0 and sid in SET_NAMES and sid not in ranked_ids:
                ranked_ids.append(int(sid))
            if len(ranked_ids) >= 8:
                break
        four_sets = [sid for sid in ranked_ids if int(SET_SIZES.get(int(sid), 2) or 2) == 4]
        two_sets = [sid for sid in ranked_ids if int(SET_SIZES.get(int(sid), 2) or 2) == 2]
        if four_sets and two_sets:
            for a in four_sets:
                for b in two_sets:
                    combos.append([int(a), int(b)])
                    if len(combos) >= 12:
                        break
                if len(combos) >= 12:
                    break
        elif len(two_sets) >= 2:
            for a, b in combinations(two_sets, 2):
                combos.append([int(a), int(b)])
                if len(combos) >= 12:
                    break
        if len(two_sets) >= 3 and len(combos) < 12:
            for a, b, c in combinations(two_sets, 3):
                combos.append([int(a), int(b), int(c)])
                if len(combos) >= 12:
                    break
        elif ranked_ids:
            combos = [[int(sid)] for sid in ranked_ids[:3]]

    if combos:
        by_width: Dict[int, List[List[int]]] = {1: [], 2: [], 3: []}
        for row in combos:
            w = int(len(row))
            if 1 <= w <= 3:
                by_width[w].append(list(row))

        best_layout: Tuple[List[int], List[int], List[int]] | None = None
        best_score: Tuple[int, int] = (-1, -1)
        for width in (3, 2, 1):
            rows = list(by_width.get(int(width), []) or [])
            if not rows:
                continue
            slots: List[List[int]] = []
            for pos in range(int(width)):
                vals: List[int] = []
                seen_vals: Set[int] = set()
                for row in rows:
                    sid = int(row[pos] or 0)
                    if sid <= 0 or sid in seen_vals:
                        continue
                    seen_vals.add(int(sid))
                    vals.append(int(sid))
                slots.append(vals)
            while len(slots) < 3:
                slots.append([])
            s1, s2, s3 = slots[0], slots[1], slots[2]
            if width == 3:
                if any(int(SET_SIZES.get(int(sid), 2) or 2) != 2 for sid in (s1 + s2)):
                    continue
            covered = len(rows)
            score = (int(covered), int(width))
            if score > best_score:
                best_score = score
                best_layout = (list(s1), list(s2), list(s3))

        if best_layout is not None:
            return best_layout

        first = list(combos[0])
        while len(first) < 3:
            first.append(0)
        return (
            [int(first[0])] if int(first[0]) > 0 else [],
            [int(first[1])] if int(first[1]) > 0 else [],
            [int(first[2])] if int(first[2]) > 0 else [],
        )

    top_set_ids = [int(x) for x in (entry.get("top_set_ids") or []) if int(x) > 0 and int(x) in SET_NAMES]
    while len(top_set_ids) < 3:
        top_set_ids.append(0)
    return (
        [int(top_set_ids[0])] if int(top_set_ids[0]) > 0 else [],
        [int(top_set_ids[1])] if int(top_set_ids[1]) > 0 else [],
        [int(top_set_ids[2])] if int(top_set_ids[2]) > 0 else [],
    )


def rune_pref_mainstats_by_slot(entry: Dict[str, Any]) -> Dict[int, List[str]]:
    out: Dict[int, List[str]] = {2: [], 4: [], 6: []}
    by_slot = entry.get("top_mainstats_by_slot")
    if isinstance(by_slot, dict):
        for slot in (2, 4, 6):
            vals_raw = by_slot.get(str(slot), by_slot.get(int(slot), []))
            for raw in list(vals_raw or []):
                key = normalize_mainstat_pref_key(raw)
                if key and key not in out[slot]:
                    out[slot].append(key)

    combos_raw = list(entry.get("top_mainstat_combos_246") or [])
    for combo in combos_raw:
        if not isinstance(combo, (list, tuple)) or len(combo) < 3:
            continue
        for idx, slot in enumerate((2, 4, 6)):
            key = normalize_mainstat_pref_key(combo[idx])
            if key and key not in out[slot]:
                out[slot].append(key)

    return {
        2: [str(x) for x in out[2] if str(x) in MAINSTAT_KEYS],
        4: [str(x) for x in out[4] if str(x) in MAINSTAT_KEYS],
        6: [str(x) for x in out[6] if str(x) in MAINSTAT_KEYS],
    }


def artifact_pref_from_entry(entry: Dict[str, Any]) -> Tuple[Dict[str, List[str]], Dict[str, List[int]]]:
    artifact_focus: Dict[str, List[str]] = {}
    focus_raw = dict(entry.get("artifact_focus") or {})
    for key in ("attribute", "type"):
        selected = ""
        for item in list(focus_raw.get(key, []) or []):
            cand = str(item or "").strip().upper()
            if cand in ("HP", "ATK", "DEF"):
                selected = cand
                break
        if selected:
            artifact_focus[str(key)] = [selected]

    artifact_substats: Dict[str, List[int]] = {}
    subs_raw = dict(entry.get("artifact_substats") or {})
    for key in ("attribute", "type"):
        vals: List[int] = []
        seen: Set[int] = set()
        for item in list(subs_raw.get(key, []) or []):
            try:
                eid = int(item or 0)
            except Exception:
                eid = 0
            if eid <= 0 or eid in seen:
                continue
            seen.add(eid)
            vals.append(int(eid))
            if len(vals) >= 2:
                break
        if vals:
            artifact_substats[str(key)] = list(vals)

    return artifact_focus, artifact_substats


def set_slots_from_community_trend(
    trend: BuildPreferenceTrend,
    combo_limit: int,
) -> Tuple[List[int], List[int], List[int]]:
    top_n = max(1, int(combo_limit))
    set_options: List[List[str]] = []
    seen: Set[Tuple[str, ...]] = set()
    for combo in list(trend.top_set_combos or [])[:top_n]:
        names: List[str] = []
        total_pieces = 0
        for sid in list(combo or [])[:3]:
            sid_i = int(sid or 0)
            set_name = str(SET_NAMES.get(int(sid_i), "") or "")
            if not set_name:
                continue
            names.append(set_name)
            total_pieces += int(SET_SIZES.get(int(sid_i), 2) or 2)
        if not names or int(total_pieces) > 6:
            continue
        key = tuple(names)
        if key in seen:
            continue
        seen.add(key)
        set_options.append(names)
        if len(set_options) >= 16:
            break
    return parse_set_options_to_slot_ids(set_options)


def mainstats_from_community_trend(
    trend: BuildPreferenceTrend,
    mainstat_limit: int,
) -> Dict[int, List[str]]:
    top_n = max(1, int(mainstat_limit))
    raw_slot_map: Dict[str, List[str]] = {
        "2": [str(x) for x in list((trend.mainstats_by_slot or {}).get(2, []) or [])[:top_n]],
        "4": [str(x) for x in list((trend.mainstats_by_slot or {}).get(4, []) or [])[:top_n]],
        "6": [str(x) for x in list((trend.mainstats_by_slot or {}).get(6, []) or [])[:top_n]],
    }
    entry = {
        "top_mainstats_by_slot": raw_slot_map,
        "top_mainstat_combos_246": [
            list(x)
            for x in list(trend.top_mainstat_combos_246 or [])[:top_n]
            if isinstance(x, list)
        ],
    }
    by_slot = rune_pref_mainstats_by_slot(entry)
    for slot in (2, 4, 6):
        vals = [str(x) for x in list(by_slot.get(int(slot), []) or [])]
        by_slot[int(slot)] = vals[:top_n]
    return by_slot


def collect_artifact_substat_options_by_type(account: AccountData | None) -> Dict[int, List[int]]:
    out: Dict[int, Set[int]] = {
        1: set(ARTIFACT_EFFECT_IDS_BY_ARTIFACT_TYPE.get(1, [])),
        2: set(ARTIFACT_EFFECT_IDS_BY_ARTIFACT_TYPE.get(2, [])),
    }
    if not account:
        return {1: sorted(out[1]), 2: sorted(out[2])}
    for art in (account.artifacts or []):
        art_type = int(getattr(art, "type_", 0) or 0)
        if art_type not in (1, 2):
            continue
        for sec in (getattr(art, "sec_effects", []) or []):
            if not sec:
                continue
            try:
                eid = int(sec[0] or 0)
            except Exception:
                continue
            if eid > 0:
                out[art_type].add(eid)
    return {1: sorted(out[1]), 2: sorted(out[2])}


def can_load_current_runes(account: AccountData | None, mode: str) -> bool:
    mode_key = str(mode or "").strip().lower()
    return bool(account) and mode_key in ("siege", "wgb", "rta", "arena_rush")


def rune_mode_for_mode(mode: str) -> str:
    mode_key = str(mode or "").strip().lower()
    if mode_key == "rta":
        return "rta"
    if mode_key in ("siege", "wgb"):
        return "siege"
    if mode_key == "arena_rush":
        return "pve"
    return "pve"


def equipped_artifacts_for_unit(account: AccountData | None, unit_id: int, rune_mode: str) -> Dict[int, int]:
    if not account:
        return {}
    uid = int(unit_id or 0)
    if uid <= 0:
        return {}
    by_id = {int(a.artifact_id): a for a in (account.artifacts or [])}
    out: Dict[int, int] = {}
    mode_key = str(rune_mode).strip().lower()
    if mode_key in ("siege", "guild"):
        for aid in (account.guild_artifact_equip.get(int(uid), []) or []):
            art = by_id.get(int(aid))
            if art is None:
                continue
            art_type = int(getattr(art, "type_", 0) or 0)
            if art_type in (1, 2) and art_type not in out:
                out[int(art_type)] = int(aid)
        if len(out) >= 2:
            return out
    elif mode_key == "rta":
        for aid in (account.rta_artifact_equip.get(int(uid), []) or []):
            art = by_id.get(int(aid))
            if art is None:
                continue
            art_type = int(getattr(art, "type_", 0) or 0)
            if art_type in (1, 2) and art_type not in out:
                out[int(art_type)] = int(aid)
        if len(out) >= 2:
            return out
    for art in (account.artifacts or []):
        if int(getattr(art, "occupied_id", 0) or 0) != int(uid):
            continue
        art_type = int(getattr(art, "type_", 0) or 0)
        aid = int(getattr(art, "artifact_id", 0) or 0)
        if art_type in (1, 2) and aid > 0 and art_type not in out:
            out[int(art_type)] = int(aid)
    return out


def capture_current_runes_snapshot(
    account: AccountData | None,
    unit_ids: List[int],
    rune_mode: str,
) -> Dict[str, Any]:
    if not account:
        return {}
    runes_by_unit: Dict[int, Dict[int, int]] = {}
    artifacts_by_unit: Dict[int, Dict[int, int]] = {}
    for unit_id in [int(uid) for uid in (unit_ids or []) if int(uid) > 0]:
        equipped = account.equipped_runes_for(int(unit_id), str(rune_mode))
        slot_map: Dict[int, int] = {}
        for rune in (equipped or []):
            slot = int(getattr(rune, "slot_no", 0) or 0)
            rid = int(getattr(rune, "rune_id", 0) or 0)
            if 1 <= slot <= 6 and rid > 0:
                slot_map[int(slot)] = int(rid)
        if slot_map:
            runes_by_unit[int(unit_id)] = slot_map
        art_map = equipped_artifacts_for_unit(account, int(unit_id), str(rune_mode))
        if art_map:
            artifacts_by_unit[int(unit_id)] = art_map
    return {
        "mode": str(rune_mode),
        "runes_by_unit": runes_by_unit,
        "artifacts_by_unit": artifacts_by_unit,
    }


def has_spd_buff_before_turn(
    team_order: List[int],
    team_effect_cfg: Dict[int, Dict[str, Any]],
    target_uid: int,
) -> bool:
    order = [int(uid) for uid in (team_order or []) if int(uid) > 0]
    tu = int(target_uid or 0)
    if tu <= 0 or tu not in order:
        return False
    pos_target = order.index(int(tu))
    for pos, caster_uid in enumerate(order):
        if pos >= pos_target:
            break
        cfg = dict((team_effect_cfg or {}).get(int(caster_uid), {}) or {})
        if bool(cfg.get("applies_spd_buff", False)):
            return True
    return False


def atb_boost_before_turn_pct(
    team_order: List[int],
    team_effect_cfg: Dict[int, Dict[str, Any]],
    target_uid: int,
) -> float:
    order = [int(uid) for uid in (team_order or []) if int(uid) > 0]
    tu = int(target_uid or 0)
    if tu <= 0 or tu not in order:
        return 0.0
    pos_target = order.index(int(tu))
    total = 0.0
    for pos, caster_uid in enumerate(order):
        if pos >= pos_target:
            break
        cfg = dict((team_effect_cfg or {}).get(int(caster_uid), {}) or {})
        total += max(0.0, float(cfg.get("atb_boost_pct", 0.0) or 0.0))
    return max(0.0, min(95.0, float(total)))


def validate_order_tick_plausibility(
    team_orders: List[List[int]],
    tick_by_uid: Dict[int, int],
    effect_teams: List[Dict[int, Dict[str, Any]]],
    mode: str,
    unit_labels: Dict[int, str],
    order_team_titles: List[str],
) -> None:
    is_arena_rush = str(mode or "").strip().lower() == "arena_rush"
    for team_index, team_order in enumerate(team_orders):
        order = [int(uid) for uid in (team_order or []) if int(uid) > 0]
        if len(order) <= 1:
            continue
        team_title = (
            order_team_titles[team_index]
            if team_index < len(order_team_titles) and order_team_titles[team_index]
            else f"Team {team_index + 1}"
        )
        effect_cfg = dict(effect_teams[int(team_index)]) if int(team_index) < len(effect_teams) else {}

        floor_by_uid: Dict[int, int] = {}
        cap_by_uid: Dict[int, int] = {}
        for uid in order:
            tick = int(tick_by_uid.get(int(uid), 0) or 0)
            if tick <= 0:
                continue
            min_tick_spd = int(min_spd_for_tick(int(tick), mode) or 0)
            max_tick_spd = int(max_spd_for_tick(int(tick), mode) or 0)
            floor = int(min_tick_spd)
            if is_arena_rush and min_tick_spd > 0:
                speed_factor = 1.0
                if has_spd_buff_before_turn(order, effect_cfg, int(uid)):
                    speed_factor += 0.30
                atb_before = atb_boost_before_turn_pct(order, effect_cfg, int(uid))
                atb_factor = 1.0 - (max(0.0, float(atb_before)) / 100.0)
                atb_factor = max(0.05, min(1.0, atb_factor))
                floor = int(ceil((float(min_tick_spd) * float(atb_factor)) / max(1e-9, float(speed_factor))))
            if floor > 0:
                floor_by_uid[int(uid)] = int(floor)
            if max_tick_spd > 0:
                cap_by_uid[int(uid)] = int(max_tick_spd)

        for uid in order:
            ui = int(uid)
            floor = int(floor_by_uid.get(ui, 0) or 0)
            cap = int(cap_by_uid.get(ui, 0) or 0)
            if floor > 0 and cap > 0 and floor > cap:
                label = unit_labels.get(int(ui), str(ui))
                tick = int(tick_by_uid.get(int(ui), 0) or 0)
                raise ValueError(
                    f"Plausibilitaetsfehler ({team_title}): {label} hat ungueltigen Tick {tick} "
                    f"(minimale SPD {floor} > maximale SPD {cap})."
                )

        for idx in range(1, len(order)):
            prev_uid = int(order[idx - 1])
            cur_uid = int(order[idx])
            prev_cap = int(cap_by_uid.get(int(prev_uid), 0) or 0)
            cur_floor = int(floor_by_uid.get(int(cur_uid), 0) or 0)
            if prev_cap > 0 and cur_floor > 0 and prev_cap <= cur_floor:
                prev_label = unit_labels.get(int(prev_uid), str(prev_uid))
                cur_label = unit_labels.get(int(cur_uid), str(cur_uid))
                raise ValueError(
                    f"Plausibilitaetsfehler ({team_title}): Turnorder Position {idx}->{idx + 1} nicht stimmig. "
                    f"{prev_label} kann mit max. SPD {prev_cap} nicht vor {cur_label} "
                    f"(min. SPD {cur_floor}) ziehen."
                )


def sanitize_rune_snapshot(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize a raw rune snapshot dict: coerce keys to int, validate ranges."""
    runes_raw = dict(snap.get("runes_by_unit") or {})
    artifacts_raw = dict(snap.get("artifacts_by_unit") or {})
    runes_by_unit: Dict[int, Dict[int, int]] = {}
    artifacts_by_unit: Dict[int, Dict[int, int]] = {}
    for uid, by_slot in runes_raw.items():
        ui = int(uid or 0)
        if ui <= 0:
            continue
        clean_slots: Dict[int, int] = {}
        for slot, rid in dict(by_slot or {}).items():
            s = int(slot or 0)
            r = int(rid or 0)
            if 1 <= s <= 6 and r > 0:
                clean_slots[int(s)] = int(r)
        if clean_slots:
            runes_by_unit[int(ui)] = clean_slots
    for uid, by_type in artifacts_raw.items():
        ui = int(uid or 0)
        if ui <= 0:
            continue
        clean_types: Dict[int, int] = {}
        for art_type, aid in dict(by_type or {}).items():
            t = int(art_type or 0)
            a = int(aid or 0)
            if t in (1, 2) and a > 0:
                clean_types[int(t)] = int(a)
        if clean_types:
            artifacts_by_unit[int(ui)] = clean_types
    return {
        "mode": str(snap.get("mode", "")),
        "runes_by_unit": runes_by_unit,
        "artifacts_by_unit": artifacts_by_unit,
    }


def set_id_combos_to_names(normalized_options: List[List[int]]) -> List[List[str]]:
    """Convert a list of set-ID combos to set-name combos (for Build storage)."""
    result: List[List[str]] = []
    for opt in normalized_options:
        names = [SET_NAMES[sid] for sid in opt if sid in SET_NAMES]
        if names:
            result.append(names)
    return result


_NO_BASE_STATS = frozenset(("SPD", "HP", "ATK", "DEF"))


def normalize_set_id_groups(groups: List[List[int]]) -> List[List[int]]:
    """Cartesian product of set-ID option groups, filtered to valid combos (≤6 total pieces, deduped)."""
    if not groups:
        return []
    normalized: List[List[int]] = []
    seen: Set[Tuple[int, ...]] = set()
    for opt in product(*groups):
        cleaned = [int(sid) for sid in opt if int(sid) > 0 and int(sid) in SET_NAMES]
        if not cleaned:
            continue
        total_pieces = sum(int(SET_SIZES.get(sid, 2)) for sid in cleaned)
        if total_pieces > 6:
            continue
        key = tuple(cleaned)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
    return normalized


def build_min_stats(min_mode: str, base_stats: Dict[str, int], raw_bonus: Dict[str, int]) -> Dict[str, int]:
    """Convert per-stat bonus spin values into the final min_stats dict, applying base offsets."""
    without_base = str(min_mode or "with_base") == "without_base"
    result: Dict[str, int] = {}
    for stat, bonus in (raw_bonus or {}).items():
        b = int(bonus or 0)
        if b <= 0:
            continue
        base = int((base_stats or {}).get(str(stat), 0) or 0)
        if str(stat) in _NO_BASE_STATS:
            result[f"{stat}_NO_BASE" if without_base else str(stat)] = b if without_base else base + b
        else:
            result[str(stat)] = b if without_base else base + b
    return result


def slot_ids_from_equipped_runes(equipped: List[Any]) -> Tuple[List[int], List[int], List[int]]:
    """Given a list of equipped rune objects, return which set IDs belong in each of the 3 set slots."""
    set_counts: Dict[int, int] = {}
    for r in (equipped or []):
        sid = int(getattr(r, "set_id", 0) or 0)
        if sid > 0:
            set_counts[sid] = set_counts.get(sid, 0) + 1
    active_sets: List[int] = []
    for sid, cnt in set_counts.items():
        if sid not in SET_NAMES:
            continue
        required = int(SET_SIZES.get(sid, 2))
        if required <= 0:
            continue
        for _ in range(max(0, int(cnt // required))):
            active_sets.append(int(sid))
    active_sets.sort(key=lambda s: (-int(SET_SIZES.get(s, 2)), s))
    slot1_ids: List[int] = []
    slot2_ids: List[int] = []
    slot3_ids: List[int] = []
    for sid in active_sets:
        if not slot1_ids:
            slot1_ids.append(sid)
        elif not slot2_ids:
            slot2_ids.append(sid)
        else:
            slot3_ids.append(sid)
    return slot1_ids, slot2_ids, slot3_ids


def top_set_ids_from_combos(top_set_combos: List[List[int]], max_ids: int = 6) -> List[int]:
    """Return unique set IDs appearing in the top combos, in order, up to max_ids."""
    result: List[int] = []
    for combo in top_set_combos:
        for sid in combo:
            si = int(sid or 0)
            if si > 0 and si in SET_NAMES and si not in result:
                result.append(si)
            if len(result) >= max_ids:
                return result
    return result


def merge_preferred_set_ids(new_ids: List[int], existing_ids: List[int], max_count: int = 10) -> List[int]:
    """Merge new set IDs with previously saved preferred IDs, deduped, up to max_count."""
    result: List[int] = []
    for sid in list(new_ids) + [int(x) for x in (existing_ids or []) if int(x) > 0]:
        si = int(sid or 0)
        if si > 0 and si in SET_NAMES and si not in result:
            result.append(si)
        if len(result) >= max_count:
            break
    return result


def unit_pref_metadata(
    account: AccountData | None,
    unit_id: int,
    master_id: int,
    unit_label: str,
    existing: Dict[str, Any],
) -> Dict[str, Any]:
    """Return name/element/archetype/awaken_level/base_stars fields for a pref entry."""
    meta: Dict[str, Any] = {
        "name": str(existing.get("name") or unit_label),
        "element": str(existing.get("element") or element_name_for_master_id(int(master_id))),
        "archetype": str(existing.get("archetype") or "Unknown"),
        "awaken_level": int(existing.get("awaken_level", 1) or 1),
    }
    if "base_stars" in existing:
        meta["base_stars"] = int(existing.get("base_stars", 0) or 0)
    elif account:
        unit_obj = account.units_by_id.get(int(unit_id))
        if unit_obj is not None:
            meta["base_stars"] = int(getattr(unit_obj, "unit_class", 0) or 0)
    return meta


def mainstat_combos_246(by_slot: Dict[int, List[str]], limit: int = 12) -> List[List[str]]:
    """Cartesian product of per-slot mainstat lists (slots 2, 4, 6), capped at limit entries."""
    s2 = list(by_slot.get(2) or [])
    s4 = list(by_slot.get(4) or [])
    s6 = list(by_slot.get(6) or [])
    if not s2 or not s4 or not s6:
        return []
    out: List[List[str]] = []
    for a, b, c in product(s2, s4, s6):
        out.append([str(a), str(b), str(c)])
        if len(out) >= int(max(1, int(limit or 1))):
            break
    return out


def artifact_prefs_from_trend(
    trend: BuildPreferenceTrend,
    sub_limit: int,
) -> Tuple[Dict[str, Any], Dict[str, List[int]]]:
    """Extract artifact focus and capped substats from a community trend."""
    limit = max(1, int(sub_limit))
    artifact_focus = dict(getattr(trend, "artifact_focus", None) or {})
    artifact_substats: Dict[str, List[int]] = {}
    for key in ("attribute", "type"):
        vals = [
            int(x) for x in list((getattr(trend, "artifact_substats", None) or {}).get(key, []) or [])
            if int(x) > 0
        ][:limit]
        if vals:
            artifact_substats[key] = vals
    return artifact_focus, artifact_substats
