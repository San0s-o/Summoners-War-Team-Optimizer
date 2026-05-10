from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import Dict, List

from desktop_app.domain.models import AccountData
from desktop_app.domain.presets import Build, BuildStore
from desktop_app.engine.arena_rush_timing import (
    OpeningTurnEffect,
    effective_spd_buff_pct_for_unit,
    spd_buff_increase_pct_by_unit_from_assignments,
)
from desktop_app.engine.greedy_optimizer import GreedyRequest, GreedyResult, GreedyUnitResult, optimize_greedy


OFF_OPTIMIZER_MODE = "off_optimizer"
STRATEGY_FIRST_TURN = "first_turn"
STRATEGY_BOOSTED_DAMAGE = "boosted_damage"
STRATEGY_SECOND_TURN = "second_turn"


@dataclass
class OffOptimizerRequest:
    unit_ids: List[int]
    pool_mode: str = "siege"
    strategy: str = STRATEGY_FIRST_TURN
    expected_opening_order: List[int] = field(default_factory=list)
    unit_turn_order: Dict[int, int] = field(default_factory=dict)
    unit_spd_leader_bonus_flat: Dict[int, int] = field(default_factory=dict)
    turn_effects_by_unit: Dict[int, OpeningTurnEffect] = field(default_factory=dict)
    unit_archetype_by_uid: Dict[int, str] = field(default_factory=dict)
    unit_artifact_hints_by_uid: Dict[int, Dict[str, object]] = field(default_factory=dict)
    workers: int = 8
    time_limit_per_unit_s: float = 5.0
    pass_count: int = 3
    quality_profile: str = "gpu_combo"
    rune_top_per_set: int = 0
    broken_set_excluded_set_ids: set[int] = field(default_factory=set)
    is_cancelled: object | None = None
    register_solver: object | None = None
    progress_callback: object | None = None


@dataclass
class MirrorTuneResult:
    ok: bool
    message: str
    observed_order: List[str] = field(default_factory=list)
    offense_first_round: List[int] = field(default_factory=list)
    first_cut_by_uid: int = 0
    recommended_min_speed_by_uid: Dict[int, int] = field(default_factory=dict)


@dataclass
class OffOptimizerResult:
    ok: bool
    message: str
    optimization: GreedyResult
    mirror_tune: MirrorTuneResult
    strategy: str = STRATEGY_FIRST_TURN


def _unique_unit_ids(unit_ids: List[int]) -> List[int]:
    out: List[int] = []
    seen: set[int] = set()
    for uid in unit_ids or []:
        ui = int(uid or 0)
        if ui <= 0 or ui in seen:
            continue
        seen.add(int(ui))
        out.append(int(ui))
        if len(out) >= 3:
            break
    return out


def _expected_order(presets: BuildStore, unit_ids: List[int]) -> List[int]:
    indexed: List[tuple[int, int, int]] = []
    for pos, uid in enumerate(unit_ids or []):
        builds = presets.get_unit_builds(OFF_OPTIMIZER_MODE, int(uid))
        b0 = builds[0] if builds else Build.default_any()
        turn = int(getattr(b0, "turn_order", 0) or 0)
        opt = int(getattr(b0, "optimize_order", 0) or 0)
        key = int(turn or opt or 0)
        indexed.append((key, int(pos), int(uid)))
    with_order = [row for row in indexed if int(row[0]) > 0]
    without_order = [row for row in indexed if int(row[0]) <= 0]
    with_order.sort(key=lambda row: (int(row[0]), int(row[1])))
    without_order.sort(key=lambda row: int(row[1]))
    return [int(uid) for _, _, uid in (with_order + without_order)]


def _result_by_uid(results: List[GreedyUnitResult]) -> Dict[int, GreedyUnitResult]:
    return {int(r.unit_id): r for r in (results or []) if int(getattr(r, "unit_id", 0) or 0) > 0}


