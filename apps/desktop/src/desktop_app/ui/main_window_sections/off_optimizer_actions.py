from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from PySide6.QtWidgets import QDialog, QMessageBox

from desktop_app.engine.arena_rush_timing import OpeningTurnEffect
from desktop_app.engine.off_optimizer import (
    OFF_OPTIMIZER_MODE,
    STRATEGY_FIRST_TURN,
    OffOptimizerRequest,
    off_optimizer_team_size_for_pool,
    optimize_off_optimizer,
)
from desktop_app.i18n import tr
from desktop_app.ui.dialogs.build_dialog import BuildDialog
from desktop_app.ui.main_window_sections.arena_rush_actions import (
    _arena_effect_capabilities_by_unit,
    _arena_speed_leader_bonus_map,
    optimizer_archetype_by_uid,
    optimizer_artifact_hints_by_uid,
)
from desktop_app.ui.toast import show_toast


def _selection_path(window) -> Path:
    return Path(window.config_dir) / "off_optimizer_selection.json"


def _current_pool_mode(window) -> str:
    combo = getattr(window, "combo_off_optimizer_pool", None)
    if combo is None:
        return "siege"
    return str(combo.currentData() or "siege")


def _current_team_size(window) -> int:
    return off_optimizer_team_size_for_pool(_current_pool_mode(window))


def collect_off_optimizer_unit_ids(window) -> List[int]:
    out: List[int] = []
    seen: set[int] = set()
    for cmb in list(getattr(window, "off_optimizer_combos", []) or []):
        uid = int(cmb.currentData() or 0)
        if uid <= 0 or uid in seen:
            continue
        seen.add(int(uid))
        out.append(int(uid))
    return out


def _validate(window) -> Tuple[bool, str, List[int]]:
    ids = collect_off_optimizer_unit_ids(window)
    max_units = _current_team_size(window)
    if not ids:
        return False, "Off-Optimierer: Bitte mindestens ein Monster auswählen.", []
    if len(ids) > max_units:
        return False, f"Off-Optimierer: Maximal {max_units} Monster auswählen.", []
    return True, f"Off-Optimierer: OK ({len(ids)} Monster).", ids


def _speed_lead_pct_by_uid(window, unit_ids: List[int]) -> Dict[int, int]:
    out: Dict[int, int] = {}
    if not window.account:
        return out
    for uid in [int(x) for x in (unit_ids or []) if int(x) > 0]:
        unit = window.account.units_by_id.get(int(uid))
        if unit is None:
            continue
        if _current_pool_mode(window) == "arena":
            pct = int(window.monster_db.rta_speed_lead_percent_for(int(unit.unit_master_id or 0)) or 0)
        else:
            pct = int(window.monster_db.speed_lead_percent_for(int(unit.unit_master_id or 0)) or 0)
        if pct > 0:
            out[int(uid)] = int(pct)
    return out


def save_state(window) -> None:
    try:
        payload = {
            "unit_ids": collect_off_optimizer_unit_ids(window),
            "pool_mode": str(window.combo_off_optimizer_pool.currentData() or "siege"),
            "strategy": str(window.combo_off_optimizer_strategy.currentData() or STRATEGY_FIRST_TURN),
            "speed_lead_uid": int(getattr(window, "off_optimizer_speed_lead_uid", 0) or 0),
            "speed_lead_pct": int(getattr(window, "off_optimizer_speed_lead_pct", 0) or 0),
            "turn_effects": {
                str(uid): dict(cfg or {})
                for uid, cfg in dict(getattr(window, "off_optimizer_turn_effects", {}) or {}).items()
            },
        }
        path = _selection_path(window)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def restore_state(window) -> None:
    try:
        path = _selection_path(window)
        if not path.exists():
            return
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        ids = [int(uid) for uid in list(raw.get("unit_ids") or [])[:4] if int(uid or 0) > 0]
        for idx, cmb in enumerate(list(getattr(window, "off_optimizer_combos", []) or [])[:4]):
            uid = int(ids[idx]) if idx < len(ids) else 0
            pos = cmb.findData(uid)
            cmb.setCurrentIndex(pos if pos >= 0 else 0)
            if hasattr(cmb, "_sync_line_edit_to_current"):
                cmb._sync_line_edit_to_current()
        pool = str(raw.get("pool_mode") or "siege")
        pidx = window.combo_off_optimizer_pool.findData(pool)
        if pidx >= 0:
            window.combo_off_optimizer_pool.setCurrentIndex(pidx)
        strategy = str(raw.get("strategy") or STRATEGY_FIRST_TURN)
        sidx = window.combo_off_optimizer_strategy.findData(strategy)
        if sidx >= 0:
            window.combo_off_optimizer_strategy.setCurrentIndex(sidx)
        window.off_optimizer_speed_lead_uid = int(raw.get("speed_lead_uid", 0) or 0)
        window.off_optimizer_speed_lead_pct = int(raw.get("speed_lead_pct", 0) or 0)
        effects: Dict[int, Dict[str, object]] = {}
        for uid, cfg in dict(raw.get("turn_effects") or {}).items():
            ui = int(uid or 0)
            if ui > 0 and isinstance(cfg, dict):
                effects[int(ui)] = dict(cfg)
        window.off_optimizer_turn_effects = effects
    except Exception:
        return


