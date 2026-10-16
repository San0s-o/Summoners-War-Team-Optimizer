from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QListWidgetItem, QMessageBox

from desktop_app.domain.presets import Build
from desktop_app.engine.greedy_optimizer import (
    BASELINE_REGRESSION_GUARD_WEIGHT,
    GreedyRequest,
    optimize_greedy,
)
from desktop_app.i18n import tr
from desktop_app.ui.dialogs.build_dialog import BuildDialog
from desktop_app.ui.toast import show_toast
from desktop_app.ui.main_window_sections import optimizer_context as ctx


@dataclass
class TeamSelection:
    team_index: int
    unit_ids: List[int]


def turn_order_by_uid(window, mode: str, unit_ids: List[int]) -> Dict[int, int]:
    out: Dict[int, int] = {}
    for uid in unit_ids:
        builds = window.presets.get_unit_builds(mode, int(uid))
        b0 = builds[0] if builds else Build.default_any()
        out[int(uid)] = int(getattr(b0, "turn_order", 0) or 0)
    return out


def run_mode_optimization(
    window,
    *,
    mode: str,
    running_text: str,
    profile_combo,
    workers_combo,
    pass_spin,
    unit_ids_in_order: List[int],
    teams: List[List[int]],
    team_idx_by_uid: Dict[int, int],
    team_turn_by_uid: Dict[int, int],
    leader_spd_bonus_by_uid: Dict[int, int],
    status_label,
    result_title: str,
    result_kwargs: Dict[str, object],
    toast: bool = True,
    **extra_request: object,
) -> None:
    """Shared run of the team-based greedy modes: build the request, optimize, report, show results."""
    quality_profile = str(profile_combo.currentData() or "gpu_combo")
    pass_count = int(pass_spin.value())
    if quality_profile.strip().lower() in ("max_quality", "ultra_quality"):
        pass_count = 1
    workers = window._effective_workers(quality_profile, workers_combo)
    baseline_runes_by_unit, baseline_arts_by_unit = ctx.baseline_assignments_for_mode(window, mode, unit_ids_in_order)
    request = dict(
        mode=mode,
        unit_ids_in_order=unit_ids_in_order,
        time_limit_per_unit_s=5.0,
        workers=workers,
        multi_pass_enabled=bool(pass_count > 1),
        multi_pass_count=pass_count,
        multi_pass_strategy="greedy_refine",
        quality_profile=quality_profile,
        enforce_turn_order=True,
        unit_team_index=team_idx_by_uid,
        unit_team_turn_order=team_turn_by_uid,
        unit_spd_leader_bonus_flat=leader_spd_bonus_by_uid,
        unit_archetype_by_uid=ctx.optimizer_archetype_by_uid(window, unit_ids_in_order),
        unit_artifact_hints_by_uid=ctx.optimizer_artifact_hints_by_uid(window, unit_ids_in_order),
        unit_team_has_spd_buff_by_uid=ctx.team_has_spd_buff_by_uid(window, teams),
        unit_baseline_runes_by_slot=(baseline_runes_by_unit or None),
        unit_baseline_artifacts_by_type=(baseline_arts_by_unit or None),
        baseline_regression_guard_weight=(
            int(BASELINE_REGRESSION_GUARD_WEIGHT) if (baseline_runes_by_unit or baseline_arts_by_unit) else 0
        ),
        broken_set_excluded_set_ids=set(window._broken_slot_excluded_set_ids() or set()),
        **extra_request,
    )
    res = window._run_with_busy_progress(
        running_text,
        lambda is_cancelled, register_solver, progress_cb: optimize_greedy(
            window.account,
            window.presets,
            GreedyRequest(
                **request,
                progress_callback=progress_cb,
                is_cancelled=is_cancelled,
                register_solver=register_solver,
            ),
        ),
    )
    ok = bool(getattr(res, "ok", False))
    final_msg = ctx.user_facing_result_message(window, ok, str(getattr(res, "message", "")))
    status_label.setText(final_msg)
    window.statusBar().showMessage(final_msg, 7000)
    if toast:
        show_toast(window, final_msg, "success" if ok else "warning")
    if res is not None and getattr(res, "results", None):
        window._show_optimize_results(result_title, final_msg, res.results, mode=mode, teams=teams, **result_kwargs)


