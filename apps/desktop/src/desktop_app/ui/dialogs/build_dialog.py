from __future__ import annotations

import copy
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Set, Tuple

from PySide6.QtCore import Qt, QPoint, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_app.domain.models import AccountData
from desktop_app.domain.presets import (
    Build,
    BuildStore,
    EFFECT_ID_TO_MAINSTAT_KEY,
    MAINSTAT_KEYS,
)
from desktop_app.domain.build_editor_helpers import (
    artifact_pref_from_entry,
    artifact_prefs_from_trend,
    build_min_stats,
    can_load_current_runes,
    mainstat_combos_246,
    capture_current_runes_snapshot,
    collect_artifact_substat_options_by_type,
    mainstats_from_community_trend,
    min_mode_for_build,
    min_value_for_build,
    merge_preferred_set_ids,
    normalize_set_id_groups,
    parse_set_options_to_slot_ids,
    rune_mode_for_mode,
    slot_ids_from_equipped_runes,
    top_set_ids_from_combos,
    rune_pref_mainstats_by_slot,
    rune_pref_slot_set_ids,
    sanitize_rune_snapshot,
    set_id_combos_to_names,
    set_slots_from_community_trend,
    unit_base_stats_for_min,
    unit_master_id_for_unit,
    unit_pref_metadata,
    validate_order_tick_plausibility,
)
from desktop_app.i18n import tr
from desktop_app.services.rune_preference_service import RunePrefCache
from desktop_app.services.cloud_learning_service import (
    build_trends_artifact_substat_limit,
    BuildPreferenceTrend,
    build_trends_mainstat_limit,
    build_trends_opt_in_enabled,
    build_trends_set_combo_limit,
    fetch_build_preference_trends,
)
from desktop_app.ui.dpi import dp
from desktop_app.ui import theme as _theme
from desktop_app.ui.widgets.single_team_order_editor import SingleTeamOrderEditor
from desktop_app.ui.widgets.unit_build_editor_widget import (
    UnitBuildEditorWidget,
    UnitEditorRefs,
    set_art_focus_combo_value,
    set_art_sub_combo_value,
)


def _rune_prefs_path() -> Path:
    if getattr(sys, "frozen", False):
        from desktop_app.services.account_persistence import user_data_dir
        return user_data_dir() / "monster_rune_set_preferences.json"
    return Path(__file__).resolve().parents[2] / "config" / "monster_rune_set_preferences.json"


def _rune_prefs_fallback_path() -> "Path | None":
    """Returns the bundled read-only preferences file as fallback (frozen EXE only)."""
    if not getattr(sys, "frozen", False):
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    p = Path(meipass) / "desktop_app" / "config" / "monster_rune_set_preferences.json"
    if p.exists():
        return p
    legacy = Path(meipass) / "app" / "config" / "monster_rune_set_preferences.json"
    return legacy if legacy.exists() else None


@dataclass
class BuildDialogSnapshot:
    """Captured initial state for Restore Saved Preset."""
    build_by_unit: Dict[int, Any]  # Dict[int, Build]
    unit_list_order: List[int]
    team_speed_lead_by_team: Dict[int, int]
    team_speed_lead_pct_by_team: Dict[int, int]
    team_effect_control_state: Dict[Tuple[int, int], Dict[str, Any]]


