from __future__ import annotations


from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from desktop_app.i18n import tr
from desktop_app.ui.dialogs.team_editor_dialog import TeamEditorDialog
from desktop_app.ui.main_window_sections.mode_actions import run_mode_optimization, turn_order_by_uid


def init_team_tab_ui(window) -> None:
    layout = QVBoxLayout(window.tab_team_builder)

    row = QHBoxLayout()
    window.lbl_team = QLabel(tr("label.team"))
    row.addWidget(window.lbl_team)
    window.team_combo = QComboBox()
    window.team_combo.currentIndexChanged.connect(window._on_team_selected)
    row.addWidget(window.team_combo, 1)
    layout.addLayout(row)

    btn_row = QHBoxLayout()
    window.btn_new_team = QPushButton(tr("btn.new_team"))
    window.btn_new_team.clicked.connect(window._on_new_team)
    btn_row.addWidget(window.btn_new_team)
    window.btn_edit_team = QPushButton(tr("btn.edit_team"))
    window.btn_edit_team.clicked.connect(window._on_edit_team)
    btn_row.addWidget(window.btn_edit_team)
    window.btn_remove_team = QPushButton(tr("btn.delete_team"))
    window.btn_remove_team.clicked.connect(window._on_remove_team)
    btn_row.addWidget(window.btn_remove_team)
    layout.addLayout(btn_row)

    window.btn_optimize_team = QPushButton(tr("btn.optimize_team"))
    window.btn_optimize_team.clicked.connect(window._optimize_team)
    layout.addWidget(window.btn_optimize_team)

    pass_row = QHBoxLayout()
    window.lbl_team_passes = QLabel(tr("label.passes"))
    pass_row.addWidget(window.lbl_team_passes)
    window.spin_multi_pass_team = QSpinBox()
    window.spin_multi_pass_team.setRange(1, 10)
    window.spin_multi_pass_team.setValue(3)
    window.spin_multi_pass_team.setToolTip(tr("tooltip.passes"))
    window.spin_multi_pass_team.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
    pass_row.addWidget(window.spin_multi_pass_team)
    window.lbl_team_workers = QLabel(tr("label.workers"))
    pass_row.addWidget(window.lbl_team_workers)
    window.combo_workers_team = QComboBox()
    window._populate_worker_combo(window.combo_workers_team)
    pass_row.addWidget(window.combo_workers_team)
    window.lbl_team_profile = QLabel(tr("label.mode"))
    pass_row.addWidget(window.lbl_team_profile)
    window.combo_quality_profile_team = QComboBox()
    window.combo_quality_profile_team.addItem(tr("profile.smart"), "gpu_combo")
    window.combo_quality_profile_team.addItem(tr("profile.maximum"), "max_quality")
    idx_gpu_team = window.combo_quality_profile_team.findData("gpu_combo")
    window.combo_quality_profile_team.setCurrentIndex(idx_gpu_team if idx_gpu_team >= 0 else 0)
    window.combo_quality_profile_team.currentIndexChanged.connect(window._sync_worker_controls)
    pass_row.addWidget(window.combo_quality_profile_team)
    window._sync_worker_controls()
    pass_row.addStretch(1)
    layout.addLayout(pass_row)

    window.lbl_team_opt_status = QLabel("—")
    layout.addWidget(window.lbl_team_opt_status)

    window.lbl_team_units = QLabel(tr("label.import_account_first"))
    layout.addWidget(window.lbl_team_units)

    window._refresh_team_combo()
    window._set_team_controls_enabled(False)


def current_team(window):
    tid = str(window.team_combo.currentData() or "")
    if not tid:
        return None
    return window.team_store.teams.get(tid)


def refresh_team_combo(window) -> None:
    current_id = str(window.team_combo.currentData() or "")
    window.team_combo.blockSignals(True)
    window.team_combo.clear()
    teams = sorted(window.team_store.teams.values(), key=lambda t: t.name)
    for team in teams:
        window.team_combo.addItem(f"{team.name} ({len(team.unit_ids)} {tr('label.units')})", team.id)
    window.team_combo.blockSignals(False)
    if not teams:
        window.lbl_team_units.setText(tr("label.no_teams"))
        window._set_team_controls_enabled(False)
        return
    window._select_team_by_id(current_id or teams[0].id)
    window._on_team_selected()


def select_team_by_id(window, tid: str) -> None:
    idx = window.team_combo.findData(tid)
    if idx >= 0:
        window.team_combo.setCurrentIndex(idx)