def _side_label(side: str, uid: int) -> str:
    return f"{side}:{int(uid)}"


def _simulate_mirror_opening(
    expected_order: List[int],
    speed_by_uid: Dict[int, int],
    turn_effects_by_unit: Dict[int, OpeningTurnEffect],
    spd_buff_increase_pct_by_unit: Dict[int, float] | None = None,
    max_actions: int = 24,
    atb_gain_per_tick_pct: float = 7.0,
) -> List[str]:
    order = [int(uid) for uid in (expected_order or []) if int(uid) > 0 and int(speed_by_uid.get(int(uid), 0) or 0) > 0]
    units: List[tuple[str, int]] = [("off", uid) for uid in order] + [("def", uid) for uid in order]
    if not units:
        return []
    atb = {_side_label(side, uid): 0.0 for side, uid in units}
    spd_buff_active = {_side_label(side, uid): False for side, uid in units}
    acted_once = {_side_label(side, uid): False for side, uid in units}
    side_pos = {"off": 0, "def": 1}
    position = {_side_label(side, uid): (side_pos[side], idx) for idx, (side, uid) in enumerate(units)}
    buff_inc = {int(uid): float(v) for uid, v in dict(spd_buff_increase_pct_by_unit or {}).items()}
    gain_ratio = float(atb_gain_per_tick_pct) / 100.0
    out: List[str] = []

    def _gain(label: str, uid: int) -> float:
        speed = float(int(speed_by_uid.get(int(uid), 0) or 0))
        if speed <= 0.0:
            return 0.0
        mult = 1.0
        if bool(spd_buff_active.get(label, False)):
            mult += effective_spd_buff_pct_for_unit(buff_inc.get(int(uid), 0.0)) / 100.0
        return float(gain_ratio * speed * mult)

    for _ in range(max(24, int(max_actions) * 20)):
        if len(out) >= int(max_actions):
            break
        gains = {_side_label(side, uid): _gain(_side_label(side, uid), uid) for side, uid in units}
        ticks_needed: Dict[str, int] = {}
        for side, uid in units:
            label = _side_label(side, uid)
            if bool(acted_once.get(label, False)):
                ticks_needed[label] = 10**9
                continue
            gain = float(gains.get(label, 0.0))
            if gain <= 0.0:
                ticks_needed[label] = 10**9
                continue
            remain = max(0.0, 100.0 - float(atb.get(label, 0.0)))
            # The off optimizer mirrors the tick-bracket calculator view: after
            # one unit acts, other already-ready units are resolved on the next
            # tick, so opening buffs/boosts can change the visible first round.
            ticks_needed[label] = 1 if remain <= 0.0 else int(ceil(remain / gain))
        min_ticks = min(ticks_needed.values()) if ticks_needed else 10**9
        if min_ticks >= 10**9:
            break
        if min_ticks > 0:
            for label, gain in gains.items():
                atb[label] = float(atb.get(label, 0.0) + (gain * float(min_ticks)))
        ready = [
            label
            for label in atb
            if not bool(acted_once.get(label, False)) and float(atb.get(label, 0.0)) >= 100.0 - 1e-9
        ]
        if not ready:
            continue
        actor = max(
            ready,
            key=lambda label: (
                float(atb.get(label, 0.0)),
                float(gains.get(label, 0.0)),
                -int(position.get(label, (9, 999))[0]),
                -int(position.get(label, (9, 999))[1]),
            ),
        )
        out.append(str(actor))
        acted_once[actor] = True
        atb[actor] = max(0.0, float(atb.get(actor, 0.0)) - 100.0)
        side_s, uid_s = actor.split(":", 1)
        uid = int(uid_s)
        effect = dict(turn_effects_by_unit or {}).get(int(uid))
        if effect is None:
            continue
        side_labels = [_side_label(side_s, oid) for oid in order]
        boost = max(0.0, float(effect.atb_boost_pct or 0.0))
        if boost > 0.0:
            for label in side_labels:
                if label == actor and not bool(effect.include_caster):
                    continue
                atb[label] = float(atb.get(label, 0.0) + boost)
        if bool(effect.applies_spd_buff):
            for label in side_labels:
                if label == actor and not bool(effect.include_caster):
                    continue
                spd_buff_active[label] = True
    return out