def on_take_current_siege(window) -> None:
    if not window.account:
        return
    teams = window.account.siege_def_teams()
    for t in range(min(len(teams), len(window.siege_team_combos))):
        team = teams[t]
        for s in range(min(3, len(team))):
            uid = team[s]
            cmb = window.siege_team_combos[t][s]
            idx = cmb.findData(uid)
            cmb.setCurrentIndex(idx if idx >= 0 else 0)
    selections = window._collect_siege_selections()
    _ok, msg, _all_units = window._validate_team_structure("Siege", selections, must_have_team_size=3)
    window.lbl_siege_validate.setText(msg)
    save_team_selections(window)


def collect_siege_selections(window) -> List[TeamSelection]:
    window._ensure_unit_dropdowns_populated()
    selections: List[TeamSelection] = []
    optimize_checks = getattr(window, "siege_optimize_checks", None) or []
    for t, row in enumerate(window.siege_team_combos):
        if optimize_checks and t < len(optimize_checks) and not optimize_checks[t].isChecked():
            continue
        ids = []
        for cmb in row:
            uid = int(cmb.currentData() or 0)
            if uid != 0:
                ids.append(uid)
        selections.append(TeamSelection(team_index=t, unit_ids=ids))
    return selections


def collect_siege_excluded_unit_ids(window) -> List[int]:
    """Return unit IDs from defenses that are NOT selected for optimization."""
    window._ensure_unit_dropdowns_populated()
    excluded: List[int] = []
    optimize_checks = getattr(window, "siege_optimize_checks", None) or []
    for t, row in enumerate(window.siege_team_combos):
        if not optimize_checks or t >= len(optimize_checks):
            continue
        if optimize_checks[t].isChecked():
            continue
        for cmb in row:
            uid = int(cmb.currentData() or 0)
            if uid != 0:
                excluded.append(uid)
    return excluded


def validate_team_structure(window, label: str, selections: List[TeamSelection], must_have_team_size: int) -> Tuple[bool, str, List[int]]:
    all_units: List[int] = []
    for sel in selections:
        if not sel.unit_ids:
            continue
        if len(sel.unit_ids) != must_have_team_size:
            return False, tr("val.incomplete_team", label=label, team=sel.team_index + 1, have=len(sel.unit_ids), need=must_have_team_size), []
        team_set: Set[int] = set()
        for uid in sel.unit_ids:
            if uid in team_set:
                name = window._unit_text(uid) if window.account else str(uid)
                return False, tr("val.duplicate_in_team", label=label, team=sel.team_index + 1, name=name), []
            team_set.add(uid)
        all_units.extend(sel.unit_ids)
    if not all_units:
        return False, tr("val.no_teams", label=label), []
    return True, tr("val.ok", label=label, count=len(all_units)), all_units


def on_validate_siege(window) -> None:
    if not window.account:
        return
    selections = window._collect_siege_selections()
    ok, msg, _all_units = window._validate_team_structure("Siege", selections, must_have_team_size=3)
    if not ok:
        window.lbl_siege_validate.setText(msg)
        QMessageBox.critical(window, tr("val.title_siege"), msg)
        return
    window.lbl_siege_validate.setText(msg)
    show_toast(window, msg, "success")


def on_edit_presets_siege(window) -> None:
    if not window.account:
        return
    selections = window._collect_siege_selections()
    ok, msg, all_units = window._validate_team_structure("Siege", selections, must_have_team_size=3)
    if not ok:
        QMessageBox.critical(window, "Siege", tr("dlg.validate_first", msg=msg))
        return
    unit_rows: List[Tuple[int, str]] = [(uid, window._unit_text(uid)) for uid in all_units]
    dlg = BuildDialog(
        window,
        "Siege Builds",
        unit_rows,
        window.presets,
        "siege",
        window.account,
        window._unit_icon_for_unit_id,
        team_size=3,
    )
    if dlg.exec() == QDialog.Accepted:
        ctx.store_compare_snapshot_from_build_dialog(window, "siege", dlg)
        window.presets.save(window.presets_path)
        save_team_selections(window)
        show_toast(window, tr("dlg.builds_saved_title"), "success")


