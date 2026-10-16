from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from ortools.sat.python import cp_model

from desktop_app.domain.models import AccountData, Rune, Artifact
from desktop_app.domain.presets import BuildStore, Build
from desktop_app.domain.speed_ticks import min_spd_for_tick
from desktop_app.engine.efficiency import rune_efficiency, artifact_efficiency
from desktop_app.engine.greedy_optimizer import (
    RUNE_SCALING_BONUS_WEIGHT,
    ARTIFACT_SCALING_BONUS_WEIGHT,
    ARTIFACT_ROLE_CONTEXT_WEIGHT,
    BASELINE_REGRESSION_GUARD_WEIGHT,
    GreedyRequest,
    GreedyResult,
    GreedyUnitResult,
    _allowed_artifacts_for_mode,
    _allowed_runes_for_mode,
    _artifact_compatible_with_unit,
    _artifact_context_score_proxy,
    _artifact_effect_value_scaled,
    _artifact_effect_roll_count,
    _artifact_hint_score,
    _artifact_hint_critical_effect_ids,
    _rune_quality_score,
    _artifact_quality_score,
    _force_swift_speed_priority,
    _arena_role_from_archetype,
    _is_attack_type_unit,
    _rune_scaling_score_proxy,
    _run_greedy_pass,
    _preferred_rune_set_ids_for_monster,
    _scaling_stat_from_hints,
    _artifact_scaling_score_proxy,
    _builds_for_unit_with_cloud_prior,
    _add_baseline_guard_shortfall,
    _add_build_constraints,
    _add_build_speed_constraints,
    _add_overcap_penalty,
    _add_unit_speed_model,
    _rune_set_hint_terms,
    _set_choice_vars,
)
from desktop_app.i18n import tr

GLOBAL_SOLVER_OVERCAP_PENALTY_SCALE = 100
GLOBAL_BASELINE_REGRESSION_GUARD_WEIGHT = 1500