class BuildDialog(QDialog):
    """
    Build editor for team presets:
    - one build per unit (Default)
    - sets/mainstats per unit
    - optimization/turn order via dedicated drag & drop lists
    """

    def __init__(
        self,
        parent: QWidget,
        title: str,
        unit_rows: List[Tuple[int, str]],
        preset_store: BuildStore,
        mode: str,
        account: AccountData | None,
        unit_icon_fn: Callable[[int], QIcon],
        team_size: int = 3,
        show_order_sections: bool = True,
        order_teams: List[List[Tuple[int, str]]] | None = None,
        order_team_titles: List[str] | None = None,
        order_turn_effects: List[Dict[int, Dict[str, Any]]] | None = None,
        show_turn_effect_controls: bool = False,
        order_turn_effect_capabilities: Dict[int, Dict[str, Any]] | None = None,
        show_speed_lead_controls: bool = False,
        order_speed_leaders: List[int] | None = None,
        order_speed_lead_pct_by_unit: Dict[int, int] | None = None,
        order_speed_lead_pct_by_team: List[int] | None = None,
        persist_order_fields: bool = True,
        skill_icons_dir: str | None = None,
    ):
        super().__init__(parent)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowMinimizeButtonHint
        )
        self.setWindowTitle(title)
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            self.setMinimumSize(int(avail.width() * 0.55), int(avail.height() * 0.65))
        else:
            self.setMinimumSize(980, 620)

        self.preset_store = preset_store
        self.mode = mode
        self._account = account
        self._unit_icon_fn = unit_icon_fn
        self._unit_rows = list(unit_rows)
        self._unit_rows_by_uid: Dict[int, Tuple[int, str]] = {int(uid): (int(uid), str(lbl)) for uid, lbl in self._unit_rows}
        self._persist_order_fields = bool(persist_order_fields)
        self._artifact_substat_options_by_type = collect_artifact_substat_options_by_type(self._account)

        layout = QVBoxLayout(self)

        self._opt_order_list: QListWidget | None = None
        self._order_section: SingleTeamOrderEditor | None = None
        self._loaded_current_runes = False
        self._loaded_current_runes_snapshot: Dict[str, Any] = {}
        self._rune_pref_cache = RunePrefCache(_rune_prefs_path(), self._account, _rune_prefs_fallback_path())
        self._community_trends_loaded = False
        self._community_trend_by_unit: Dict[int, BuildPreferenceTrend] = {}
        self._community_trend_missing_units: Set[int] = set()
        self._unit_editors: Dict[int, UnitBuildEditorWidget] = {}

        if show_order_sections:
            self._order_section = SingleTeamOrderEditor(
                mode=mode,
                order_teams=order_teams,
                unit_rows=unit_rows,
                team_size=team_size,
                order_team_titles=list(order_team_titles or []),
                order_turn_effects=list(order_turn_effects or []),
                order_turn_effect_capabilities=dict(order_turn_effect_capabilities or {}),
                order_speed_leaders=list(order_speed_leaders or []),
                order_speed_lead_pct_by_unit=dict(order_speed_lead_pct_by_unit or {}),
                order_speed_lead_pct_by_team=list(order_speed_lead_pct_by_team or []),
                show_turn_effect_controls=show_turn_effect_controls,
                show_speed_lead_controls=show_speed_lead_controls,
                preset_store=preset_store,
                unit_icon_fn=unit_icon_fn,
                skill_icons_dir=Path(skill_icons_dir) if skill_icons_dir else None,
            )
            self._order_section.unit_selected.connect(self._on_order_section_unit_selected)
            layout.addWidget(self._order_section)

        # Per-unit widget refs (replaces 22 individual dicts)
        self._unit_label_by_id: Dict[int, str] = {uid: lbl for uid, lbl in self._unit_rows}
        self._unit_editor_stack = QStackedWidget()
        self._unit_list = QListWidget()
        self._unit_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._unit_list.setIconSize(QSize(dp(34), dp(34)))
        self._unit_list.setDragDropMode(QAbstractItemView.InternalMove)
        self._unit_list.setDefaultDropAction(Qt.MoveAction)
        self._unit_list.setToolTip(tr("tooltip.optimize_order_priority"))
        self._unit_list.setFrameShape(QFrame.NoFrame)

        editor_split = QSplitter(Qt.Horizontal)
        editor_split.setChildrenCollapsible(True)
        editor_split.setHandleWidth(dp(3))

        _list_title = tr("group.build_monster_list")
        list_panel = QWidget()
        list_panel.setObjectName("buildListPanel")
        list_panel.setMinimumWidth(0)
        list_panel_layout = QVBoxLayout(list_panel)
        list_panel_layout.setContentsMargins(0, 0, 0, 0)
        list_panel_layout.setSpacing(0)

        list_toggle_btn = QPushButton("◀  " + _list_title)
        list_toggle_btn.setObjectName("buildUnitListToggle")
        list_toggle_btn.setCheckable(True)
        list_toggle_btn.setChecked(True)
        list_toggle_btn.setMinimumWidth(0)
        list_toggle_btn.setToolTip(tr("tooltip.optimize_order_priority"))
        list_toggle_btn.setStyleSheet(
            "QPushButton { text-align: left; padding: 4px 8px; border: none;"
            " border-bottom: 1px solid palette(mid);"
            " background: transparent; font-weight: bold; }"
            "QPushButton:hover { background: rgba(255,255,255,0.05); }"
        )

        list_content = QWidget()
        list_content.setObjectName("buildUnitListCard")
        list_content_layout = QVBoxLayout(list_content)
        list_content_layout.setContentsMargins(dp(8), dp(8), dp(8), dp(8))
        self._unit_list.setObjectName("buildUnitList")
        list_content_layout.addWidget(self._unit_list, 1)

        def _on_unit_list_toggle(checked: bool) -> None:
            list_content.setVisible(bool(checked))
            list_toggle_btn.setText(("◀  " + _list_title) if checked else "▶")
            total = editor_split.width()
            if checked:
                editor_split.setSizes([dp(340), max(0, total - dp(340))])
            else:
                editor_split.setSizes([dp(28), max(0, total - dp(28))])

        list_toggle_btn.toggled.connect(_on_unit_list_toggle)
        list_panel_layout.addWidget(list_toggle_btn)
        list_panel_layout.addWidget(list_content, 1)
        bottom_left_buttons: List[QPushButton] = []
        if can_load_current_runes(self._account, self.mode):
            btn_load_runes = QPushButton(tr("btn.load_current_runes"))
            btn_load_runes.setToolTip(tr("tooltip.load_current_runes"))
            btn_load_runes.clicked.connect(self._on_load_current_runes)
            bottom_left_buttons.append(btn_load_runes)
        btn_load_preferred_all = QPushButton(tr("btn.load_preferred_runes_all"))
        btn_load_preferred_all.setToolTip(tr("tooltip.load_preferred_runes_all"))
        btn_load_preferred_all.clicked.connect(self._on_load_preferred_runes_for_all)
        bottom_left_buttons.append(btn_load_preferred_all)
        btn_load_preferred_artifacts_all = QPushButton(tr("btn.load_preferred_artifacts_all"))
        btn_load_preferred_artifacts_all.setToolTip(tr("tooltip.load_preferred_artifacts_all"))
        btn_load_preferred_artifacts_all.clicked.connect(self._on_load_preferred_artifacts_for_all)
        bottom_left_buttons.append(btn_load_preferred_artifacts_all)
        btn_load_community_all = QPushButton(tr("btn.load_community_trends_all"))
        btn_load_community_all.setToolTip(tr("tooltip.load_community_trends_all"))
        btn_load_community_all.clicked.connect(self._on_load_community_trends_for_all)
        bottom_left_buttons.append(btn_load_community_all)
        btn_restore_saved_preset = QPushButton(tr("btn.restore_saved_preset"))
        btn_restore_saved_preset.setToolTip(tr("tooltip.restore_saved_preset"))
        btn_restore_saved_preset.clicked.connect(self._on_restore_saved_preset)
        bottom_left_buttons.append(btn_restore_saved_preset)
        editor_split.addWidget(list_panel)

        detail_box = QGroupBox(tr("group.build_editor"))
        detail_box.setObjectName("buildEditorBox")
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(dp(8), dp(8), dp(8), dp(8))
        self._unit_editor_stack.setObjectName("buildEditorStack")
        detail_layout.addWidget(self._unit_editor_stack, 1)
        editor_split.addWidget(detail_box)
        editor_split.setStretchFactor(0, 0)
        editor_split.setStretchFactor(1, 1)
        editor_split.setSizes([340, 1100])
        layout.addWidget(editor_split, 1)

        table_rows = list(self._unit_rows)
        table_rows.sort(
            key=lambda x: (
                int(getattr((self.preset_store.get_unit_builds(self.mode, int(x[0])) or [Build.default_any()])[0], "optimize_order", 0) or 0) <= 0,
                int(getattr((self.preset_store.get_unit_builds(self.mode, int(x[0])) or [Build.default_any()])[0], "optimize_order", 0) or 0),
                next((idx for idx, it in enumerate(self._unit_rows) if int(it[0]) == int(x[0])), 10000),
            )
        )

        self._uid_to_stack_index: Dict[int, int] = {}
        for unit_id, label in table_rows:
            item = QListWidgetItem(label)
            icon = self._unit_icon_fn(unit_id)
            if not icon.isNull():
                item.setIcon(icon)
            item.setData(Qt.UserRole, int(unit_id))
            self._unit_list.addItem(item)
            self._uid_to_stack_index[int(unit_id)] = -1

        self._unit_list.currentRowChanged.connect(self._on_unit_row_changed)
        if self._unit_list.count() > 0:
            self._unit_list.setCurrentRow(0)
        self._initial_snapshot = BuildDialogSnapshot(
            build_by_unit={
                int(uid): copy.deepcopy(
                    (self.preset_store.get_unit_builds(self.mode, int(uid)) or [Build.default_any()])[0]
                )
                for uid, _label in self._unit_rows
                if int(uid) > 0
            },
            unit_list_order=self._unit_list_uid_order(),
            team_speed_lead_by_team=self._order_section.capture_speed_lead_uid_state() if self._order_section else {},
            team_speed_lead_pct_by_team=self._order_section.capture_speed_lead_pct_state() if self._order_section else {},
            team_effect_control_state=self._order_section.capture_effect_control_state() if self._order_section else {},
        )

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(dp(8))

        actions_menu = QMenu()
        for btn in bottom_left_buttons:
            action = actions_menu.addAction(btn.text())
            action.setToolTip(btn.toolTip())
            action.triggered.connect(btn.click)

        actions_btn = QPushButton(tr("btn.actions") + "  ▲")

        def _show_actions_menu() -> None:
            pos = actions_btn.mapToGlobal(QPoint(0, -actions_menu.sizeHint().height()))
            actions_menu.exec_(pos)

        actions_btn.clicked.connect(_show_actions_menu)
        footer_row.addWidget(actions_btn)
        footer_row.addStretch(1)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        footer_row.addWidget(btns, 0, Qt.AlignRight)
        layout.addLayout(footer_row)

        c = _theme.C
        editor_split.setStyleSheet(
            f"""
            QSplitter::handle {{
                background: transparent;
                border: none;
            }}
            QSplitter::handle:horizontal {{
                margin: {dp(2)}px 0;
            }}
            QSplitter::handle:hover {{
                background: {c['border']};
            }}
            """
        )
        self.setStyleSheet(
            f"""
            QPushButton#buildUnitListToggle {{
                text-align: left;
                padding: {dp(6)}px {dp(10)}px;
                border: none;
                border-radius: 0px;
                background: transparent;
                font-weight: 600;
            }}
            QPushButton#buildUnitListToggle:hover {{
                color: {c['text']};
            }}
            QWidget#buildListPanel {{
                border: 1px solid {c['border']};
                border-radius: {dp(8)}px;
                background: transparent;
            }}
            QWidget#buildUnitListCard {{
                background: transparent;
                border: none;
                border-radius: 0px;
            }}
            QListWidget#buildUnitList {{
                background: {c['bg']};
                border: none;
                border-radius: 0px;
                padding: 0px;
            }}
            QListWidget#buildUnitList::item {{
                border-radius: {dp(6)}px;
                margin: {dp(2)}px;
                padding: {dp(4)}px {dp(6)}px;
            }}
            QGroupBox#buildEditorBox {{
                border: 1px solid {c['border']};
                border-radius: {dp(8)}px;
                margin-top: {dp(8)}px;
                padding-top: {dp(14)}px;
            }}
            QGroupBox#buildEditorBox::title {{
                subcontrol-origin: margin;
                left: {dp(10)}px;
                padding: 0 {dp(6)}px;
                color: {c['text_dim']};
            }}
            """
        )

        # Show only after the full UI is constructed to avoid a brief white flash.
        self.showMaximized()

    def accept(self) -> None:
        # Commit any in-progress spinbox edits (value may not yet be committed
        # if the user typed but didn't press Enter or click away first).
        focused = QApplication.focusWidget()
        if focused is not None:
            focused.clearFocus()
        for widget in self._unit_editors.values():
            for spin in widget.refs.all_min_spins().values():
                try:
                    spin.interpretText()
                except Exception:
                    pass
        try:
            self.apply_to_store()
        except ValueError as exc:
            QMessageBox.critical(self, "Builds", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Builds", f"Fehler beim Speichern:\n{exc}")
            return
        super().accept()

    def _on_unit_row_changed(self, row: int) -> None:
        if row < 0 or row >= self._unit_list.count():
            return
        item = self._unit_list.item(row)
        uid = int(item.data(Qt.UserRole) or 0) if item else 0
        stack_idx = self._ensure_editor_page(int(uid))
        if 0 <= stack_idx < self._unit_editor_stack.count():
            self._unit_editor_stack.setCurrentIndex(stack_idx)

    def _ensure_editor_page(self, unit_id: int) -> int:
        uid = int(unit_id or 0)
        if uid <= 0:
            return -1
        _raw = self._uid_to_stack_index.get(uid)
        existing = int(_raw) if _raw is not None else -1
        if existing >= 0 and existing < self._unit_editor_stack.count():
            return int(existing)
        builds = self.preset_store.get_unit_builds(self.mode, uid)
        b0 = builds[0] if builds else Build.default_any()
        editor_page = self._build_unit_editor(int(uid), b0)
        stack_idx = int(self._unit_editor_stack.addWidget(editor_page))
        self._uid_to_stack_index[int(uid)] = int(stack_idx)
        return int(stack_idx)

    def _ensure_all_editor_pages(self) -> None:
        for row in range(self._unit_list.count()):
            item = self._unit_list.item(row)
            uid = int(item.data(Qt.UserRole) or 0) if item else 0
            if uid > 0:
                self._ensure_editor_page(int(uid))

    def _editor_refs(self, unit_id: int) -> UnitEditorRefs | None:
        widget = self._unit_editors.get(int(unit_id or 0))
        return widget.refs if widget is not None else None

    def _row_for_uid_in_unit_list(self, uid: int) -> int:
        target = int(uid or 0)
        if target <= 0:
            return -1
        for row in range(self._unit_list.count()):
            item = self._unit_list.item(row)
            if int(item.data(Qt.UserRole) or 0) == target:
                return int(row)
        return -1

    def _unit_list_uid_order(self) -> List[int]:
        order: List[int] = []
        for row in range(self._unit_list.count()):
            item = self._unit_list.item(row)
            uid = int(item.data(Qt.UserRole) or 0) if item else 0
            if uid > 0:
                order.append(int(uid))
        return order

    def _restore_unit_list_uid_order(self, uid_order: List[int]) -> None:
        target_order = [int(uid) for uid in (uid_order or []) if int(uid) > 0]
        if not target_order:
            return
        selected_uid = 0
        current_item = self._unit_list.currentItem()
        if current_item is not None:
            selected_uid = int(current_item.data(Qt.UserRole) or 0)

        rank_by_uid = {int(uid): idx for idx, uid in enumerate(target_order)}
        items: List[QListWidgetItem] = []
        while self._unit_list.count() > 0:
            item = self._unit_list.takeItem(0)
            if item is not None:
                items.append(item)
        items.sort(
            key=lambda it: (
                rank_by_uid.get(int(it.data(Qt.UserRole) or 0), 999999),
                str(it.text() or "").lower(),
            )
        )
        for item in items:
            self._unit_list.addItem(item)

        restore_uid = int(selected_uid or 0)
        if restore_uid <= 0 and target_order:
            restore_uid = int(target_order[0])
        row = self._row_for_uid_in_unit_list(int(restore_uid))
        if row >= 0:
            self._unit_list.setCurrentRow(int(row))

    def _on_order_section_unit_selected(self, uid: int) -> None:
        row = self._row_for_uid_in_unit_list(int(uid))
        if row >= 0 and self._unit_list.currentRow() != row:
            self._unit_list.setCurrentRow(int(row))

    def _build_unit_editor(self, unit_id: int, build: Build) -> UnitBuildEditorWidget:
        widget = UnitBuildEditorWidget(
            unit_id=int(unit_id),
            build=build,
            account=self._account,
            artifact_options_by_type=self._artifact_substat_options_by_type,
            has_rune_pref=self._rune_pref_cache.has_rune_pref(int(unit_id)),
            has_artifact_pref=self._rune_pref_cache.has_artifact_pref(int(unit_id)),
            community_status_text=self._community_status_text_for_unit(int(unit_id)),
        )
        widget.load_pref_runes_requested.connect(self._on_load_preferred_runes_for_unit)
        widget.load_community_trends_requested.connect(self._on_load_community_trends_for_unit)
        widget.save_pref_runes_requested.connect(self._on_save_preferred_runes_for_unit)
        widget.load_pref_artifacts_requested.connect(self._on_load_preferred_artifacts_for_unit)
        widget.save_pref_artifacts_requested.connect(self._on_save_preferred_artifacts_for_unit)
        widget.set_constraints_changed.connect(self._sync_set_combo_constraints_for_unit)
        self._unit_editors[unit_id] = widget
        self._sync_set_combo_constraints_for_unit(int(unit_id))
        self._refresh_community_status_label(int(unit_id))
        return widget

    def _is_set3_allowed_for_unit(self, unit_id: int) -> bool:
        refs = self._editor_refs(unit_id)
        if refs is None:
            return False
        s1 = refs.set1.checked_sizes()
        s2 = refs.set2.checked_sizes()
        if not refs.set1.checked_ids() or not refs.set2.checked_ids():
            return False
        return s1 == {2} and s2 == {2}

    def _sync_set_combo_constraints_for_unit(self, unit_id: int) -> None:
        refs = self._editor_refs(unit_id)
        if refs is None:
            return
        c1, c2, c3 = refs.set1, refs.set2, refs.set3

        c1.set_enforced_size(None)
        c2.set_enforced_size(None)

        allow_set3 = self._is_set3_allowed_for_unit(int(unit_id))
        if allow_set3:
            c3.setEnabled(True)
            c3.set_enforced_size(2)
        else:
            c3.clear_checked()
            c3.set_enforced_size(None)
            c3.setEnabled(False)

    # -- Rune preference access (delegated to RunePrefCache) --

    def _rune_pref_entry_for_unit(self, unit_id: int) -> Dict[str, Any] | None:
        return self._rune_pref_cache.entry_for_unit(int(unit_id))

    def _load_artifact_prefs_into_editor(
        self,
        unit_id: int,
        artifact_focus: Dict[str, List[str]] | None = None,
        artifact_substats: Dict[str, List[int]] | None = None,
    ) -> bool:
        uid = int(unit_id or 0)
        if uid <= 0:
            return False

        self._ensure_editor_page(int(uid))
        refs = self._editor_refs(uid)
        if refs is None:
            return False
        focus_cfg = dict(artifact_focus or {})
        subs_cfg = dict(artifact_substats or {})

        for cmb in (refs.art_attr_focus, refs.art_type_focus):
            idx_any = cmb.findData("")
            if idx_any >= 0:
                cmb.setCurrentIndex(int(idx_any))
        for key, cmb in (("attribute", refs.art_attr_focus), ("type", refs.art_type_focus)):
            selected = ""
            for item in list(focus_cfg.get(str(key), []) or []):
                cand = str(item or "").strip().upper()
                if cand in ("HP", "ATK", "DEF"):
                    selected = cand
                    break
            if selected:
                set_art_focus_combo_value(cmb, selected)

        art_attr_sub1, art_attr_sub2 = refs.art_attr_sub1, refs.art_attr_sub2
        art_type_sub1, art_type_sub2 = refs.art_type_sub1, refs.art_type_sub2
        for cmb in (art_attr_sub1, art_attr_sub2, art_type_sub1, art_type_sub2):
            if cmb is None:
                continue
            idx_any = cmb.findData(0)
            if idx_any >= 0:
                cmb.setCurrentIndex(int(idx_any))

        attr_subs: List[int] = []
        seen_attr: Set[int] = set()
        for item in list(subs_cfg.get("attribute", []) or []):
            try:
                eid = int(item or 0)
            except Exception:
                eid = 0
            if eid <= 0 or eid in seen_attr:
                continue
            seen_attr.add(eid)
            attr_subs.append(int(eid))
            if len(attr_subs) >= 2:
                break

        type_subs: List[int] = []
        seen_type: Set[int] = set()
        for item in list(subs_cfg.get("type", []) or []):
            try:
                eid = int(item or 0)
            except Exception:
                eid = 0
            if eid <= 0 or eid in seen_type:
                continue
            seen_type.add(eid)
            type_subs.append(int(eid))
            if len(type_subs) >= 2:
                break

        if art_attr_sub1 is not None and len(attr_subs) >= 1:
            set_art_sub_combo_value(art_attr_sub1, int(attr_subs[0]))
        if art_attr_sub2 is not None and len(attr_subs) >= 2:
            set_art_sub_combo_value(art_attr_sub2, int(attr_subs[1]))
        if art_type_sub1 is not None and len(type_subs) >= 1:
            set_art_sub_combo_value(art_type_sub1, int(type_subs[0]))
        if art_type_sub2 is not None and len(type_subs) >= 2:
            set_art_sub_combo_value(art_type_sub2, int(type_subs[1]))

        has_focus = bool(
            list(focus_cfg.get("attribute", []) or [])
            or list(focus_cfg.get("type", []) or [])
        )
        return bool(has_focus or attr_subs or type_subs)

    def _read_set_options_from_editor(self, unit_id: int) -> List[List[int]]:
        self._sync_set_combo_constraints_for_unit(int(unit_id))
        refs = self._editor_refs(unit_id)
        if refs is None:
            return []
        set1_ids = [int(x) for x in refs.set1.checked_ids()]
        set2_ids = [int(x) for x in refs.set2.checked_ids()]
        set3_ids = [int(x) for x in refs.set3.checked_ids()] if self._is_set3_allowed_for_unit(int(unit_id)) else []
        groups: List[List[int]] = []
        if set1_ids:
            groups.append(set1_ids)
        if set2_ids:
            groups.append(set2_ids)
        if set3_ids:
            groups.append(set3_ids)
        if not groups:
            return []
        return normalize_set_id_groups(groups)

    def _read_mainstats_from_editor(self, unit_id: int) -> Dict[int, List[str]]:
        out: Dict[int, List[str]] = {2: [], 4: [], 6: []}
        refs = self._editor_refs(unit_id)
        if refs is None:
            return out
        out[2] = [str(x) for x in (refs.ms2.checked_values() or []) if str(x) in MAINSTAT_KEYS]
        out[4] = [str(x) for x in (refs.ms4.checked_values() or []) if str(x) in MAINSTAT_KEYS]
        out[6] = [str(x) for x in (refs.ms6.checked_values() or []) if str(x) in MAINSTAT_KEYS]
        return out

    def _current_mainstat_combos_246_for_unit(self, unit_id: int, limit: int = 12) -> List[List[str]]:
        return mainstat_combos_246(self._read_mainstats_from_editor(int(unit_id)), limit)

    def _read_artifact_preferences_from_editor(self, unit_id: int) -> Tuple[Dict[str, List[str]], Dict[str, List[int]]]:
        uid = int(unit_id or 0)
        refs = self._editor_refs(uid)
        artifact_focus: Dict[str, List[str]] = {}
        if refs is not None:
            attr_v = str(refs.art_attr_focus.currentData() or "").upper()
            type_v = str(refs.art_type_focus.currentData() or "").upper()
            if attr_v in ("HP", "ATK", "DEF"):
                artifact_focus["attribute"] = [attr_v]
            if type_v in ("HP", "ATK", "DEF"):
                artifact_focus["type"] = [type_v]
        artifact_substats: Dict[str, List[int]] = {}
        attr_subs = self._artifact_substat_ids_for_unit(int(uid), "attribute")
        type_subs = self._artifact_substat_ids_for_unit(int(uid), "type")
        if attr_subs:
            artifact_substats["attribute"] = [int(x) for x in attr_subs[:2]]
        if type_subs:
            artifact_substats["type"] = [int(x) for x in type_subs[:2]]
        return artifact_focus, artifact_substats

    def _save_rune_pref_entry(self, master_id: int, payload: Dict[str, Any]) -> bool:
        return self._rune_pref_cache.save(int(master_id), dict(payload or {}))

    def _on_load_preferred_runes_for_unit(self, unit_id: int) -> None:
        entry = self._rune_pref_entry_for_unit(int(unit_id))
        if not isinstance(entry, dict):
            return
        refs = self._editor_refs(unit_id)
        if refs is None:
            return
        slot1_ids, slot2_ids, slot3_ids = rune_pref_slot_set_ids(entry)
        if slot1_ids:
            refs.set1.set_checked_ids(slot1_ids)
        if slot2_ids:
            refs.set2.set_checked_ids(slot2_ids)
        if slot3_ids:
            refs.set3.set_checked_ids(slot3_ids)
        self._sync_set_combo_constraints_for_unit(int(unit_id))
        by_slot = rune_pref_mainstats_by_slot(entry)
        if by_slot.get(2):
            refs.ms2.set_checked_values(list(by_slot[2]))
        if by_slot.get(4):
            refs.ms4.set_checked_values(list(by_slot[4]))
        if by_slot.get(6):
            refs.ms6.set_checked_values(list(by_slot[6]))

    def _on_load_preferred_runes_for_all(self) -> None:
        self._ensure_all_editor_pages()
        for unit_id in list(self._unit_editors.keys()):
            self._on_load_preferred_runes_for_unit(int(unit_id))

    def _on_load_preferred_artifacts_for_all(self) -> None:
        self._ensure_all_editor_pages()
        for unit_id in list(self._unit_editors.keys()):
            self._on_load_preferred_artifacts_for_unit(int(unit_id))

    def _on_load_preferred_artifacts_for_unit(self, unit_id: int) -> None:
        uid = int(unit_id or 0)
        if uid <= 0:
            return
        entry = self._rune_pref_entry_for_unit(int(uid))
        if not isinstance(entry, dict):
            return
        artifact_focus, artifact_substats = artifact_pref_from_entry(entry)
        if not (artifact_focus or artifact_substats):
            return
        self._load_artifact_prefs_into_editor(
            int(uid),
            artifact_focus=artifact_focus,
            artifact_substats=artifact_substats,
        )

    def _on_save_preferred_runes_for_unit(self, unit_id: int) -> None:
        uid = int(unit_id or 0)
        if uid <= 0:
            return
        master_id = unit_master_id_for_unit(self._account, uid)
        if master_id <= 0:
            return

        combos = self._read_set_options_from_editor(uid)
        top_set_combos = [list(c) for c in combos[:6]]
        top_set_ids = top_set_ids_from_combos(top_set_combos)
        if not top_set_ids:
            return

        main_by_slot = self._read_mainstats_from_editor(uid)
        main_combos = self._current_mainstat_combos_246_for_unit(uid, limit=12)
        artifact_focus, artifact_substats = self._read_artifact_preferences_from_editor(uid)
        existing = self._rune_pref_entry_for_unit(uid) or {}
        merged_pref_ids = merge_preferred_set_ids(top_set_ids, existing.get("preferred_set_ids") or [])

        unit_label = str(self._unit_label_by_id.get(uid, f"Unit {uid}") or f"Unit {uid}")
        payload: Dict[str, Any] = {
            **unit_pref_metadata(self._account, uid, master_id, unit_label, existing),
            "top_set_ids": list(top_set_ids[:3]),
            "preferred_set_ids": list(merged_pref_ids[:10]),
            "top_set_combos": list(top_set_combos),
            "preferred_set_combos": list(top_set_combos),
            "top_mainstats_by_slot": {
                "2": list(main_by_slot.get(2) or []),
                "4": list(main_by_slot.get(4) or []),
                "6": list(main_by_slot.get(6) or []),
            },
            "top_mainstat_combos_246": list(main_combos),
            "artifact_focus": dict(artifact_focus),
            "artifact_substats": dict(artifact_substats),
        }
        if self._save_rune_pref_entry(master_id=master_id, payload=payload):
            self._show_dialog_status(tr("status.pref_runes_saved", name=unit_label))

    def _on_save_preferred_artifacts_for_unit(self, unit_id: int) -> None:
        uid = int(unit_id or 0)
        if uid <= 0:
            return
        master_id = unit_master_id_for_unit(self._account, uid)
        if master_id <= 0:
            return
        existing = self._rune_pref_entry_for_unit(uid) or {}
        artifact_focus, artifact_substats = self._read_artifact_preferences_from_editor(uid)
        unit_label = str(self._unit_label_by_id.get(uid, f"Unit {uid}") or f"Unit {uid}")
        payload: Dict[str, Any] = {
            **unit_pref_metadata(self._account, uid, master_id, unit_label, existing),
            "artifact_focus": dict(artifact_focus),
            "artifact_substats": dict(artifact_substats),
        }
        unit_label = str(self._unit_label_by_id.get(uid, f"Unit {uid}") or f"Unit {uid}")
        if self._save_rune_pref_entry(master_id=master_id, payload=payload):
            self._show_dialog_status(tr("status.pref_artifacts_saved", name=unit_label))

    def _show_dialog_status(self, text: str, timeout_ms: int = 5000) -> None:
        parent = self.parentWidget()
        if parent is None or not hasattr(parent, "statusBar"):
            return
        try:
            status_bar = parent.statusBar()
            if status_bar is not None:
                status_bar.showMessage(str(text), int(timeout_ms))
        except Exception:
            return

    def _community_status_text_for_unit(self, unit_id: int) -> str:
        uid = int(unit_id or 0)
        if not build_trends_opt_in_enabled():
            return tr("build.community_status_disabled")

        trend = self._community_trend_by_unit.get(int(uid))
        if trend is not None:
            samples = int(max(0, int(getattr(trend, "sample_count", 0) or 0)))
            conf_raw = float(getattr(trend, "confidence", 0.0) or 0.0)
            confidence_pct = int(round(max(0.0, min(1.0, conf_raw)) * 100.0))
            return tr("build.community_status_active", samples=samples, confidence=confidence_pct)

        if int(uid) in self._community_trend_missing_units and bool(self._community_trends_loaded):
            return tr("build.community_status_none")
        return tr("build.community_status_not_loaded")

    def _refresh_community_status_label(self, unit_id: int) -> None:
        widget = self._unit_editors.get(int(unit_id or 0))
        if widget is not None:
            widget.set_community_status(self._community_status_text_for_unit(int(unit_id)))

    def _refresh_all_community_status_labels(self) -> None:
        for uid in list(self._unit_editors.keys()):
            self._refresh_community_status_label(int(uid))

    def _community_trend_for_unit(self, unit_id: int) -> BuildPreferenceTrend | None:
        uid = int(unit_id or 0)
        if uid <= 0:
            return None
        master_id = unit_master_id_for_unit(self._account, int(uid))
        if master_id <= 0:
            return None
        trends_by_mid = fetch_build_preference_trends(
            mode=self.mode,
            unit_master_ids=[int(master_id)],
        )
        return trends_by_mid.get(int(master_id))

    def _load_community_trend_into_editor(self, unit_id: int, trend: BuildPreferenceTrend) -> bool:
        uid = int(unit_id or 0)
        if uid <= 0:
            return False

        self._ensure_editor_page(int(uid))
        refs = self._editor_refs(uid)
        if refs is None:
            return False

        slot1_ids, slot2_ids, slot3_ids = set_slots_from_community_trend(trend, build_trends_set_combo_limit())
        if slot1_ids:
            refs.set1.set_checked_ids(slot1_ids)
        if slot2_ids:
            refs.set2.set_checked_ids(slot2_ids)
        if slot3_ids:
            refs.set3.set_checked_ids(slot3_ids)
        self._sync_set_combo_constraints_for_unit(int(uid))

        by_slot = mainstats_from_community_trend(trend, build_trends_mainstat_limit())
        if by_slot.get(2):
            refs.ms2.set_checked_values([str(x) for x in list(by_slot.get(2) or [])])
        if by_slot.get(4):
            refs.ms4.set_checked_values([str(x) for x in list(by_slot.get(4) or [])])
        if by_slot.get(6):
            refs.ms6.set_checked_values([str(x) for x in list(by_slot.get(6) or [])])

        trend_art_focus, trend_art_subs = artifact_prefs_from_trend(trend, build_trends_artifact_substat_limit())
        artifact_signal = self._load_artifact_prefs_into_editor(
            int(uid),
            artifact_focus=trend_art_focus,
            artifact_substats=trend_art_subs,
        )

        has_signal = bool(
            slot1_ids
            or slot2_ids
            or slot3_ids
            or by_slot.get(2)
            or by_slot.get(4)
            or by_slot.get(6)
            or artifact_signal
        )
        return has_signal

    def _mark_missing_community_trend(self, unit_id: int) -> None:
        self._community_trend_by_unit.pop(int(unit_id), None)
        self._community_trend_missing_units.add(int(unit_id))
        self._refresh_community_status_label(int(unit_id))

    def _apply_loaded_community_trend(self, unit_id: int, trend: "BuildPreferenceTrend") -> bool:
        applied = self._load_community_trend_into_editor(int(unit_id), trend)
        if applied:
            self._community_trend_by_unit[int(unit_id)] = trend
            self._community_trend_missing_units.discard(int(unit_id))
        else:
            self._mark_missing_community_trend(int(unit_id))
            return False
        self._refresh_community_status_label(int(unit_id))
        return True

    def _on_load_community_trends_for_unit(self, unit_id: int) -> None:
        uid = int(unit_id or 0)
        if uid <= 0:
            return
        if not build_trends_opt_in_enabled():
            self._show_dialog_status(tr("status.community_trends_disabled"))
            self._refresh_community_status_label(int(uid))
            return

        self._ensure_editor_page(int(uid))
        self._community_trends_loaded = True

        trend: BuildPreferenceTrend | None = None
        try:
            trend = self._community_trend_for_unit(int(uid))
        except Exception:
            trend = None

        if trend is None:
            self._mark_missing_community_trend(int(uid))
            self._show_dialog_status(tr("status.community_trends_none"))
            return

        applied = self._apply_loaded_community_trend(int(uid), trend)
        self._show_dialog_status(
            tr("status.community_trends_loaded", count=1) if applied else tr("status.community_trends_none")
        )

    def _on_load_community_trends_for_all(self) -> None:
        if not build_trends_opt_in_enabled():
            self._show_dialog_status(tr("status.community_trends_disabled"))
            self._refresh_all_community_status_labels()
            return

        self._ensure_all_editor_pages()
        unit_ids = [int(uid) for uid in list(self._unit_editors.keys()) if int(uid) > 0]
        if not unit_ids:
            return

        unit_master_by_uid: Dict[int, int] = {}
        for uid in unit_ids:
            master_id = unit_master_id_for_unit(self._account, int(uid))
            if master_id > 0:
                unit_master_by_uid[int(uid)] = int(master_id)
        if not unit_master_by_uid:
            self._show_dialog_status(tr("status.community_trends_none"))
            return

        trends_by_mid: Dict[int, BuildPreferenceTrend] = {}
        self._community_trends_loaded = True
        try:
            trends_by_mid = fetch_build_preference_trends(
                mode=self.mode,
                unit_master_ids=list(set(unit_master_by_uid.values())),
            )
        except Exception:
            trends_by_mid = {}

        applied_count = 0
        for uid in unit_ids:
            mid = int(unit_master_by_uid.get(int(uid), 0) or 0)
            trend = trends_by_mid.get(int(mid))
            if trend is None:
                self._mark_missing_community_trend(int(uid))
                continue
            if self._apply_loaded_community_trend(int(uid), trend):
                applied_count += 1

        if applied_count > 0:
            self._show_dialog_status(tr("status.community_trends_loaded", count=applied_count))
        else:
            self._show_dialog_status(tr("status.community_trends_none"))

    def _load_build_into_editor(self, unit_id: int, build: Build) -> None:
        uid = int(unit_id or 0)
        if uid <= 0:
            return
        self._ensure_editor_page(int(uid))
        refs = self._editor_refs(uid)
        if refs is None:
            return

        slot1_ids, slot2_ids, slot3_ids = parse_set_options_to_slot_ids(list(build.set_options or []))
        refs.set1.set_checked_ids(list(slot1_ids))
        refs.set2.set_checked_ids(list(slot2_ids))
        refs.set3.set_checked_ids(list(slot3_ids))
        self._sync_set_combo_constraints_for_unit(int(uid))

        mainstats = dict(getattr(build, "mainstats", {}) or {})
        ms2_vals = list(mainstats.get(2) or mainstats.get("2") or [])
        ms4_vals = list(mainstats.get(4) or mainstats.get("4") or [])
        ms6_vals = list(mainstats.get(6) or mainstats.get("6") or [])
        refs.ms2.set_checked_values([str(x) for x in ms2_vals if str(x) in MAINSTAT_KEYS])
        refs.ms4.set_checked_values([str(x) for x in ms4_vals if str(x) in MAINSTAT_KEYS])
        refs.ms6.set_checked_values([str(x) for x in ms6_vals if str(x) in MAINSTAT_KEYS])

        artifact_focus = dict(getattr(build, "artifact_focus", {}) or {})
        attr_focus_vals = [str(x).upper() for x in (artifact_focus.get("attribute") or []) if str(x)]
        type_focus_vals = [str(x).upper() for x in (artifact_focus.get("type") or []) if str(x)]
        for cmb in (refs.art_attr_focus, refs.art_type_focus):
            idx_any = cmb.findData("")
            if idx_any >= 0:
                cmb.setCurrentIndex(int(idx_any))
        if attr_focus_vals:
            set_art_focus_combo_value(refs.art_attr_focus, attr_focus_vals[0])
        if type_focus_vals:
            set_art_focus_combo_value(refs.art_type_focus, type_focus_vals[0])

        artifact_substats = dict(getattr(build, "artifact_substats", {}) or {})
        attr_subs = [int(x) for x in (artifact_substats.get("attribute") or []) if int(x) > 0][:2]
        type_subs = [int(x) for x in (artifact_substats.get("type") or []) if int(x) > 0][:2]
        for cmb in (refs.art_attr_sub1, refs.art_attr_sub2, refs.art_type_sub1, refs.art_type_sub2):
            idx_any = cmb.findData(0)
            if idx_any >= 0:
                cmb.setCurrentIndex(int(idx_any))
        if len(attr_subs) >= 1:
            set_art_sub_combo_value(refs.art_attr_sub1, int(attr_subs[0]))
        if len(attr_subs) >= 2:
            set_art_sub_combo_value(refs.art_attr_sub2, int(attr_subs[1]))
        if len(type_subs) >= 1:
            set_art_sub_combo_value(refs.art_type_sub1, int(type_subs[0]))
        if len(type_subs) >= 2:
            set_art_sub_combo_value(refs.art_type_sub2, int(type_subs[1]))

        current_min = dict(getattr(build, "min_stats", {}) or {})
        base_stats = unit_base_stats_for_min(self._account, int(uid))
        min_mode = min_mode_for_build(current_min)
        idx = refs.min_mode.findData(str(min_mode))
        if idx >= 0:
            refs.min_mode.setCurrentIndex(int(idx))
        for stat_key, spin in refs.all_min_spins().items():
            spin.setValue(int(min_value_for_build(current_min, str(stat_key), str(min_mode), base_stats)))

        current_weights = dict(getattr(build, "stat_weights", {}) or {})
        for stat_key, slider in refs.all_stat_weight_sliders().items():
            val = float(current_weights.get(str(stat_key), 0.5))
            slider.setValue(int(round(val * 10)))

        target_tick = int(getattr(build, "spd_tick", 0) or 0)
        if self._order_section is not None:
            self._order_section.set_spd_tick_for_unit(int(uid), target_tick)

    def _on_restore_saved_preset(self) -> None:
        snap = self._initial_snapshot
        self._ensure_all_editor_pages()
        for unit_id, build in snap.build_by_unit.items():
            self._load_build_into_editor(int(unit_id), copy.deepcopy(build))
        self._restore_unit_list_uid_order(list(snap.unit_list_order))
        self._community_trends_loaded = False
        self._community_trend_by_unit = {}
        self._community_trend_missing_units = set()
        self._refresh_all_community_status_labels()

        if self._order_section is not None:
            self._order_section.restore_state(
                snap.team_speed_lead_by_team,
                snap.team_speed_lead_pct_by_team,
                snap.team_effect_control_state,
            )

        self._loaded_current_runes = False
        self._loaded_current_runes_snapshot = {}

    def _on_load_current_runes(self) -> None:
        """Load currently equipped rune sets and mainstats for all units."""
        if not self._account:
            return
        # This action updates all units, so ensure all editors exist first.
        self._ensure_all_editor_pages()
        rune_mode = rune_mode_for_mode(self.mode)
        for unit_id in list(self._unit_editors.keys()):
            refs = self._editor_refs(unit_id)
            if refs is None:
                continue
            equipped = self._account.equipped_runes_for(int(unit_id), rune_mode)
            if not equipped:
                continue
            slot1_ids, slot2_ids, slot3_ids = slot_ids_from_equipped_runes(equipped)
            refs.set1.set_checked_ids(slot1_ids)
            refs.set2.set_checked_ids(slot2_ids)
            refs.set3.set_checked_ids(slot3_ids)
            self._sync_set_combo_constraints_for_unit(int(unit_id))
            for r in equipped:
                slot = int(r.slot_no or 0)
                if slot not in (2, 4, 6):
                    continue
                eff_id = int(r.pri_eff[0] or 0) if r.pri_eff else 0
                ms_key = EFFECT_ID_TO_MAINSTAT_KEY.get(eff_id, "")
                if not ms_key:
                    continue
                ms_cmb = {2: refs.ms2, 4: refs.ms4, 6: refs.ms6}.get(slot)
                if ms_cmb:
                    ms_cmb.set_checked_values([ms_key])
        self._loaded_current_runes = True
        self._loaded_current_runes_snapshot = capture_current_runes_snapshot(self._account, list(self._unit_rows_by_uid.keys()), rune_mode)


    def loaded_current_runes_snapshot(self) -> Dict[str, Any] | None:
        if not bool(self._loaded_current_runes):
            return None
        snap = dict(self._loaded_current_runes_snapshot or {})
        if not snap:
            return None
        return sanitize_rune_snapshot(snap)

    def _optimize_order_by_unit(self) -> Dict[int, int]:
        source = self._opt_order_list or self._unit_list
        if not source:
            return {}
        out: Dict[int, int] = {}
        for idx in range(source.count()):
            it = source.item(idx)
            uid = int(it.data(Qt.UserRole) or 0) if it else 0
            if uid:
                out[uid] = idx + 1
        return out

    def team_order_by_lists(self) -> List[List[int]]:
        return self._order_section.team_order_by_lists() if self._order_section else []

    def team_speed_lead_by_lists(self) -> List[int]:
        return self._order_section.team_speed_lead_by_lists() if self._order_section else []

    def team_speed_lead_pct_by_lists(self) -> List[int]:
        return self._order_section.team_speed_lead_pct_by_lists() if self._order_section else []

    def team_turn_effects_by_lists(self) -> List[Dict[int, Dict[str, Any]]]:
        return self._order_section.team_turn_effects_by_lists() if self._order_section else []

    def _validate_order_tick_plausibility(self) -> None:
        if not bool(self._persist_order_fields):
            return
        if self._order_section is None:
            return
        team_orders = self._order_section.team_order_by_lists()
        tick_by_uid = self._order_section.spd_tick_by_unit()
        effect_teams = self._order_section.team_turn_effects_by_lists()
        order_team_titles = [self._order_section.team_title(i) for i in range(len(team_orders))]
        validate_order_tick_plausibility(
            team_orders, tick_by_uid, effect_teams, self.mode, self._unit_label_by_id, order_team_titles
        )

    def _artifact_substat_ids_for_unit(self, unit_id: int, kind: str) -> List[int]:
        refs = self._editor_refs(int(unit_id))
        if refs is None:
            return []
        if str(kind) == "attribute":
            c1 = refs.art_attr_sub1
            c2 = refs.art_attr_sub2
        else:
            c1 = refs.art_type_sub1
            c2 = refs.art_type_sub2
        vals: List[int] = []
        seen: Set[int] = set()
        for cmb in (c1, c2):
            if cmb is None:
                continue
            eid = int(cmb.currentData() or 0)
            if eid <= 0 or eid in seen:
                continue
            seen.add(eid)
            vals.append(eid)
            if len(vals) >= 2:
                break
        return vals

    def _read_stat_weights_from_editor(self, unit_id: int) -> Dict[str, float]:
        refs = self._editor_refs(int(unit_id))
        if refs is None:
            return {}
        result = {}
        for key, slider in refs.all_stat_weight_sliders().items():
            val = round(int(slider.value()) / 10.0, 1)
            if val != 0.5:
                result[str(key)] = val
        return result

    def _read_min_stats_from_editor(self, unit_id: int) -> Dict[str, int]:
        refs = self._editor_refs(int(unit_id))
        min_mode = str(refs.min_mode.currentData() or "with_base") if refs else "with_base"
        base_stats = unit_base_stats_for_min(self._account, int(unit_id))
        raw = {
            "SPD": refs.min_spd.value() if refs else 0,
            "HP": refs.min_hp.value() if refs else 0,
            "ATK": refs.min_atk.value() if refs else 0,
            "DEF": refs.min_def.value() if refs else 0,
            "CR": refs.min_cr.value() if refs else 0,
            "CD": refs.min_cd.value() if refs else 0,
            "RES": refs.min_res.value() if refs else 0,
            "ACC": refs.min_acc.value() if refs else 0,
        }
        return build_min_stats(min_mode, base_stats, raw)

    def _read_build_from_editor(
        self, unit_id: int, optimize_order: int, turn_order: int, spd_tick: int
    ) -> Build:
        refs = self._editor_refs(int(unit_id))
        normalized_options = self._read_set_options_from_editor(int(unit_id))
        if not normalized_options and refs is not None:
            has_sel = (
                bool(refs.set1.checked_ids())
                or bool(refs.set2.checked_ids())
                or (self._is_set3_allowed_for_unit(int(unit_id)) and bool(refs.set3.checked_ids()))
            )
            if has_sel:
                unit_label = self._unit_label_by_id.get(unit_id, str(unit_id))
                raise ValueError(tr("val.set_invalid", unit=unit_label))
        by_slot = self._read_mainstats_from_editor(int(unit_id))
        artifact_focus, artifact_substats = self._read_artifact_preferences_from_editor(int(unit_id))
        min_stats = self._read_min_stats_from_editor(int(unit_id))
        stat_weights = self._read_stat_weights_from_editor(int(unit_id))
        return Build(
            id="default",
            name="Default",
            enabled=True,
            priority=1,
            optimize_order=int(optimize_order),
            turn_order=int(turn_order),
            spd_tick=int(spd_tick),
            set_options=set_id_combos_to_names(normalized_options),
            mainstats={s: v for s, v in by_slot.items() if v},
            min_stats=min_stats,
            stat_weights=stat_weights,
            artifact_focus=artifact_focus,
            artifact_substats=artifact_substats,
        )

    def apply_to_store(self) -> None:
        self._ensure_all_editor_pages()
        self._validate_order_tick_plausibility()
        optimize_order_by_uid = self._optimize_order_by_unit()
        team_turn_order_by_uid = self._order_section.turn_order_by_unit() if (self._persist_order_fields and self._order_section) else {}
        team_spd_tick_by_uid = self._order_section.spd_tick_by_unit() if (self._persist_order_fields and self._order_section) else {}

        for unit_id in self._unit_editors.keys():
            optimize_order = int(optimize_order_by_uid.get(unit_id, 0) or 0)
            existing_builds = self.preset_store.get_unit_builds(self.mode, int(unit_id))
            existing_build = existing_builds[0] if existing_builds else Build.default_any()
            turn_order = int(getattr(existing_build, "turn_order", 0) or 0)
            spd_tick = int(getattr(existing_build, "spd_tick", 0) or 0)
            if self._persist_order_fields:
                turn_order = int(team_turn_order_by_uid.get(unit_id, turn_order) or 0)
                spd_tick = int(team_spd_tick_by_uid.get(unit_id, spd_tick) or 0)
            b = self._read_build_from_editor(int(unit_id), optimize_order, turn_order, spd_tick)
            self.preset_store.set_unit_builds(self.mode, unit_id, [b])