def on_optimize_siege(window) -> None:
    if not window.account or window._siege_optimization_running:
        return
    window._siege_optimization_running = True
    window.btn_optimize_siege.setEnabled(False)
    try:
        selections = window._collect_siege_selections()
        ok, msg, all_units = window._validate_team_structure("Siege", selections, must_have_team_size=3)
        if not ok:
            QMessageBox.critical(window, "Siege", tr("dlg.validate_first", msg=msg))
            return
        teams = [sel.unit_ids for sel in selections if sel.unit_ids]
        team_idx_by_uid = {int(uid): int(idx) for idx, sel in enumerate(selections) for uid in sel.unit_ids}

        # Runes/artifacts of the defenses that are not being optimized stay where they are.
        excluded_rune_ids: Set[int] = set()
        excluded_artifact_ids: Set[int] = set()
        chk_block = getattr(window, "chk_siege_block_excluded", None)
        if chk_block and chk_block.isChecked():
            for uid in window._collect_siege_excluded_unit_ids():
                excluded_rune_ids.update(
                    int(rune.rune_id) for rune in window.account.equipped_runes_for(uid, mode="siege") if int(rune.rune_id or 0) > 0
                )
                excluded_artifact_ids.update(
                    int(art.artifact_id)
                    for art in window.account.artifacts
                    if int(art.occupied_id or 0) == int(uid) and int(art.artifact_id or 0) > 0
                )

        run_mode_optimization(
            window,
            mode="siege",
            running_text=tr("result.opt_running", mode="Siege"),
            profile_combo=window.combo_quality_profile_siege,
            workers_combo=window.combo_workers_siege,
            pass_spin=window.spin_multi_pass_siege,
            unit_ids_in_order=window._units_by_turn_order("siege", all_units),
            teams=teams,
            team_idx_by_uid=team_idx_by_uid,
            team_turn_by_uid=turn_order_by_uid(window, "siege", all_units),
            leader_spd_bonus_by_uid=window._leader_spd_bonus_map(teams),
            status_label=window.lbl_siege_validate,
            result_title=tr("result.title_siege"),
            result_kwargs=dict(
                unit_team_index=team_idx_by_uid,
                unit_display_order={int(uid): idx for idx, uid in enumerate(all_units)},
            ),
            excluded_rune_ids=(excluded_rune_ids or None),
            excluded_artifact_ids=(excluded_artifact_ids or None),
        )
    finally:
        window._siege_optimization_running = False
        window.btn_optimize_siege.setEnabled(bool(window.account))


def units_by_turn_order(window, mode: str, unit_ids: List[int]) -> List[int]:
    indexed: List[Tuple[int, int, int]] = []
    for pos, uid in enumerate(unit_ids):
        builds = window.presets.get_unit_builds(mode, int(uid))
        b0 = builds[0] if builds else Build.default_any()
        opt = int(getattr(b0, "optimize_order", 0) or 0)
        indexed.append((opt, pos, int(uid)))
    with_order = [x for x in indexed if x[0] > 0]
    without_order = [x for x in indexed if x[0] <= 0]
    with_order.sort(key=lambda t: (t[0], t[1]))
    without_order.sort(key=lambda t: t[1])
    return [uid for _, _, uid in (with_order + without_order)]


def units_by_turn_order_grouped(window, mode: str, unit_ids: List[int], group_size: int) -> List[int]:
    if group_size <= 0:
        return window._units_by_turn_order(mode, unit_ids)
    out: List[int] = []
    for i in range(0, len(unit_ids), group_size):
        group = unit_ids[i : i + group_size]
        out.extend(window._units_by_turn_order(mode, group))
    return out


def leader_spd_bonus_map(window, teams: List[List[int]]) -> Dict[int, int]:
    out: Dict[int, int] = {}
    if not window.account:
        return out
    for team in teams:
        ids = [int(uid) for uid in (team or []) if int(uid) != 0]
        if not ids:
            continue
        for uid in ids:
            out[int(uid)] = int(window._unit_leader_bonus(int(uid), ids).get("SPD", 0) or 0)
    return out