def evaluate_mirror_tune(
    expected_order: List[int],
    results: List[GreedyUnitResult],
    turn_effects_by_unit: Dict[int, OpeningTurnEffect],
    artifact_lookup,
    strategy: str,
) -> MirrorTuneResult:
    order = [int(uid) for uid in (expected_order or []) if int(uid) > 0]
    by_uid = _result_by_uid(results)
    speed_by_uid = {int(uid): int(by_uid[int(uid)].final_speed or 0) for uid in order if int(uid) in by_uid}
    if len(order) < 1 or len(speed_by_uid) != len(order):
        return MirrorTuneResult(False, "Off-Optimizer: not all selected units have a valid result.")
    artifacts_by_unit = {
        int(uid): dict((by_uid[int(uid)].artifacts_by_type or {}))
        for uid in order
        if int(uid) in by_uid
    }
    buff_inc = spd_buff_increase_pct_by_unit_from_assignments(artifacts_by_unit, dict(artifact_lookup or {}))
    observed = _simulate_mirror_opening(
        expected_order=order,
        speed_by_uid=speed_by_uid,
        turn_effects_by_unit=dict(turn_effects_by_unit or {}),
        spd_buff_increase_pct_by_unit=buff_inc,
        max_actions=max(6, len(order) * 2),
    )
    off_round: List[int] = []
    first_cut = 0
    for label in observed:
        side, uid_s = str(label).split(":", 1)
        uid = int(uid_s)
        if side == "off":
            if uid not in off_round:
                off_round.append(int(uid))
            if len(off_round) >= len(order):
                break
        else:
            first_cut = int(uid)
            break

    strategy_key = str(strategy or STRATEGY_FIRST_TURN).strip().lower()
    if strategy_key == STRATEGY_SECOND_TURN:
        expected_labels = [_side_label("def", uid) for uid in order] + [_side_label("off", uid) for uid in order]
        ok = observed[: len(expected_labels)] == expected_labels
        return MirrorTuneResult(
            ok=bool(ok),
            message="Second Turn mirror order ok." if ok else "Second Turn mirror order was not reached cleanly.",
            observed_order=observed,
            offense_first_round=off_round,
            first_cut_by_uid=0 if ok else int(first_cut),
        )

    ok = off_round == order and int(first_cut) == 0
    rec: Dict[int, int] = {}
    if not ok:
        # Conservative repair hint: speed up the first missing/offending unit first.
        missing = [uid for uid in order if uid not in off_round]
        target = int(missing[0]) if missing else int(order[min(len(off_round), len(order) - 1)])
        cur = int(speed_by_uid.get(int(target), 0) or 0)
        if cur > 0:
            rec[int(target)] = int(cur + 3)
    return MirrorTuneResult(
        ok=bool(ok),
        message="Mirror tune ok." if ok else "Mirror tune failed: enemy mirror cut before all offense units moved.",
        observed_order=observed,
        offense_first_round=off_round,
        first_cut_by_uid=int(first_cut),
        recommended_min_speed_by_uid=rec,
    )


def _team_has_spd_buff_by_uid(order: List[int], effects: Dict[int, OpeningTurnEffect]) -> Dict[int, bool]:
    has_before = False
    out: Dict[int, bool] = {}
    for uid in order:
        out[int(uid)] = bool(has_before)
        effect = dict(effects or {}).get(int(uid))
        if effect is not None and bool(effect.applies_spd_buff):
            has_before = True
    return out


