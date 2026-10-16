from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from PySide6.QtWidgets import QDialog, QMessageBox

from desktop_app.domain.optimization_store import SavedOptimization, SavedUnitResult
from desktop_app.engine.off_optimizer import (
    OFF_OPTIMIZER_MAX_TEAM_SIZE,
    OFF_OPTIMIZER_MODE,
    OpeningTurnEffect,
    STRATEGY_BOOSTED_DAMAGE,
    STRATEGY_FIRST_TURN,
    STRATEGY_SECOND_TURN,
    OffOptimizerRequest,
    find_unbuildable_units,
    optimize_off_optimizer,
)
from desktop_app.i18n import tr
from desktop_app.ui.dialogs.build_dialog import BuildDialog
from desktop_app.ui.toast import show_toast
from desktop_app.ui.main_window_sections import optimizer_context as ctx


def _selection_path(window) -> Path:
    return Path(window.config_dir) / "off_optimizer_selection.json"


def _current_pool_mode(window) -> str:
    combo = getattr(window, "combo_off_optimizer_pool", None)
    if combo is None:
        return "siege"
    return str(combo.currentData() or "siege")


def _team_size(ids: List[int]) -> int:
    return max(3, len(ids))


def _turn_effects_with_defaults(window, ids: List[int]) -> Dict[int, Dict[str, object]]:
    """Saved per-unit opening effects; units never configured fall back to their skill data."""
    saved = dict(getattr(window, "off_optimizer_turn_effects", {}) or {})
    caps = ctx.effect_capabilities_by_unit(window, ids)
    out: Dict[int, Dict[str, object]] = {}
    for uid in ids:
        if int(uid) in saved:
            out[int(uid)] = dict(saved[int(uid)] or {})
            continue
        cap = dict(caps.get(int(uid), {}) or {})
        out[int(uid)] = {
            "applies_spd_buff": bool(cap.get("has_spd_buff", False)),
            "atb_boost_pct": float(cap.get("max_atb_boost_pct", 0) or 0) if cap.get("has_atb_boost") else 0.0,
            "include_caster": True,
        }
    return out


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
    if not ids:
        return False, tr("off.need_unit"), []
    if len(ids) >= OFF_OPTIMIZER_MAX_TEAM_SIZE:
        # 4-unit offenses only exist in Arena.
        window.combo_off_optimizer_pool.setCurrentIndex(window.combo_off_optimizer_pool.findData("arena"))
    pool = str(window.combo_off_optimizer_pool.currentText() or "")
    return True, tr("off.valid", n=len(ids), size=_team_size(ids), pool=pool), ids


def _leader_bonus(window, ids: List[int]) -> Dict[int, int]:
    return ctx.speed_leader_bonus_map(
        window,
        ids,
        leader_uid=int(getattr(window, "off_optimizer_speed_lead_uid", 0) or 0),
        lead_pct_override=int(getattr(window, "off_optimizer_speed_lead_pct", 0) or 0),
    )


def _short_name(window, uid: int) -> str:
    unit = window.account.units_by_id.get(int(uid)) if window.account else None
    return window.monster_db.name_for(int(unit.unit_master_id)) if unit is not None else str(uid)


def _result_summary(window, ids: List[int], results, tune, strategy: str) -> Tuple[str, bool]:
    """One short status line plus whether the run reached its goal."""
    ok_ids = {int(r.unit_id) for r in results if r.ok}
    parts = [tr("off.built", ok=len(ok_ids), total=len(ids))]
    missing = [uid for uid in ids if int(uid) not in ok_ids]
    if missing:
        parts.append(tr("off.not_built", names=", ".join(_short_name(window, uid) for uid in missing)))
        return " · ".join(parts), False
    if tune is None:
        return parts[0], True
    strategy_key = str(strategy or "").strip().lower()
    if strategy_key == STRATEGY_SECOND_TURN:
        parts.append(tr("off.second_turn_ok" if tune.ok else "off.second_turn_fail"))
        return " · ".join(parts), bool(tune.ok)
    if tune.ok:
        parts.append(tr("off.turn_ok"))
        return " · ".join(parts), True
    name = _short_name(window, int(tune.first_cut_by_uid)) if int(tune.first_cut_by_uid or 0) > 0 else "?"
    if strategy_key == STRATEGY_BOOSTED_DAMAGE:
        parts.append(tr("off.mirror_cut_accepted", name=name))
        return " · ".join(parts), True
    parts.append(tr("off.mirror_cut", name=name))
    return " · ".join(parts), False