def collect_wgb_selections(window) -> List[TeamSelection]:
    window._ensure_unit_dropdowns_populated()
    selections: List[TeamSelection] = []
    for t, row in enumerate(window.wgb_team_combos):
        ids = []
        for cmb in row:
            uid = int(cmb.currentData() or 0)
            if uid != 0:
                ids.append(uid)
        selections.append(TeamSelection(team_index=t, unit_ids=ids))
    return selections


def validate_unique_monsters(window, all_unit_ids: List[int]) -> Tuple[bool, str]:
    if not window.account:
        return False, tr("val.no_account")
    seen: Dict[int, str] = {}
    for uid in all_unit_ids:
        u = window.account.units_by_id.get(uid)
        if not u:
            continue
        mid = u.unit_master_id
        name = window.monster_db.name_for(mid)
        if mid in seen:
            return False, tr("val.duplicate_monster_wgb", name=name)
        seen[mid] = name
    return True, ""


def on_validate_wgb(window) -> None:
    if not window.account:
        return
    selections = window._collect_wgb_selections()
    ok, msg, all_units = window._validate_team_structure("WGB", selections, must_have_team_size=3)
    if not ok:
        window.lbl_wgb_validate.setText(msg)
        QMessageBox.critical(window, tr("val.title_wgb"), msg)
        return
    ok2, msg2 = window._validate_unique_monsters(all_units)
    if not ok2:
        window.lbl_wgb_validate.setText(msg2)
        QMessageBox.critical(window, tr("val.title_wgb"), msg2)
        return
    window.lbl_wgb_validate.setText(msg)
    show_toast(window, msg, "success")
    window._render_wgb_preview(selections)


def on_edit_presets_wgb(window) -> None:
    if not window.account:
        return
    selections = window._collect_wgb_selections()
    ok, msg, all_units = window._validate_team_structure("WGB", selections, must_have_team_size=3)
    if not ok:
        QMessageBox.critical(window, "WGB", tr("dlg.validate_first", msg=msg))
        return
    ok2, msg2 = window._validate_unique_monsters(all_units)
    if not ok2:
        QMessageBox.critical(window, "WGB", msg2)
        return

    unit_rows: List[Tuple[int, str]] = [(uid, window._unit_text(uid)) for uid in all_units]
    dlg = BuildDialog(
        window,
        "WGB Builds",
        unit_rows,
        window.presets,
        "wgb",
        window.account,
        window._unit_icon_for_unit_id,
        team_size=3,
    )
    if dlg.exec() == QDialog.Accepted:
        ctx.store_compare_snapshot_from_build_dialog(window, "wgb", dlg)
        window.presets.save(window.presets_path)
        save_team_selections(window)
        show_toast(window, tr("dlg.builds_saved_title"), "success")


def on_optimize_wgb(window) -> None:
    if not window.account:
        return
    selections = window._collect_wgb_selections()
    ok, msg, all_units = window._validate_team_structure("WGB", selections, must_have_team_size=3)
    if not ok:
        QMessageBox.critical(window, "WGB", tr("dlg.validate_first", msg=msg))
        return
    ok2, msg2 = window._validate_unique_monsters(all_units)
    if not ok2:
        QMessageBox.critical(window, "WGB", msg2)
        return
    teams = [sel.unit_ids for sel in selections if sel.unit_ids]
    team_idx_by_uid = {int(uid): int(idx) for idx, sel in enumerate(selections) for uid in sel.unit_ids}
    run_mode_optimization(
        window,
        mode="wgb",
        running_text=tr("result.opt_running", mode="WGB"),
        profile_combo=window.combo_quality_profile_wgb,
        workers_combo=window.combo_workers_wgb,
        pass_spin=window.spin_multi_pass_wgb,
        unit_ids_in_order=window._units_by_turn_order("wgb", all_units),
        teams=teams,
        team_idx_by_uid=team_idx_by_uid,
        team_turn_by_uid=turn_order_by_uid(window, "wgb", all_units),
        leader_spd_bonus_by_uid=window._leader_spd_bonus_map(teams),
        status_label=window.lbl_wgb_validate,
        result_title=tr("result.title_wgb"),
        result_kwargs=dict(
            unit_team_index=team_idx_by_uid,
            unit_display_order={int(uid): idx for idx, uid in enumerate(all_units)},
        ),
    )