def set_team_controls_enabled(window, has_account: bool) -> None:
    team_exists = window._current_team() is not None
    window.btn_new_team.setEnabled(has_account)
    window.btn_edit_team.setEnabled(has_account and team_exists)
    window.btn_remove_team.setEnabled(has_account and team_exists)
    window.btn_optimize_team.setEnabled(has_account and team_exists)
    window.team_combo.setEnabled(bool(window.team_store.teams))


def on_team_selected(window) -> None:
    team = window._current_team()
    if not team:
        if not window.team_store.teams:
            window.lbl_team_units.setText(tr("label.no_teams"))
        else:
            window.lbl_team_units.setText(tr("label.no_team_selected"))
        window._set_team_controls_enabled(bool(window.account))
        return
    window.lbl_team_units.setText(window._team_units_text(team))
    window._set_team_controls_enabled(bool(window.account))
    if not window.account:
        return


def team_units_text(window, team) -> str:
    if not team.unit_ids:
        return tr("label.no_units")
    return "\n".join(window._unit_text_cached(uid) for uid in team.unit_ids)


def on_new_team(window) -> None:
    if not window.account:
        QMessageBox.warning(window, tr("label.team"), tr("dlg.load_import_first"))
        return
    dlg = TeamEditorDialog(
        window,
        window.account,
        window._unit_text_cached,
        window._icon_for_master_id,
        unit_combo_model=window._ensure_unit_combo_model(),
    )
    if dlg.exec() != QDialog.Accepted:
        return
    try:
        team = window.team_store.upsert(dlg.team_name or "Team", dlg.unit_ids)
    except ValueError as exc:
        QMessageBox.warning(window, tr("label.team"), str(exc))
        return
    window.team_store.save(window.team_config_path)
    window._refresh_team_combo()
    window._select_team_by_id(team.id)


def on_edit_team(window) -> None:
    if not window.account:
        QMessageBox.warning(window, tr("label.team"), tr("dlg.load_import_first"))
        return
    team = window._current_team()
    if not team:
        return
    dlg = TeamEditorDialog(
        window,
        window.account,
        window._unit_text_cached,
        window._icon_for_master_id,
        team=team,
        unit_combo_model=window._ensure_unit_combo_model(),
    )
    if dlg.exec() != QDialog.Accepted:
        return
    try:
        window.team_store.upsert(dlg.team_name or team.name, dlg.unit_ids, tid=team.id)
    except ValueError as exc:
        QMessageBox.warning(window, tr("label.team"), str(exc))
        return
    window.team_store.save(window.team_config_path)
    window._refresh_team_combo()
    window._select_team_by_id(team.id)


def on_remove_team(window) -> None:
    team = window._current_team()
    if not team:
        return
    window.team_store.remove(team.id)
    window.team_store.save(window.team_config_path)
    window._refresh_team_combo()


def optimize_team(window) -> None:
    team = window._current_team()
    if not window.account or not team:
        QMessageBox.warning(window, tr("label.team"), tr("dlg.load_import_and_team"))
        return
    run_mode_optimization(
        window,
        mode="siege",
        running_text=tr("result.team_opt_running", name=team.name),
        profile_combo=window.combo_quality_profile_team,
        workers_combo=window.combo_workers_team,
        pass_spin=window.spin_multi_pass_team,
        unit_ids_in_order=window._units_by_turn_order("siege", team.unit_ids),
        teams=[team.unit_ids],
        team_idx_by_uid={int(uid): 0 for uid in team.unit_ids},
        team_turn_by_uid=turn_order_by_uid(window, "siege", team.unit_ids),
        leader_spd_bonus_by_uid=window._leader_spd_bonus_map([team.unit_ids]),
        status_label=window.lbl_team_opt_status,
        result_title=tr("result.title_team", name=team.name),
        result_kwargs={},
        toast=False,
    )


def ensure_siege_team_defaults(window) -> None:
    if not window.account:
        return
    existing_names = {team.name for team in window.team_store.teams.values()}
    added = False
    for idx, units in enumerate(window.account.siege_def_teams(), start=1):
        if not units:
            continue
        name = tr("label.defense", n=idx)
        legacy_name = f"Siege Verteidigung {idx}"
        if name in existing_names or legacy_name in existing_names:
            continue
        try:
            window.team_store.upsert(name, units)
        except ValueError:
            continue
        existing_names.add(name)
        added = True
    if added:
        window.team_store.save(window.team_config_path)