def _turn_order_text(window, tune, unit_count: int) -> str:
    labels = []
    for label in list(getattr(tune, "observed_order", []) or [])[: max(6, unit_count * 2)]:
        side, uid_s = str(label).split(":", 1)
        side_txt = tr("off.side_off") if side == "off" else tr("off.side_mirror")
        labels.append(f"{side_txt} {_short_name(window, int(uid_s))}")
    return tr("off.turn_order", order=" → ".join(labels)) if labels else ""


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
    ok, msg, ids = _validate(window)
    window.lbl_off_optimizer_validate.setText(msg)
    if not ok:
        QMessageBox.critical(window, tr("off.title"), msg)
        return
    save_state(window)
    if window.account:
        # Catch builds that can never be met (min stats, ticks) before a long optimization.
        problems = window._run_with_busy_progress(
            msg,
            lambda is_cancelled, _register_solver, _progress_cb: find_unbuildable_units(
                window.account, window.presets, ids, _leader_bonus(window, ids), is_cancelled
            ),
        ) or {}
        if problems:
            lines = "\n".join(f"• {_short_name(window, uid)}: {reason}" for uid, reason in problems.items())
            QMessageBox.warning(window, tr("off.title"), tr("off.infeasible_units", lines=lines))
            return
    show_toast(window, msg, "success")


def on_edit_presets(window) -> None:
    if not window.account:
        return
    ok, msg, ids = _validate(window)
    if not ok:
        QMessageBox.critical(window, tr("off.title"), tr("dlg.validate_first", msg=msg))
        return
    unit_rows = [(uid, window._unit_text(uid)) for uid in ids]
    speed_lead_pct_by_uid = _speed_lead_pct_by_uid(window, ids)
    effect_caps = ctx.effect_capabilities_by_unit(window, ids)
    order_turn_effects = [_turn_effects_with_defaults(window, ids)]
    team_size = _team_size(ids)
    dlg = BuildDialog(
        window,
        tr("off.builds_title"),
        unit_rows,
        window.presets,
        OFF_OPTIMIZER_MODE,
        window.account,
        window._unit_icon_for_unit_id,
        team_size=team_size,
        order_teams=[unit_rows],
        order_team_titles=[tr("off.title")],
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
        QMessageBox.critical(window, tr("off.title"), tr("dlg.validate_first", msg=msg))
        return
    save_state(window)
    quality_profile = str(window.combo_quality_profile_off_optimizer.currentData() or "gpu_combo")
    workers = window._effective_workers(quality_profile, window.combo_workers_off_optimizer)
    strategy = str(window.combo_off_optimizer_strategy.currentData() or STRATEGY_FIRST_TURN)
    order = _opening_order_from_presets(window, ids)
    raw_effects = _turn_effects_with_defaults(window, ids)
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
    leader_bonus = _leader_bonus(window, ids)
    unit_archetype_by_uid = ctx.optimizer_archetype_by_uid(window, ids)
    unit_artifact_hints_by_uid = ctx.optimizer_artifact_hints_by_uid(window, ids)
    running_text = tr("result.opt_running", mode=tr("off.title"))
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
    opt = getattr(res, "optimization", None)
    results = list(getattr(opt, "results", None) or [])
    tune = getattr(res, "mirror_tune", None)
    summary, reached = _result_summary(window, ids, results, tune, strategy)
    lines = [summary]
    lines += [f"• {_short_name(window, int(r.unit_id))}: {r.message}" for r in results if not r.ok]
    order_text = _turn_order_text(window, tune, len(ids))
    if order_text:
        lines.append(order_text)
    if opt is not None and str(getattr(opt, "message", "") or ""):
        lines.append(tr("off.details", details=str(opt.message)))
    full_msg = "\n".join(lines)
    # Short line in the status bar; reasons, turn order and solver stats in the tooltip/dialog.
    window.lbl_off_optimizer_validate.setText(summary)
    window.lbl_off_optimizer_validate.setToolTip(full_msg)
    show_toast(window, summary, "success" if reached else "warning")
    preview = SavedOptimization(
        id="",
        name="",
        mode=OFF_OPTIMIZER_MODE,
        teams=[ids],
        results=[
            SavedUnitResult(
                unit_id=int(r.unit_id),
                runes_by_slot=dict(r.runes_by_slot),
                artifacts_by_type=dict(r.artifacts_by_type or {}),
                final_speed=int(r.final_speed or 0),
            )
            for r in results
            if r.ok and r.runes_by_slot
        ],
    )
    window.off_optimizer_result_cards.render_saved_optimization(
        preview,
        window.account,
        window.monster_db,
        window.assets_dir,
        rune_mode="arena" if _current_pool_mode(window) == "arena" else "siege",
    )
    if results:
        window._show_optimize_results(
            tr("off.title"),
            full_msg,
            results,
            unit_team_index={int(uid): 0 for uid in ids},
            unit_display_order={int(uid): idx for idx, uid in enumerate(ids)},
            mode=OFF_OPTIMIZER_MODE,
            teams=[ids],
            team_header_by_index={0: tr("off.title")},
            group_size=_team_size(ids),
        )