def on_validate(window) -> None:
    ok, msg, _ids = _validate(window)
    window.lbl_off_optimizer_validate.setText(msg)
    if not ok:
        QMessageBox.critical(window, "Off-Optimierer", msg)
        return
    save_state(window)
    show_toast(window, msg, "success")


def on_edit_presets(window) -> None:
    if not window.account:
        return
    ok, msg, ids = _validate(window)
    if not ok:
        QMessageBox.critical(window, "Off-Optimierer", tr("dlg.validate_first", msg=msg))
        return
    unit_rows = [(uid, window._unit_text(uid)) for uid in ids]
    speed_lead_pct_by_uid = _speed_lead_pct_by_uid(window, ids)
    effect_caps = _arena_effect_capabilities_by_unit(window, ids)
    effects = dict(getattr(window, "off_optimizer_turn_effects", {}) or {})
    order_turn_effects = [{int(uid): dict(effects.get(int(uid), {}) or {}) for uid in ids}]
    team_size = _current_team_size(window)
    dlg = BuildDialog(
        window,
        "Off-Optimierer Builds",
        unit_rows,
        window.presets,
        OFF_OPTIMIZER_MODE,
        window.account,
        window._unit_icon_for_unit_id,
        team_size=team_size,
        order_teams=[unit_rows],
        order_team_titles=["Off-Optimierer"],
        order_turn_effects=order_turn_effects,
        show_turn_effect_controls=True,
        order_turn_effect_capabilities=effect_caps,
        show_speed_lead_controls=True,
        order_speed_leaders=[int(getattr(window, "off_optimizer_speed_lead_uid", 0) or 0)],
        order_speed_lead_pct_by_unit=speed_lead_pct_by_uid,
        order_speed_lead_pct_by_team=[int(getattr(window, "off_optimizer_speed_lead_pct", 0) or 0)],
        skill_icons_dir=str(window.assets_dir / "skills"),
        current_rune_mode="arena" if _current_pool_mode(window) == "arena" else "siege",
    )
    if dlg.exec() != QDialog.Accepted:
        return
    window.presets.save(window.presets_path)
    orders = dlg.team_order_by_lists()
    if orders:
        order = [int(uid) for uid in list(orders[0] or []) if int(uid) > 0]
        for slot, uid in enumerate(order[:team_size]):
            cmb = window.off_optimizer_combos[slot]
            pos = cmb.findData(int(uid))
            if pos >= 0:
                cmb.setCurrentIndex(pos)
                if hasattr(cmb, "_sync_line_edit_to_current"):
                    cmb._sync_line_edit_to_current()
    lead_uids = dlg.team_speed_lead_by_lists()
    lead_pcts = dlg.team_speed_lead_pct_by_lists()
    window.off_optimizer_speed_lead_uid = int(lead_uids[0]) if lead_uids else 0
    window.off_optimizer_speed_lead_pct = int(lead_pcts[0]) if lead_pcts else 0
    effect_lists = dlg.team_turn_effects_by_lists()
    window.off_optimizer_turn_effects = dict(effect_lists[0]) if effect_lists else {}
    save_state(window)
    show_toast(window, tr("dlg.builds_saved_title"), "success")


def _opening_order_from_presets(window, ids: List[int]) -> List[int]:
    indexed: List[Tuple[int, int, int]] = []
    for pos, uid in enumerate(ids):
        builds = window.presets.get_unit_builds(OFF_OPTIMIZER_MODE, int(uid))
        b0 = builds[0] if builds else None
        turn = int(getattr(b0, "turn_order", 0) or 0) if b0 is not None else 0
        opt = int(getattr(b0, "optimize_order", 0) or 0) if b0 is not None else 0
        indexed.append((int(turn or opt or 0), int(pos), int(uid)))
    with_order = [row for row in indexed if row[0] > 0]
    without_order = [row for row in indexed if row[0] <= 0]
    with_order.sort(key=lambda row: (row[0], row[1]))
    without_order.sort(key=lambda row: row[1])
    return [uid for _, _, uid in (with_order + without_order)]