def render_wgb_preview(window, selections: List[TeamSelection] | None = None) -> None:
    if not window.account:
        return
    if selections is None:
        selections = window._collect_wgb_selections()
    teams = [sel.unit_ids for sel in selections if sel.unit_ids]
    # Empty preview stays hidden so the team slots can use the height.
    window.wgb_preview_cards.setVisible(bool(teams))
    window.wgb_preview_cards.render_from_selections(teams, window.account, window.monster_db, window.assets_dir, rune_mode="siege")


def on_rta_add_monster(window) -> None:
    window._ensure_unit_dropdowns_populated()
    uid = int(window.rta_add_combo.currentData() or 0)
    if uid == 0:
        return
    if window.rta_selected_list.count() >= 25:
        QMessageBox.warning(window, "RTA", tr("dlg.max_15_rta"))
        return
    for i in range(window.rta_selected_list.count()):
        if int(window.rta_selected_list.item(i).data(Qt.UserRole) or 0) == uid:
            return
    item = QListWidgetItem(window._unit_text(uid))
    item.setData(Qt.UserRole, uid)
    item.setIcon(window._unit_icon_for_unit_id(uid))
    window.rta_selected_list.addItem(item)
    window.rta_add_combo.setCurrentIndex(0)
    if hasattr(window.rta_add_combo, "_reset_search_field"):
        window.rta_add_combo._reset_search_field()


def on_rta_remove_monster(window) -> None:
    for item in list(window.rta_selected_list.selectedItems()):
        window.rta_selected_list.takeItem(window.rta_selected_list.row(item))


def on_take_current_rta(window) -> None:
    if not window.account:
        return
    active_uids = window.account.rta_active_unit_ids()
    window.rta_selected_list.clear()
    for uid in active_uids[:25]:
        item = QListWidgetItem(window._unit_text(uid))
        item.setData(Qt.UserRole, uid)
        item.setIcon(window._unit_icon_for_unit_id(uid))
        window.rta_selected_list.addItem(item)
    ids = window._collect_rta_unit_ids()
    if ids and len(ids) == len(set(ids)):
        window.lbl_rta_validate.setText(tr("rta.ok", count=len(ids)))
    else:
        window.lbl_rta_validate.setText(tr("status.rta_taken", count=min(len(active_uids), 25)))


def collect_rta_unit_ids(window) -> List[int]:
    ids: List[int] = []
    for i in range(window.rta_selected_list.count()):
        uid = int(window.rta_selected_list.item(i).data(Qt.UserRole) or 0)
        if uid != 0:
            ids.append(uid)
    return ids


def on_validate_rta(window) -> None:
    if not window.account:
        return
    ids = window._collect_rta_unit_ids()
    if not ids:
        msg = tr("rta.no_monsters")
        window.lbl_rta_validate.setText(msg)
        QMessageBox.critical(window, tr("val.title_rta"), msg)
        return
    seen: Set[int] = set()
    for uid in ids:
        if uid in seen:
            name = window._unit_text(uid)
            msg = tr("rta.duplicate", name=name)
            window.lbl_rta_validate.setText(msg)
            QMessageBox.critical(window, tr("val.title_rta"), msg)
            return
        seen.add(uid)
    msg = tr("rta.ok", count=len(ids))
    window.lbl_rta_validate.setText(msg)
    show_toast(window, msg, "success")


def on_edit_presets_rta(window) -> None:
    if not window.account:
        return
    ids = window._collect_rta_unit_ids()
    if not ids:
        QMessageBox.critical(window, "RTA", tr("dlg.select_monsters_first"))
        return
    if len(ids) != len(set(ids)):
        QMessageBox.critical(window, "RTA", tr("dlg.duplicates_found"))
        return
    unit_rows: List[Tuple[int, str]] = [(uid, window._unit_text(uid)) for uid in ids]
    dlg = BuildDialog(
        window,
        "RTA Builds",
        unit_rows,
        window.presets,
        "rta",
        window.account,
        window._unit_icon_for_unit_id,
        team_size=len(ids),
        show_order_sections=False,
    )
    if dlg.exec() == QDialog.Accepted:
        ctx.store_compare_snapshot_from_build_dialog(window, "rta", dlg)
        window.presets.save(window.presets_path)
        show_toast(window, tr("dlg.builds_saved_title"), "success")