def optimize_off_optimizer(account: AccountData, presets: BuildStore, req: OffOptimizerRequest) -> OffOptimizerResult:
    unit_ids = _unique_unit_ids(req.unit_ids)
    if not unit_ids:
        empty = GreedyResult(False, "Off-Optimizer: no units selected.", [])
        return OffOptimizerResult(False, empty.message, empty, MirrorTuneResult(False, empty.message), req.strategy)
    order = [int(uid) for uid in (req.expected_opening_order or []) if int(uid) in set(unit_ids)]
    if not order:
        order = _expected_order(presets, unit_ids)
    turn_by_uid = dict(req.unit_turn_order or {})
    for idx, uid in enumerate(order):
        turn_by_uid.setdefault(int(uid), int(idx + 1))

    artifact_lookup = {int(a.artifact_id): a for a in account.artifacts}
    floors: Dict[int, int] = {}
    best_result: GreedyResult | None = None
    best_tune: MirrorTuneResult | None = None
    max_attempts = 1 if str(req.strategy).strip().lower() == STRATEGY_SECOND_TURN else 4
    for attempt in range(max_attempts):
        if req.is_cancelled and req.is_cancelled():
            break
        greedy_req = GreedyRequest(
            mode=OFF_OPTIMIZER_MODE,
            unit_ids_in_order=order,
            time_limit_per_unit_s=float(req.time_limit_per_unit_s),
            workers=int(req.workers or 1),
            multi_pass_enabled=bool(int(req.pass_count or 1) > 1),
            multi_pass_count=max(1, int(req.pass_count or 1)),
            multi_pass_strategy="greedy_refine",
            quality_profile=str(req.quality_profile or "gpu_combo"),
            rune_top_per_set=int(req.rune_top_per_set or 0),
            progress_callback=req.progress_callback,
            is_cancelled=req.is_cancelled,
            register_solver=req.register_solver,
            enforce_turn_order=True,
            unit_team_index={int(uid): 0 for uid in order},
            unit_team_turn_order=turn_by_uid,
            unit_spd_leader_bonus_flat=dict(req.unit_spd_leader_bonus_flat or {}),
            unit_min_final_speed=(dict(floors) or None),
            unit_archetype_by_uid=dict(req.unit_archetype_by_uid or {}),
            unit_artifact_hints_by_uid=dict(req.unit_artifact_hints_by_uid or {}),
            unit_team_has_spd_buff_by_uid=_team_has_spd_buff_by_uid(order, dict(req.turn_effects_by_unit or {})),
            broken_set_excluded_set_ids=set(req.broken_set_excluded_set_ids or set()),
            arena_rush_context="offense",
        )
        result = optimize_greedy(account, presets, greedy_req)
        tune = evaluate_mirror_tune(order, result.results, dict(req.turn_effects_by_unit or {}), artifact_lookup, req.strategy)
        best_result = result
        best_tune = tune
        if tune.ok or str(req.strategy).strip().lower() == STRATEGY_BOOSTED_DAMAGE:
            # Boosted Damage accepts the greedy damage result unless the mirror check
            # can be repaired by cheap speed floors in the first retry.
            if tune.ok or attempt >= 1:
                break
        rec = dict(tune.recommended_min_speed_by_uid or {})
        if not rec:
            break
        changed = False
        for uid, floor in rec.items():
            old = int(floors.get(int(uid), 0) or 0)
            if int(floor) > old:
                floors[int(uid)] = int(floor)
                changed = True
        if not changed:
            break
    final_result = best_result or GreedyResult(False, "Off-Optimizer: no result.", [])
    final_tune = best_tune or MirrorTuneResult(False, "Off-Optimizer: mirror tune not evaluated.")
    ok = bool(final_result.ok) and (bool(final_tune.ok) or str(req.strategy).strip().lower() == STRATEGY_BOOSTED_DAMAGE)
    msg = final_tune.message if final_result.ok else final_result.message
    return OffOptimizerResult(bool(ok), str(msg), final_result, final_tune, str(req.strategy or STRATEGY_FIRST_TURN))