def optimize_global(account: AccountData, presets: BuildStore, req: GreedyRequest) -> GreedyResult:
    unit_ids = [int(u) for u in (req.unit_ids_in_order or [])]
    if not unit_ids:
        return GreedyResult(False, tr("opt.no_units"), [])
    if req.is_cancelled and req.is_cancelled():
        return GreedyResult(False, tr("opt.cancelled"), [])

    pool = _allowed_runes_for_mode(account, req, unit_ids)
    artifact_pool = _allowed_artifacts_for_mode(account, unit_ids, req=req)
    runes_by_slot_global: Dict[int, List[Rune]] = {s: [] for s in range(1, 7)}
    for r in pool:
        if 1 <= int(r.slot_no or 0) <= 6:
            runes_by_slot_global[int(r.slot_no)].append(r)

    artifacts_by_type_global: Dict[int, List[Artifact]] = {1: [], 2: []}
    for a in artifact_pool:
        t = int(a.type_ or 0)
        if t in (1, 2):
            artifacts_by_type_global[t].append(a)

    model = cp_model.CpModel()

    # x[(uid, slot, rid)] = 1 if rune rid is assigned to uid in slot
    x: Dict[Tuple[int, int, int], cp_model.IntVar] = {}
    # xa[(uid, type, aid)] = 1 if artifact aid is assigned
    xa: Dict[Tuple[int, int, int], cp_model.IntVar] = {}
    use_build: Dict[Tuple[int, int], cp_model.IntVar] = {}
    final_speed_expr: Dict[int, cp_model.LinearExpr] = {}
    force_speed_uids: Set[int] = set()
    swift_active_by_uid: Dict[int, cp_model.IntVar] = {}
    speed_tiebreak_weight_by_uid: Dict[int, int] = {}
    archetype_by_uid: Dict[int, str] = {}
    artifact_role_by_uid: Dict[int, str] = {}
    scaling_stat_by_uid: Dict[int, str] = {}
    unit_base_stats_by_uid: Dict[int, Tuple[int, int, int, int]] = {}
    overcap_penalty_expr_by_uid: Dict[int, cp_model.LinearExpr] = {}
    baseline_guard_shortfall_by_uid: Dict[int, cp_model.IntVar] = {}
    rune_set_hint_terms: List[cp_model.LinearExpr] = []

    # Keep deterministic build order
    builds_by_uid: Dict[int, List[Build]] = {}
    for uid in unit_ids:
        builds_by_uid[uid] = _builds_for_unit_with_cloud_prior(presets, req, int(uid))

    # per-unit constraints
    for uid in unit_ids:
        unit = account.units_by_id.get(uid)
        base_hp = int((unit.base_con or 0) * 15) if unit else 0
        base_atk = int(unit.base_atk or 0) if unit else 0
        base_def = int(unit.base_def or 0) if unit else 0
        base_spd = int(unit.base_spd or 0) if unit else 0
        unit_base_stats_by_uid[int(uid)] = (
            int(base_hp or 0),
            int(base_atk or 0),
            int(base_def or 0),
            int(base_spd or 0),
        )
        totem_spd_bonus_flat = int(base_spd * int(account.sky_tribe_totem_spd_pct or 0) / 100)
        leader_spd_bonus_flat = int((req.unit_spd_leader_bonus_flat or {}).get(int(uid), 0) or 0)
        base_spd_bonus_flat = int(totem_spd_bonus_flat + leader_spd_bonus_flat)
        base_cr = int(unit.crit_rate or 15) if unit else 15
        base_cd = int(unit.crit_dmg or 50) if unit else 50
        base_res = int(unit.base_res or 15) if unit else 15
        base_acc = int(unit.base_acc or 0) if unit else 0
        unit_arch = str((req.unit_archetype_by_uid or {}).get(int(uid), "") or "")
        archetype_by_uid[int(uid)] = str(unit_arch)
        role_for_art = _arena_role_from_archetype(unit_arch)
        if role_for_art == "unknown":
            role_for_art = (
                "attack"
                if _is_attack_type_unit(base_hp, base_atk, base_def, archetype=unit_arch)
                else "support"
            )
        artifact_role_by_uid[int(uid)] = str(role_for_art)
        scaling_stat_by_uid[int(uid)] = str(
            _scaling_stat_from_hints(
                dict((req.unit_artifact_hints_by_uid or {}).get(int(uid), {}) or {})
            )
            or ""
        )
        fixed_runes_by_slot = {
            int(slot): int(rid)
            for slot, rid in ((req.unit_fixed_runes_by_slot or {}).get(int(uid), {}) or {}).items()
            if 1 <= int(slot or 0) <= 6 and int(rid or 0) > 0
        }
        fixed_artifacts_by_type = {
            int(art_type): int(aid)
            for art_type, aid in ((req.unit_fixed_artifacts_by_type or {}).get(int(uid), {}) or {}).items()
            if int(art_type or 0) in (1, 2) and int(aid or 0) > 0
        }

        # rune pick: exactly one per slot
        rune_candidates_by_slot: Dict[int, List[Rune]] = {}
        for slot in range(1, 7):
            cands = list(runes_by_slot_global.get(slot, []))
            locked_rune_id = int(fixed_runes_by_slot.get(int(slot), 0) or 0)
            if locked_rune_id > 0:
                cands = [r for r in cands if int(r.rune_id or 0) == int(locked_rune_id)]
            rune_candidates_by_slot[slot] = cands
            if not cands:
                fallback = _run_greedy_pass(
                    account=account,
                    presets=presets,
                    req=req,
                    unit_ids=unit_ids,
                    time_limit_per_unit_s=float(req.time_limit_per_unit_s),
                    speed_slack_for_quality=0,
                    rune_top_per_set_override=0,
                )
                return GreedyResult(False, "Global fallback: slot has no candidates.", fallback)
            vars_for_slot: List[cp_model.IntVar] = []
            for r in cands:
                v = model.NewBoolVar(f"x_u{uid}_s{slot}_r{int(r.rune_id)}")
                x[(uid, slot, int(r.rune_id))] = v
                vars_for_slot.append(v)
            model.Add(sum(vars_for_slot) == 1)

        # artifact pick: exactly one per type
        for art_type in (1, 2):
            cands = list(artifacts_by_type_global[art_type])
            locked_artifact_id = int(fixed_artifacts_by_type.get(int(art_type), 0) or 0)
            if locked_artifact_id > 0:
                cands = [a for a in cands if int(a.artifact_id or 0) == int(locked_artifact_id)]
            compatible_cands = [
                a
                for a in cands
                if _artifact_compatible_with_unit(
                    a,
                    unit_attribute=int(unit.attribute or 0) if unit else 0,
                    unit_archetype=str(unit_arch),
                    base_hp=int(base_hp or 0),
                    base_atk=int(base_atk or 0),
                    base_def=int(base_def or 0),
                    account=account,
                )
            ]
            compatible_ids = {int(a.artifact_id or 0) for a in compatible_cands}
            if not compatible_cands:
                fallback = _run_greedy_pass(
                    account=account,
                    presets=presets,
                    req=req,
                    unit_ids=unit_ids,
                    time_limit_per_unit_s=float(req.time_limit_per_unit_s),
                    speed_slack_for_quality=0,
                    rune_top_per_set_override=0,
                )
                return GreedyResult(False, "Global fallback: artifact pool incomplete.", fallback)
            vars_for_type: List[cp_model.IntVar] = []
            for a in cands:
                av = model.NewBoolVar(f"xa_u{uid}_t{art_type}_a{int(a.artifact_id)}")
                xa[(uid, art_type, int(a.artifact_id))] = av
                vars_for_type.append(av)
                if int(a.artifact_id or 0) not in compatible_ids:
                    model.Add(av == 0)
            model.Add(sum(vars_for_type) == 1)

        # This unit's variables keyed like the per-unit solver: (slot, rune_id) / (type, artifact_id).
        xs = {(slot, int(r.rune_id)): x[(uid, slot, int(r.rune_id))] for slot in range(1, 7) for r in rune_candidates_by_slot[slot]}
        art_candidates_by_type = {
            t: [a for a in artifacts_by_type_global[t] if (uid, t, int(a.artifact_id)) in xa] for t in (1, 2)
        }
        xas = {(t, int(a.artifact_id)): xa[(uid, t, int(a.artifact_id))] for t in (1, 2) for a in art_candidates_by_type[t]}

        # build select
        builds = builds_by_uid[uid]
        # Global mode: treat a unit as Swift-opener if at least one viable build
        # qualifies for Swift speed priority. This avoids losing opener-priority
        # just because other alternative builds have extra constraints.
        if any(_force_swift_speed_priority(req, uid, [b]) for b in builds):
            force_speed_uids.add(int(uid))
        use_vars: List[cp_model.IntVar] = []
        for b_idx, _b in enumerate(builds):
            bv = model.NewBoolVar(f"use_build_u{uid}_b{b_idx}")
            use_build[(uid, b_idx)] = bv
            use_vars.append(bv)
        model.Add(sum(use_vars) == 1)

        set_choice_vars = _set_choice_vars(rune_candidates_by_slot, xs)
        apply_rune_set_fallback = not any(bool(getattr(bb, "set_options", []) or []) for bb in (builds or []))
        if apply_rune_set_fallback:
            fallback_ids = _preferred_rune_set_ids_for_monster(
                int(unit.unit_master_id or 0) if unit else 0,
                role=str(unit_arch),
            )
            rune_set_hint_terms.extend(_rune_set_hint_terms(model, uid, fallback_ids, set_choice_vars, "g_hint_set_full"))

        sm = _add_unit_speed_model(model, uid, rune_candidates_by_slot, xs, base_spd, base_spd_bonus_flat)
        swift_active_by_uid[int(uid)] = sm.swift_active
        final_spd_raw = sm.final_raw
        final_spd = sm.final
        final_speed_expr[uid] = final_spd
        speed_tie_raw = (req.unit_speed_tiebreak_weight or {}).get(int(uid), None)
        speed_tiebreak_weight_by_uid[int(uid)] = 1 if speed_tie_raw is None else int(speed_tie_raw)

        # Request-level final combat speed bounds (used by Arena Rush coordination
        # between defense and offense contexts, e.g. shared-unit tick guarantees).
        req_min_final = int((dict(req.unit_min_final_speed or {})).get(int(uid), 0) or 0)
        req_max_final = int((dict(req.unit_max_final_speed or {})).get(int(uid), 0) or 0)
        if req_min_final > 0:
            model.Add(final_spd >= int(req_min_final))
        if req_max_final > 0:
            model.Add(final_spd <= int(req_max_final))

        # Safety floor (global mode):
        # - min SPD is raw SPD (without tower/leader)
        # - tick floor is combat SPD (with tower/leader)
        unit_min_spd_floor_raw = 0
        unit_min_spd_floor_no_base = 0
        unit_min_tick_floor = 0
        for bb in builds:
            cfg_min = int((getattr(bb, "min_stats", {}) or {}).get("SPD", 0) or 0)
            cfg_min_no_base = int((getattr(bb, "min_stats", {}) or {}).get("SPD_NO_BASE", 0) or 0)
            tick_min = int(min_spd_for_tick(int(getattr(bb, "spd_tick", 0) or 0), req.mode) or 0)
            unit_min_spd_floor_raw = max(unit_min_spd_floor_raw, cfg_min)
            unit_min_spd_floor_no_base = max(unit_min_spd_floor_no_base, cfg_min_no_base)
            unit_min_tick_floor = max(unit_min_tick_floor, tick_min)
        if unit_min_spd_floor_raw > 0:
            model.Add(final_spd_raw >= int(unit_min_spd_floor_raw))
        if unit_min_spd_floor_no_base > 0:
            model.Add(final_spd_raw - int(base_spd or 0) >= int(unit_min_spd_floor_no_base))
        if unit_min_tick_floor > 0:
            model.Add(final_spd >= int(unit_min_tick_floor))

        overcap_penalty_expr_by_uid[int(uid)] = _add_overcap_penalty(model, uid, base_cr, base_res, base_acc, sm)

        baseline_guard_weight = int(
            getattr(req, "baseline_regression_guard_weight", BASELINE_REGRESSION_GUARD_WEIGHT) or 0
        )
        if baseline_guard_weight > 0:
            baseline_slots = {
                int(slot): int(rid)
                for slot, rid in (((req.unit_baseline_runes_by_slot or {}).get(int(uid), {}) or {}).items())
                if 1 <= int(slot or 0) <= 6 and int(rid or 0) > 0
            }
            baseline_arts = {
                int(t): int(aid)
                for t, aid in (((req.unit_baseline_artifacts_by_type or {}).get(int(uid), {}) or {}).items())
                if int(t or 0) in (1, 2) and int(aid or 0) > 0
            }
            if len(baseline_slots) == 6 and len(baseline_arts) == 2:
                guard_role = str(archetype_by_uid.get(int(uid), "") or "").strip().lower()
                if guard_role in ("rueckhalt", "rückhalt"):
                    guard_role = "support"
                if guard_role == "":
                    guard_role = "attack" if _is_attack_type_unit(base_hp, base_atk, base_def, archetype="") else "support"
                if guard_role not in ("attack", "defense", "hp", "support"):
                    guard_role = "attack" if _is_attack_type_unit(base_hp, base_atk, base_def, archetype=guard_role) else "support"
                shortfall = _add_baseline_guard_shortfall(
                    model,
                    uid=uid,
                    runes_by_slot=rune_candidates_by_slot,
                    xs=xs,
                    artifacts_by_type=art_candidates_by_type,
                    xas=xas,
                    baseline_runes_by_slot=baseline_slots,
                    baseline_artifacts_by_type=baseline_arts,
                    role=guard_role,
                    base_hp=int(base_hp or 0),
                    base_atk=int(base_atk or 0),
                    base_def=int(base_def or 0),
                    base_spd=int(base_spd or 0),
                    base_cr=int(base_cr or 0),
                    base_res=int(base_res or 0),
                    base_acc=int(base_acc or 0),
                    rta_rune_ids_for_unit=None,
                    rta_artifact_ids_for_unit=None,
                    overcap_penalty_expr=overcap_penalty_expr_by_uid[int(uid)],
                    overcap_scale=int(GLOBAL_SOLVER_OVERCAP_PENALTY_SCALE),
                    shortfall_floor=300000,
                )
                if shortfall is not None:
                    baseline_guard_shortfall_by_uid[int(uid)] = shortfall

        # build-conditioned constraints
        excluded_set_ids = {int(sid) for sid in (req.broken_set_excluded_set_ids or set()) if int(sid or 0) > 0}
        for b_idx, b in enumerate(builds):
            vb = use_build[(uid, b_idx)]
            _add_build_constraints(
                model,
                uid=uid,
                b_idx=b_idx,
                build=b,
                vb=vb,
                runes_by_slot=rune_candidates_by_slot,
                xs=xs,
                artifacts_by_type=art_candidates_by_type,
                xas=xas,
                set_choice_vars=set_choice_vars,
                base_hp=int(base_hp or 0),
                base_atk=int(base_atk or 0),
                base_def=int(base_def or 0),
                base_cr=int(base_cr or 0),
                base_cd=int(base_cd or 0),
                base_res=int(base_res or 0),
                base_acc=int(base_acc or 0),
                excluded_set_ids=excluded_set_ids,
            )
            _add_build_speed_constraints(model, b, vb, req.mode, sm, base_spd)

    # Global uniqueness: each rune/artifact at most once
    rune_use_by_id: Dict[int, List[cp_model.IntVar]] = {}
    for (uid, slot, rid), vv in x.items():
        rune_use_by_id.setdefault(int(rid), []).append(vv)
    for rid, vars_for_rid in rune_use_by_id.items():
        model.Add(sum(vars_for_rid) <= 1)

    art_use_by_id: Dict[int, List[cp_model.IntVar]] = {}
    for (uid, _t, aid), vv in xa.items():
        art_use_by_id.setdefault(int(aid), []).append(vv)
    for aid, vars_for_aid in art_use_by_id.items():
        model.Add(sum(vars_for_aid) <= 1)

    # Global turn-order constraints
    if req.enforce_turn_order and req.unit_team_index and req.unit_team_turn_order:
        teams: Dict[int, List[int]] = {}
        for uid in unit_ids:
            t = req.unit_team_index.get(int(uid))
            trn = int(req.unit_team_turn_order.get(int(uid), 0) or 0)
            if t is None or trn <= 0:
                continue
            teams.setdefault(int(t), []).append(int(uid))
        for rows in teams.values():
            rows_sorted = sorted(rows, key=lambda u: int(req.unit_team_turn_order.get(int(u), 0) or 0))
            for i in range(1, len(rows_sorted)):
                prev_uid = int(rows_sorted[i - 1])
                cur_uid = int(rows_sorted[i])
                model.Add(final_speed_expr[prev_uid] >= final_speed_expr[cur_uid] + 1)

    # Objective: efficiency-first, speed as tie-break
    obj_terms: List[cp_model.LinearExpr] = []
    for (uid, slot, rid), vv in x.items():
        r = next((rr for rr in runes_by_slot_global[slot] if int(rr.rune_id) == int(rid)), None)
        if r is None:
            continue
        base_hp, base_atk, base_def, _base_spd = unit_base_stats_by_uid.get(int(uid), (0, 0, 0, 0))
        scaling_stat = str(scaling_stat_by_uid.get(int(uid), "") or "")
        scaling_bonus = int(
            _rune_scaling_score_proxy(
                r,
                scaling_stat=scaling_stat,
                base_hp=int(base_hp or 0),
                base_atk=int(base_atk or 0),
                base_def=int(base_def or 0),
            )
        )
        eff_score = int(round(float(rune_efficiency(r)) * 100.0))
        qual_score = int(_rune_quality_score(r, uid, None))
        obj_terms.append((eff_score * 100 + qual_score + (int(RUNE_SCALING_BONUS_WEIGHT) * scaling_bonus)) * vv)
    for (uid, t, aid), vv in xa.items():
        a = next((aa for aa in artifacts_by_type_global[t] if int(aa.artifact_id) == int(aid)), None)
        if a is None:
            continue
        base_hp, base_atk, base_def, base_spd = unit_base_stats_by_uid.get(int(uid), (0, 0, 0, 0))
        role_for_art = str(artifact_role_by_uid.get(int(uid), "unknown") or "unknown")
        scaling_stat = str(scaling_stat_by_uid.get(int(uid), "") or "")
        unit_hint = dict((req.unit_artifact_hints_by_uid or {}).get(int(uid), {}) or {})
        hint_score = int(_artifact_hint_score(a, unit_hint))
        scaling_score = int(_artifact_scaling_score_proxy(a, scaling_stat=scaling_stat))
        eff_score = int(round(float(artifact_efficiency(a)) * 100.0))
        qual_score = int(_artifact_quality_score(a, uid, None))
        context_score = int(
            _artifact_context_score_proxy(
                a,
                role=role_for_art,
                base_hp=int(base_hp or 0),
                base_atk=int(base_atk or 0),
                base_def=int(base_def or 0),
                base_spd=int(base_spd or 0),
            )
        )
        obj_terms.append(
            (
                eff_score * 80
                + qual_score
                + (int(ARTIFACT_ROLE_CONTEXT_WEIGHT) * context_score)
                + hint_score
                + (int(ARTIFACT_SCALING_BONUS_WEIGHT) * scaling_score)
            ) * vv
        )
    # Unit-level critical hint satisfaction (balanced/quality guidance):
    # if the candidate pool contains key hint effects, reward selecting at least one.
    for uid in unit_ids:
        unit_hint = dict((req.unit_artifact_hints_by_uid or {}).get(int(uid), {}) or {})
        critical_eids = _artifact_hint_critical_effect_ids(unit_hint)
        if not critical_eids:
            continue
        for rank, eff_id in enumerate(critical_eids[:4]):
            target_hits = [2, 1, 1, 1][min(rank, 3)]
            per_hit_bonus = [3200, 1400, 900, 600][min(rank, 3)]
            shortfall_penalty = [22000, 9000, 6000, 4000][min(rank, 3)]
            target_roll_sum = [4, 2, 2, 2][min(rank, 3)]
            per_roll_bonus = [1800, 1100, 700, 450][min(rank, 3)]
            roll_shortfall_penalty = [12000, 7000, 4500, 2800][min(rank, 3)]
            hit_vars: List[cp_model.IntVar] = []
            roll_terms: List[cp_model.LinearExpr] = []
            for t in (1, 2):
                for a in artifacts_by_type_global[t]:
                    if int(_artifact_effect_value_scaled(a, int(eff_id))) <= 0:
                        continue
                    key = (int(uid), int(t), int(a.artifact_id))
                    vv = xa.get(key)
                    if vv is not None:
                        hit_vars.append(vv)
                        rolls = int(_artifact_effect_roll_count(a, int(eff_id)))
                        if rolls > 0:
                            roll_terms.append(int(rolls) * vv)
            if not hit_vars:
                continue
            hit_count = model.NewIntVar(0, 2, f"g_hint_cnt_u{int(uid)}_e{int(eff_id)}_r{int(rank)}")
            model.Add(hit_count == sum(hit_vars))
            obj_terms.append(int(per_hit_bonus) * hit_count)
            if int(target_hits) > 0 and int(shortfall_penalty) > 0:
                shortfall = model.NewIntVar(0, int(target_hits), f"g_hint_short_u{int(uid)}_e{int(eff_id)}_r{int(rank)}")
                model.Add(shortfall >= int(target_hits) - hit_count)
                obj_terms.append((-int(shortfall_penalty)) * shortfall)
            if roll_terms:
                roll_sum = model.NewIntVar(0, 20, f"g_hint_roll_u{int(uid)}_e{int(eff_id)}_r{int(rank)}")
                model.Add(roll_sum == sum(roll_terms))
                obj_terms.append(int(per_roll_bonus) * roll_sum)
                if int(target_roll_sum) > 0 and int(roll_shortfall_penalty) > 0:
                    roll_shortfall = model.NewIntVar(0, int(target_roll_sum), f"g_hint_roll_short_u{int(uid)}_e{int(eff_id)}_r{int(rank)}")
                    model.Add(roll_shortfall >= int(target_roll_sum) - roll_sum)
                    obj_terms.append((-int(roll_shortfall_penalty)) * roll_shortfall)
    for uid in unit_ids:
        tie_raw = speed_tiebreak_weight_by_uid.get(int(uid), None)
        tie_w = 1 if tie_raw is None else int(tie_raw)
        if tie_w != 0:
            obj_terms.append(int(tie_w) * final_speed_expr[uid])
        over_expr = overcap_penalty_expr_by_uid.get(int(uid), None)
        if over_expr is not None:
            obj_terms.append((-int(GLOBAL_SOLVER_OVERCAP_PENALTY_SCALE)) * over_expr)
        shortfall_var = baseline_guard_shortfall_by_uid.get(int(uid), None)
        if shortfall_var is not None:
            guard_w = int(
                getattr(req, "baseline_regression_guard_weight", GLOBAL_BASELINE_REGRESSION_GUARD_WEIGHT)
                or GLOBAL_BASELINE_REGRESSION_GUARD_WEIGHT
            )
            obj_terms.append((-int(guard_w)) * shortfall_var)

    objective_expr = sum(obj_terms)
    if rune_set_hint_terms:
        objective_expr = objective_expr + sum(rune_set_hint_terms)
    solver = cp_model.CpSolver()
    if req.register_solver:
        try:
            req.register_solver(solver)
        except Exception:
            pass
    # Global model: budget scales with unit count.
    solver.parameters.max_time_in_seconds = float(max(10.0, float(req.time_limit_per_unit_s) * float(max(1, len(unit_ids))) * 1.5))
    solver.parameters.num_search_workers = int(max(1, int(req.workers or 1)))
    status = cp_model.UNKNOWN

    # Special rule: for Swift openers without extra min-stat requirements,
    # prioritize Swift usage and speed first, then optimize global quality.
    if force_speed_uids:
        forced_uids_sorted = sorted(int(uid) for uid in force_speed_uids)
        forced_swift_count_expr = sum(swift_active_by_uid[int(uid)] for uid in forced_uids_sorted)
        forced_speed_vars: Dict[int, cp_model.IntVar] = {}
        for uid in forced_uids_sorted:
            spd_var = model.NewIntVar(0, 2000, f"forced_speed_u{uid}")
            model.Add(spd_var == final_speed_expr[int(uid)])
            forced_speed_vars[int(uid)] = spd_var
        forced_speed_expr = sum(forced_speed_vars[int(uid)] for uid in forced_uids_sorted)
        forced_min_speed = model.NewIntVar(0, 2000, "forced_min_speed")
        model.AddMinEquality(forced_min_speed, [forced_speed_vars[int(uid)] for uid in forced_uids_sorted])

        # Stage 1: use Swift on as many forced openers as possible.
        model.Maximize(forced_swift_count_expr)
        status = solver.Solve(model)
        if req.is_cancelled and req.is_cancelled():
            return GreedyResult(False, tr("opt.cancelled"), [])
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            best_swift_count = int(solver.Value(forced_swift_count_expr))
            model.Add(forced_swift_count_expr >= int(best_swift_count))

            # Stage 2: avoid one opener being too slow by maximizing the minimum speed.
            model.Maximize(forced_min_speed)
            status = solver.Solve(model)
            if req.is_cancelled and req.is_cancelled():
                return GreedyResult(False, tr("opt.cancelled"), [])
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                best_forced_min_speed = int(solver.Value(forced_min_speed))
                model.Add(forced_min_speed >= int(best_forced_min_speed))

                # Stage 3: then maximize total opener speed.
                model.Maximize(forced_speed_expr)
                status = solver.Solve(model)
                if req.is_cancelled and req.is_cancelled():
                    return GreedyResult(False, tr("opt.cancelled"), [])
                if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    best_forced_speed = int(solver.Value(forced_speed_expr))
                    model.Add(forced_speed_expr >= int(best_forced_speed))

    run_count = int(max(1, int(req.multi_pass_count or 1))) if bool(req.multi_pass_enabled) else 1
    best_obj: Optional[int] = None
    best_x_assign: Set[Tuple[int, int, int]] = set()
    best_xa_assign: Set[Tuple[int, int, int]] = set()
    best_build_by_uid: Dict[int, int] = {}
    best_speed_by_uid: Dict[int, int] = {}
    seen_solution_signatures: Set[Tuple[Tuple[Tuple[int, int, int], ...], Tuple[Tuple[int, int, int], ...]]] = set()
    unique_solution_count = 0

    for run_idx in range(int(run_count)):
        try:
            seed_offset = int(getattr(req, "global_seed_offset", 0) or 0)
            solver.parameters.random_seed = int(101 + int(seed_offset) + (run_idx * 977))
            solver.parameters.randomize_search = bool(run_idx > 0)
        except Exception:
            pass
        model.Maximize(objective_expr)
        status = solver.Solve(model)
        if req.is_cancelled and req.is_cancelled():
            return GreedyResult(False, tr("opt.cancelled"), [])
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            break

        cur_x_assign: Set[Tuple[int, int, int]] = set()
        cur_xa_assign: Set[Tuple[int, int, int]] = set()
        cur_build_by_uid: Dict[int, int] = {}
        cur_speed_by_uid: Dict[int, int] = {}
        selected_vars: List[cp_model.IntVar] = []

        for key, vv in x.items():
            if int(solver.Value(vv)) == 1:
                cur_x_assign.add((int(key[0]), int(key[1]), int(key[2])))
                selected_vars.append(vv)
        for key, vv in xa.items():
            if int(solver.Value(vv)) == 1:
                cur_xa_assign.add((int(key[0]), int(key[1]), int(key[2])))
                selected_vars.append(vv)
        for uid in unit_ids:
            for b_idx, _b in enumerate(builds_by_uid[uid]):
                bv = use_build[(uid, b_idx)]
                if int(solver.Value(bv)) == 1:
                    cur_build_by_uid[int(uid)] = int(b_idx)
                    selected_vars.append(bv)
                    break
            cur_speed_by_uid[int(uid)] = int(solver.Value(final_speed_expr[int(uid)]))

        sig = (
            tuple(sorted(cur_x_assign)),
            tuple(sorted(cur_xa_assign)),
        )
        if sig not in seen_solution_signatures:
            seen_solution_signatures.add(sig)
            unique_solution_count += 1

        cur_obj = int(solver.Value(objective_expr))
        if best_obj is None or int(cur_obj) > int(best_obj):
            best_obj = int(cur_obj)
            best_x_assign = set(cur_x_assign)
            best_xa_assign = set(cur_xa_assign)
            best_build_by_uid = dict(cur_build_by_uid)
            best_speed_by_uid = dict(cur_speed_by_uid)

        if run_idx + 1 < int(run_count) and selected_vars:
            model.Add(sum(selected_vars) <= int(len(selected_vars) - 1))

    if best_obj is None:
        fallback = _run_greedy_pass(
            account=account,
            presets=presets,
            req=req,
            unit_ids=unit_ids,
            time_limit_per_unit_s=float(req.time_limit_per_unit_s),
            speed_slack_for_quality=0,
            rune_top_per_set_override=0,
        )
        ok_all = all(r.ok for r in fallback)
        msg = "Global infeasible/time limit; fallback heuristic used."
        return GreedyResult(ok_all, msg, fallback)

    # Extract
    results: List[GreedyUnitResult] = []
    for uid in unit_ids:
        chosen_runes: Dict[int, int] = {}
        for slot in range(1, 7):
            picked = 0
            for r in runes_by_slot_global[slot]:
                key = (uid, slot, int(r.rune_id))
                if key in best_x_assign:
                    picked = int(r.rune_id)
                    break
            if picked <= 0:
                results.append(GreedyUnitResult(uid, False, tr("opt.internal_no_rune", slot=slot), runes_by_slot={}))
                chosen_runes = {}
                break
            chosen_runes[slot] = picked
        if not chosen_runes:
            continue

        chosen_artifacts: Dict[int, int] = {}
        art_ok = True
        for t in (1, 2):
            picked_a = 0
            for a in artifacts_by_type_global[t]:
                akey = (uid, t, int(a.artifact_id))
                if akey in best_xa_assign:
                    picked_a = int(a.artifact_id)
                    break
            if picked_a <= 0:
                art_ok = False
                break
            chosen_artifacts[t] = picked_a

        chosen_build = builds_by_uid[uid][0]
        for b_idx, b in enumerate(builds_by_uid[uid]):
            if int(best_build_by_uid.get(int(uid), -1)) == int(b_idx):
                chosen_build = b
                break

        if not art_ok:
            results.append(GreedyUnitResult(uid, False, tr("opt.internal_no_artifact", art_type=1), runes_by_slot={}))
            continue

        # Post-check SPD guard (defensive; should already be guaranteed by constraints).
        floor_spd_raw = 0
        floor_spd_no_base = 0
        floor_tick_spd = 0
        for bb in builds_by_uid[uid]:
            cfg_min = int((getattr(bb, "min_stats", {}) or {}).get("SPD", 0) or 0)
            cfg_min_no_base = int((getattr(bb, "min_stats", {}) or {}).get("SPD_NO_BASE", 0) or 0)
            tick_min = int(min_spd_for_tick(int(getattr(bb, "spd_tick", 0) or 0), req.mode) or 0)
            floor_spd_raw = max(floor_spd_raw, cfg_min)
            floor_spd_no_base = max(floor_spd_no_base, cfg_min_no_base)
            floor_tick_spd = max(floor_tick_spd, tick_min)
        unit = account.units_by_id.get(int(uid))
        solved_spd = int(best_speed_by_uid.get(int(uid), 0))
        base_spd_u = int(unit.base_spd or 0) if unit else 0
        totem_spd_bonus_u = int(base_spd_u * int(account.sky_tribe_totem_spd_pct or 0) / 100)
        leader_spd_bonus_u = int((req.unit_spd_leader_bonus_flat or {}).get(int(uid), 0) or 0)
        solved_spd_raw = int(solved_spd - int(totem_spd_bonus_u) - int(leader_spd_bonus_u))
        solved_spd_no_base = solved_spd_raw - int(unit.base_spd or 0) if unit else solved_spd_raw
        if floor_spd_raw > 0 and solved_spd_raw < floor_spd_raw:
            results.append(
                GreedyUnitResult(
                    unit_id=uid,
                    ok=False,
                    message=f"Global raw SPD floor violated ({solved_spd_raw} < {floor_spd_raw})",
                    runes_by_slot={},
                )
            )
            continue
        if floor_spd_no_base > 0 and solved_spd_no_base < floor_spd_no_base:
            results.append(
                GreedyUnitResult(
                    unit_id=uid,
                    ok=False,
                    message=f"Global bonus SPD floor violated ({solved_spd_no_base} < {floor_spd_no_base})",
                    runes_by_slot={},
                )
            )
            continue
        if floor_tick_spd > 0 and solved_spd < floor_tick_spd:
            results.append(
                GreedyUnitResult(
                    unit_id=uid,
                    ok=False,
                    message=f"Global tick SPD floor violated ({solved_spd} < {floor_tick_spd})",
                    runes_by_slot={},
                )
            )
            continue
        results.append(
            GreedyUnitResult(
                unit_id=uid,
                ok=True,
                message="OK",
                chosen_build_id=str(chosen_build.id),
                chosen_build_name=str(chosen_build.name),
                runes_by_slot=chosen_runes,
                artifacts_by_type=chosen_artifacts,
                final_speed=solved_spd,
            )
        )

    ok_all = len(results) == len(unit_ids) and all(r.ok for r in results)
    msg_base = "Global optimization finished." if ok_all else "Global optimization partial."
    msg = f"{msg_base} runs={int(run_count)}, unique={int(max(1, unique_solution_count))}."
    return GreedyResult(ok_all, msg, results)