def on_optimize_rta(window) -> None:
    if not window.account:
        return
    ids = window._collect_rta_unit_ids()
    if not ids:
        QMessageBox.critical(window, "RTA", tr("dlg.select_monsters_first"))
        return
    if len(ids) != len(set(ids)):
        QMessageBox.critical(window, "RTA", tr("dlg.duplicates_found"))
        return
    team_idx_by_uid = {int(uid): 0 for uid in ids}
    run_mode_optimization(
        window,
        mode="rta",
        running_text=tr("result.opt_running", mode="RTA"),
        profile_combo=window.combo_quality_profile_rta,
        workers_combo=window.combo_workers_rta,
        pass_spin=window.spin_multi_pass_rta,
        unit_ids_in_order=ids,
        teams=[ids],
        team_idx_by_uid=team_idx_by_uid,
        team_turn_by_uid={int(uid): pos + 1 for pos, uid in enumerate(ids)},
        leader_spd_bonus_by_uid={},
        status_label=window.lbl_rta_validate,
        result_title=tr("result.title_rta"),
        result_kwargs=dict(
            unit_team_index=team_idx_by_uid,
            unit_display_order={int(uid): idx for idx, uid in enumerate(ids)},
        ),
    )


def save_team_selections(window) -> None:
    """Persist current siege and WGB team selections to app_settings.json."""
    settings_path = window.config_dir / "app_settings.json"
    data: dict = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    siege_sel: List[List[int]] = []
    for row in getattr(window, "siege_team_combos", []):
        siege_sel.append([int(cmb.currentData() or 0) for cmb in row])
    if siege_sel:
        data["siege_team_selections"] = siege_sel

    siege_checks: List[bool] = [
        bool(chk.isChecked()) for chk in getattr(window, "siege_optimize_checks", [])
    ]
    if siege_checks:
        data["siege_optimize_checks"] = siege_checks

    wgb_sel: List[List[int]] = []
    for row in getattr(window, "wgb_team_combos", []):
        wgb_sel.append([int(cmb.currentData() or 0) for cmb in row])
    if wgb_sel:
        data["wgb_team_selections"] = wgb_sel

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def restore_team_selections(window, mode: str = "all") -> None:
    """Restore siege and WGB team selections from app_settings.json."""
    settings_path = window.config_dir / "app_settings.json"
    if not settings_path.exists():
        return
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return

    if mode in ("all", "siege"):
        siege_sel = data.get("siege_team_selections")
        if isinstance(siege_sel, list):
            for t, row_uids in enumerate(siege_sel):
                combos = getattr(window, "siege_team_combos", [])
                if t >= len(combos):
                    break
                row = combos[t]
                for s, uid in enumerate(row_uids if isinstance(row_uids, list) else []):
                    if s >= len(row):
                        break
                    uid = int(uid or 0)
                    if uid:
                        idx = row[s].findData(uid, role=Qt.UserRole)
                        if idx >= 0:
                            row[s].setCurrentIndex(idx)
                            if hasattr(row[s], "_sync_line_edit_to_current"):
                                row[s]._sync_line_edit_to_current()

        siege_checks = data.get("siege_optimize_checks")
        if isinstance(siege_checks, list):
            for t, checked in enumerate(siege_checks):
                checks = getattr(window, "siege_optimize_checks", [])
                if t >= len(checks):
                    break
                checks[t].setChecked(bool(checked))

    if mode in ("all", "wgb"):
        wgb_sel = data.get("wgb_team_selections")
        if isinstance(wgb_sel, list):
            for t, row_uids in enumerate(wgb_sel):
                combos = getattr(window, "wgb_team_combos", [])
                if t >= len(combos):
                    break
                row = combos[t]
                for s, uid in enumerate(row_uids if isinstance(row_uids, list) else []):
                    if s >= len(row):
                        break
                    uid = int(uid or 0)
                    if uid:
                        idx = row[s].findData(uid, role=Qt.UserRole)
                        if idx >= 0:
                            row[s].setCurrentIndex(idx)
                            if hasattr(row[s], "_sync_line_edit_to_current"):
                                row[s]._sync_line_edit_to_current()