def on_optimize(window) -> None:
    if not window.account:
        return
    ok, msg, ids = _validate(window)
    if not ok:
        QMessageBox.critical(window, "Off-Optimierer", tr("dlg.validate_first", msg=msg))
        return
    save_state(window)
    quality_profile = str(window.combo_quality_profile_off_optimizer.currentData() or "gpu_combo")
    workers = window._effective_workers(quality_profile, window.combo_workers_off_optimizer)
    strategy = str(window.combo_off_optimizer_strategy.currentData() or STRATEGY_FIRST_TURN)
    order = _opening_order_from_presets(window, ids)
    raw_effects = dict(getattr(window, "off_optimizer_turn_effects", {}) or {})
    turn_effects: Dict[int, OpeningTurnEffect] = {}
    for uid in ids:
        cfg = dict(raw_effects.get(int(uid), {}) or {})
        atb = float(cfg.get("atb_boost_pct", 0.0) or 0.0)
        spd = bool(cfg.get("applies_spd_buff", False))
        include_caster = bool(cfg.get("include_caster", True))
        if atb > 0.0 or spd:
            turn_effects[int(uid)] = OpeningTurnEffect(
                atb_boost_pct=float(atb),
                applies_spd_buff=bool(spd),
                include_caster=bool(include_caster),
            )
    leader_bonus = _arena_speed_leader_bonus_map(
        window,
        ids,
        leader_uid=int(getattr(window, "off_optimizer_speed_lead_uid", 0) or 0),
        lead_pct_override=int(getattr(window, "off_optimizer_speed_lead_pct", 0) or 0),
    )
    unit_archetype_by_uid = optimizer_archetype_by_uid(window, ids)
    unit_artifact_hints_by_uid = optimizer_artifact_hints_by_uid(window, ids)
    running_text = tr("result.opt_running", mode="Off-Optimierer")
    res = window._run_with_busy_progress(
        running_text,
        lambda is_cancelled, register_solver, progress_cb: optimize_off_optimizer(
            window.account,
            window.presets,
            OffOptimizerRequest(
                unit_ids=ids,
                pool_mode=str(window.combo_off_optimizer_pool.currentData() or "siege"),
                strategy=strategy,
                expected_opening_order=order,
                unit_turn_order={int(uid): idx + 1 for idx, uid in enumerate(order)},
                unit_spd_leader_bonus_flat=leader_bonus,
                turn_effects_by_unit=turn_effects,
                unit_archetype_by_uid=unit_archetype_by_uid,
                unit_artifact_hints_by_uid=unit_artifact_hints_by_uid,
                workers=workers,
                quality_profile=quality_profile,
                pass_count=3,
                is_cancelled=is_cancelled,
                register_solver=register_solver,
                progress_callback=progress_cb,
                broken_set_excluded_set_ids=set(window._broken_slot_excluded_set_ids() or set()),
            ),
        ),
    )
    final_msg = str(getattr(res, "message", "") or "")
    tune = getattr(res, "mirror_tune", None)
    if tune is not None:
        labels = []
        for label in list(getattr(tune, "observed_order", []) or [])[: max(6, len(ids) * 2)]:
            side, uid_s = str(label).split(":", 1)
            labels.append(("Off " if side == "off" else "Mirror ") + window._unit_text(int(uid_s)))
        if labels:
            final_msg = f"{final_msg}\nTurnorder: " + " -> ".join(labels)
    window.lbl_off_optimizer_validate.setText(final_msg.splitlines()[0] if final_msg else msg)
    show_toast(window, final_msg.splitlines()[0] if final_msg else msg, "success" if bool(getattr(res, "ok", False)) else "warning")
    opt = getattr(res, "optimization", None)
    if opt is not None and getattr(opt, "results", None):
        window._show_optimize_results(
            "Off-Optimierer",
            final_msg,
            opt.results,
            unit_team_index={int(uid): 0 for uid in ids},
            unit_display_order={int(uid): idx for idx, uid in enumerate(ids)},
            mode=OFF_OPTIMIZER_MODE,
            teams=[ids],
            team_header_by_index={0: "Off-Optimierer"},
            group_size=_current_team_size(window),
        )
