from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.domain.presets import Build, BuildStore
from app.domain.speed_ticks import (
    LEO_LOW_SPD_TICK,
    allowed_spd_ticks,
    max_spd_for_tick,
    min_spd_for_tick,
)
from app.i18n import tr
from app.ui import theme as _theme
from app.ui.dpi import dp
from app.ui.widgets.selection_combos import _NoScrollComboBox


class SingleTeamOrderEditor(QWidget):
    """
    Team-centric replacement for TeamOrderSection — styled like the optimizer result dialog.

    Layout:
      LEFT  │ plain nav list — one entry per team
      RIGHT │ portrait card bar (TeamIconBar) + DnD list + collapsible advanced section

    Public API is identical to TeamOrderSection so BuildDialog only needs an import swap.
    """

    unit_selected: Signal = Signal(object)  # uid (Python int, may exceed 32-bit)

    def __init__(
        self,
        mode: str,
        order_teams: List[List[Tuple[int, str]]] | None,
        unit_rows: List[Tuple[int, str]],
        team_size: int,
        order_team_titles: List[str],
        order_turn_effects: List[Dict[int, Dict[str, Any]]],
        order_turn_effect_capabilities: Dict[int, Dict[str, Any]],
        order_speed_leaders: List[int],
        order_speed_lead_pct_by_unit: Dict[int, int],
        order_speed_lead_pct_by_team: List[int],
        show_turn_effect_controls: bool,
        show_speed_lead_controls: bool,
        preset_store: BuildStore,
        unit_icon_fn: Callable[[int], QIcon],
        skill_icons_dir: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.mode = mode
        self._preset_store = preset_store
        self._unit_icon_fn = unit_icon_fn
        self._skill_icons_dir = skill_icons_dir
        self._team_size = max(1, int(team_size))
        self._unit_rows = list(unit_rows)
        self._show_turn_effect_controls = bool(show_turn_effect_controls)
        self._show_speed_lead_controls = bool(show_speed_lead_controls)

        self._order_teams: List[List[Tuple[int, str]]] | None = None
        if order_teams:
            self._order_teams = [
                [(int(uid), str(lbl)) for uid, lbl in team if int(uid) > 0]
                for team in order_teams
                if team
            ]

        self._order_team_titles: List[str] = [str(x) for x in order_team_titles]

        self._order_turn_effects: List[Dict[int, Dict[str, Any]]] = []
        for team_cfg in order_turn_effects:
            cleaned: Dict[int, Dict[str, Any]] = {}
            for uid, cfg in (team_cfg or {}).items():
                ui = int(uid or 0)
                if ui > 0:
                    cleaned[ui] = dict(cfg or {})
            self._order_turn_effects.append(cleaned)

        self._order_turn_effect_capabilities: Dict[int, Dict[str, Any]] = {
            int(uid): dict(cfg or {})
            for uid, cfg in dict(order_turn_effect_capabilities).items()
            if int(uid or 0) > 0
        }
        self._order_speed_leaders: List[int] = [int(uid or 0) for uid in order_speed_leaders]
        self._order_speed_lead_pct_by_unit: Dict[int, int] = {
            int(uid): int(pct or 0)
            for uid, pct in dict(order_speed_lead_pct_by_unit).items()
            if int(uid or 0) > 0 and int(pct or 0) > 0
        }
        self._order_speed_lead_pct_by_team: List[int] = [int(v or 0) for v in order_speed_lead_pct_by_team]

        # State (same dict keys as TeamOrderSection for full API compatibility)
        self._team_order_lists: List[QListWidget] = []
        self._team_spd_tick_combo_by_unit: Dict[int, List[QComboBox]] = {}
        self._syncing_team_spd_tick = False
        self._team_effect_controls: Dict[Tuple[int, int], Tuple[QCheckBox, QCheckBox, QSpinBox]] = {}
        self._team_speed_lead_combo_by_team: Dict[int, QComboBox] = {}
        self._team_speed_lead_pct_spin_by_team: Dict[int, QSpinBox] = {}
        self._syncing_focus_selection = False
        self._syncing_nav = False
        self._active_team_index: int = 0

        # Team list
        if self._order_teams:
            teams: List[List[Tuple[int, str]]] = [list(t) for t in self._order_teams if t]
        else:
            teams = [
                self._unit_rows[i : i + self._team_size]
                for i in range(0, len(self._unit_rows), self._team_size)
                if self._unit_rows[i : i + self._team_size]
            ]
        self._teams = teams

        # Build all DnD lists per team
        self._team_list_stack = QStackedWidget()
        for t_idx, team_units in enumerate(teams):
            lw = self._build_team_list(t_idx, team_units)
            self._team_list_stack.addWidget(lw)

        # ── Layout ───────────────────────────────────────────────────────────
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(dp(8))

        # Left: team navigation list
        self._nav_list = self._build_nav_list(teams)
        outer.addWidget(self._nav_list)

        # Right: DnD list → advanced
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(dp(6))

        has_advanced = self._show_speed_lead_controls or self._show_turn_effect_controls
        self._speed_lead_stack: QStackedWidget | None = None
        self._turn_effect_stack: QStackedWidget | None = None
        if has_advanced:
            toggle_btn, content = self._build_advanced_panel(teams)
            top_split = QHBoxLayout()
            top_split.setContentsMargins(0, 0, 0, 0)
            top_split.setSpacing(dp(8))
            top_split.addWidget(self._team_list_stack, 1)

            advanced_col_widget = QWidget()
            advanced_col = QVBoxLayout(advanced_col_widget)
            advanced_col.setContentsMargins(0, 0, 0, 0)
            advanced_col.setSpacing(dp(4))
            advanced_col.addWidget(toggle_btn, 0, Qt.AlignTop)
            advanced_col.addWidget(content, 0, Qt.AlignTop)
            advanced_col.addStretch(1)
            top_split.addWidget(advanced_col_widget, 0, Qt.AlignTop)

            right.addLayout(top_split, 1)
        else:
            right.addWidget(self._team_list_stack, 1)

        outer.addLayout(right, 1)

        if teams:
            self._switch_active_team(0)

    # ── Public API (identical to TeamOrderSection) ────────────────────────────

    def team_order_by_lists(self) -> List[List[int]]:
        out: List[List[int]] = []
        for lw in self._team_order_lists:
            row: List[int] = []
            for idx in range(lw.count()):
                it = lw.item(idx)
                uid = int(it.data(Qt.UserRole) or 0) if it else 0
                if uid > 0:
                    row.append(uid)
            out.append(row)
        return out

    def turn_order_by_unit(self) -> Dict[int, int]:
        out: Dict[int, int] = {}
        for lw in self._team_order_lists:
            for idx in range(lw.count()):
                it = lw.item(idx)
                uid = int(it.data(Qt.UserRole) or 0)
                if uid:
                    out[uid] = idx + 1
        return out

    def spd_tick_by_unit(self) -> Dict[int, int]:
        out: Dict[int, int] = {}
        for uid, cmb_list in self._team_spd_tick_combo_by_unit.items():
            if cmb_list:
                out[int(uid)] = int(cmb_list[0].currentData() or 0)
        return out

    def team_speed_lead_by_lists(self) -> List[int]:
        out: List[int] = []
        for t, _lw in enumerate(self._team_order_lists):
            cmb = self._team_speed_lead_combo_by_team.get(int(t))
            out.append(int(cmb.currentData() or 0) if cmb is not None else 0)
        return out

    def team_speed_lead_pct_by_lists(self) -> List[int]:
        out: List[int] = []
        for t, _lw in enumerate(self._team_order_lists):
            spin = self._team_speed_lead_pct_spin_by_team.get(int(t))
            out.append(int(spin.value()) if spin is not None else 0)
        return out

    def team_turn_effects_by_lists(self) -> List[Dict[int, Dict[str, Any]]]:
        out: List[Dict[int, Dict[str, Any]]] = []
        for t, lw in enumerate(self._team_order_lists):
            row_cfg: Dict[int, Dict[str, Any]] = {}
            for idx in range(lw.count()):
                it = lw.item(idx)
                uid = int(it.data(Qt.UserRole) or 0) if it else 0
                if uid <= 0:
                    continue
                controls = self._team_effect_controls.get((int(t), int(uid)))
                if not controls:
                    continue
                spd_buff_chk, atb_boost_chk, atb_boost_spin = controls
                atb_boost_pct = float(atb_boost_spin.value()) if bool(atb_boost_chk.isChecked()) else 0.0
                applies_spd_buff = bool(spd_buff_chk.isChecked())
                if not applies_spd_buff and atb_boost_pct <= 0.0:
                    continue
                row_cfg[int(uid)] = {
                    "applies_spd_buff": bool(applies_spd_buff),
                    "atb_boost_pct": float(atb_boost_pct),
                    "include_caster": True,
                }
            out.append(row_cfg)
        return out

    def team_title(self, team_index: int) -> str:
        if 0 <= int(team_index) < len(self._order_team_titles):
            title = str(self._order_team_titles[int(team_index)] or "").strip()
            if title:
                return title
        return f"Team {int(team_index) + 1}"

    def capture_speed_lead_uid_state(self) -> Dict[int, int]:
        return {int(t): int(cmb.currentData() or 0) for t, cmb in self._team_speed_lead_combo_by_team.items()}

    def capture_speed_lead_pct_state(self) -> Dict[int, int]:
        return {int(t): int(spin.value() or 0) for t, spin in self._team_speed_lead_pct_spin_by_team.items()}

    def capture_effect_control_state(self) -> Dict[Tuple[int, int], Dict[str, Any]]:
        out: Dict[Tuple[int, int], Dict[str, Any]] = {}
        for key, controls in self._team_effect_controls.items():
            team_idx, uid = int(key[0]), int(key[1])
            spd_chk, atb_chk, atb_spin = controls
            out[(team_idx, uid)] = {
                "applies_spd_buff": bool(spd_chk.isChecked()),
                "atb_boost_enabled": bool(atb_chk.isChecked()),
                "atb_boost_pct": int(atb_spin.value() or 0),
            }
        return out

    def set_spd_tick_for_unit(self, uid: int, tick: int) -> None:
        for tick_cmb in list(self._team_spd_tick_combo_by_unit.get(int(uid), []) or []):
            idx = tick_cmb.findData(int(tick))
            tick_cmb.setCurrentIndex(int(idx) if idx >= 0 else 0)

    def restore_state(
        self,
        team_speed_lead_by_team: Dict[int, int],
        team_speed_lead_pct_by_team: Dict[int, int],
        team_effect_control_state: Dict[Tuple[int, int], Dict[str, Any]],
    ) -> None:
        for team_idx, cmb in self._team_speed_lead_combo_by_team.items():
            target_uid = int(team_speed_lead_by_team.get(int(team_idx), 0) or 0)
            idx = cmb.findData(int(target_uid))
            cmb.setCurrentIndex(int(idx) if idx >= 0 else 0)
        for team_idx, spin in self._team_speed_lead_pct_spin_by_team.items():
            val = int(team_speed_lead_pct_by_team.get(int(team_idx), int(spin.value())) or 0)
            spin.setValue(max(int(spin.minimum()), min(int(spin.maximum()), int(val))))
        for key, controls in self._team_effect_controls.items():
            team_idx, uid = int(key[0]), int(key[1])
            raw = dict(team_effect_control_state.get((team_idx, uid), {}) or {})
            spd_chk, atb_chk, atb_spin = controls
            spd_chk.setChecked(bool(raw.get("applies_spd_buff", False)))
            atb_chk.setChecked(bool(raw.get("atb_boost_enabled", False)))
            atb_val = int(raw.get("atb_boost_pct", 0) or 0)
            atb_spin.setValue(max(int(atb_spin.minimum()), min(int(atb_spin.maximum()), int(atb_val))))

    # ── Team switching ────────────────────────────────────────────────────────

    def _switch_active_team(self, team_index: int) -> None:
        idx = max(0, min(len(self._team_order_lists) - 1, int(team_index)))
        self._active_team_index = idx
        self._team_list_stack.setCurrentIndex(idx)
        if self._speed_lead_stack is not None:
            self._speed_lead_stack.setCurrentIndex(idx)
        if self._turn_effect_stack is not None:
            self._turn_effect_stack.setCurrentIndex(idx)
        if not self._syncing_nav and self._nav_list.currentRow() != idx:
            self._syncing_nav = True
            try:
                self._nav_list.setCurrentRow(idx)
            finally:
                self._syncing_nav = False

    def _on_nav_row_changed(self, row: int) -> None:
        if self._syncing_nav or row < 0 or row >= len(self._team_order_lists):
            return
        if self._active_team_index != row:
            self._switch_active_team(row)

    # ── UI building ───────────────────────────────────────────────────────────

    def _build_nav_list(self, teams: List[List[Tuple[int, str]]]) -> QListWidget:
        """Left navigation: plain QListWidget — one item per team, matching optimizer style."""
        nav = QListWidget()
        nav.setFixedWidth(dp(210))
        nav.setIconSize(QSize(dp(32), dp(32)))

        for t_idx, team_units in enumerate(teams):
            title = self.team_title(t_idx)
            item = QListWidgetItem(title)
            # Use first unit's icon as a team icon hint
            if team_units:
                icon = self._unit_icon_fn(team_units[0][0])
                if not icon.isNull():
                    item.setIcon(icon)
            nav.addItem(item)

        nav.currentRowChanged.connect(self._on_nav_row_changed)
        return nav

    def _build_advanced_panel(
        self, teams: List[List[Tuple[int, str]]]
    ) -> Tuple[QPushButton, QWidget]:
        """Returns (toggle_button, content_widget). Content is hidden by default."""
        c = _theme.C
        toggle_btn = QPushButton("▶  Erweitert")
        toggle_btn.setCheckable(True)
        toggle_btn.setChecked(False)
        toggle_btn.setStyleSheet(
            "QPushButton { text-align: left; padding: 3px 6px; border: none;"
            f" background: transparent; color: {c['text_dim']}; font-size: {dp(11)}px; }}"
            f"QPushButton:hover {{ color: {c['text']}; }}"
            f"QPushButton:checked {{ color: {c['text']}; }}"
        )

        content = QWidget()
        content.setVisible(False)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, dp(2), 0, 0)
        content_layout.setSpacing(dp(6))

        if self._show_speed_lead_controls:
            self._speed_lead_stack = QStackedWidget()
            for t_idx, team_units in enumerate(teams):
                page = self._build_speed_lead_page(t_idx, team_units)
                self._speed_lead_stack.addWidget(page)
            content_layout.addWidget(self._speed_lead_stack)

        if self._show_turn_effect_controls:
            self._turn_effect_stack = QStackedWidget()
            for t_idx, team_units in enumerate(teams):
                page = self._build_turn_effects_page(t_idx, team_units)
                self._turn_effect_stack.addWidget(page)
            content_layout.addWidget(self._turn_effect_stack)

        def _on_toggle(checked: bool) -> None:
            content.setVisible(bool(checked))
            toggle_btn.setText(("▼  " if checked else "▶  ") + "Erweitert")

        toggle_btn.toggled.connect(_on_toggle)
        return toggle_btn, content

    def _build_speed_lead_page(
        self, team_index: int, team_units: List[Tuple[int, str]]
    ) -> QWidget:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(dp(6))

        row.addWidget(QLabel("SPD Lead"))

        cmb = _NoScrollComboBox()
        cmb.setMinimumWidth(dp(180))
        cmb.addItem("-", 0)
        for uid, label in team_units:
            pct = int(self._order_speed_lead_pct_by_unit.get(int(uid), 0) or 0)
            if pct <= 0:
                continue
            cmb.addItem(f"{label} (+{pct}%)", int(uid))
        preferred_uid = (
            int(self._order_speed_leaders[int(team_index)])
            if int(team_index) < len(self._order_speed_leaders)
            else 0
        )
        idx = cmb.findData(int(preferred_uid))
        if idx < 0 and cmb.count() > 1:
            idx = 1
        cmb.setCurrentIndex(max(0, idx))
        cmb.setEnabled(bool(cmb.count() > 1))
        row.addWidget(cmb)

        pct_spin = QSpinBox()
        pct_spin.setMinimum(0)
        pct_spin.setMaximum(100)
        pct_spin.setSuffix("%")
        pct_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        pct_spin.setReadOnly(True)
        pct_spin.setMaximumWidth(dp(64))
        preferred_pct = (
            int(self._order_speed_lead_pct_by_team[int(team_index)])
            if int(team_index) < len(self._order_speed_lead_pct_by_team)
            else 0
        )
        if preferred_pct <= 0:
            selected_uid = int(cmb.currentData() or 0)
            preferred_pct = int(self._order_speed_lead_pct_by_unit.get(int(selected_uid), 0) or 0)
        pct_spin.setValue(max(0, min(100, int(preferred_pct))))
        row.addWidget(pct_spin)
        row.addStretch(1)

        def _sync_pct(_idx: int, _cmb: QComboBox = cmb, _spin: QSpinBox = pct_spin) -> None:
            sel_uid = int(_cmb.currentData() or 0)
            known_pct = int(self._order_speed_lead_pct_by_unit.get(int(sel_uid), 0) or 0)
            _spin.setValue(max(0, min(100, int(known_pct))))

        cmb.currentIndexChanged.connect(_sync_pct)
        self._team_speed_lead_combo_by_team[int(team_index)] = cmb
        self._team_speed_lead_pct_spin_by_team[int(team_index)] = pct_spin
        return page

    def _build_turn_effects_page(
        self, team_idx: int, team_units: List[Tuple[int, str]]
    ) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dp(3))

        sorted_units = self._sorted_team_units(team_units)
        has_any = False
        for uid, label, _spd_tick, _min_spd in sorted_units:
            capability_cfg = dict(self._order_turn_effect_capabilities.get(int(uid), {}) or {})
            can_spd_buff = bool(capability_cfg.get("has_spd_buff", False))
            can_atb_boost = bool(capability_cfg.get("has_atb_boost", False))
            if not can_spd_buff and not can_atb_boost:
                continue

            team_effect_cfg = (
                dict(self._order_turn_effects[team_idx])
                if team_idx < len(self._order_turn_effects)
                else {}
            )
            effect_cfg = dict(team_effect_cfg.get(int(uid), {}) or {})
            effect_spd_buff = bool(effect_cfg.get("applies_spd_buff", False))
            effect_atb_boost_pct = int(float(effect_cfg.get("atb_boost_pct", 0.0) or 0.0))
            max_atb_boost_pct = int(capability_cfg.get("max_atb_boost_pct", 0) or 0) or 100
            spd_buff_icon_file = str(capability_cfg.get("spd_buff_skill_icon", "") or "")
            atb_boost_icon_file = str(capability_cfg.get("atb_boost_skill_icon", "") or "")

            unit_row = QHBoxLayout()
            unit_row.setSpacing(dp(4))
            icon_lbl = QLabel()
            icon = self._unit_icon_fn(uid)
            if not icon.isNull():
                icon_lbl.setPixmap(icon.pixmap(dp(22), dp(22)))
            unit_row.addWidget(icon_lbl)
            unit_row.addWidget(QLabel(str(label)), 1)

            spd_buff_chk, atb_boost_chk, atb_boost_spin = self._create_turn_effect_controls(
                int(team_idx), int(uid),
                effect_spd_buff, can_spd_buff, spd_buff_icon_file,
                effect_atb_boost_pct, can_atb_boost, atb_boost_icon_file,
                max_atb_boost_pct,
            )
            if can_spd_buff:
                unit_row.addWidget(spd_buff_chk)
            if can_atb_boost:
                unit_row.addWidget(atb_boost_chk)
                unit_row.addWidget(atb_boost_spin)

            layout.addLayout(unit_row)
            has_any = True

        if not has_any:
            layout.addWidget(QLabel("–"))

        return page

    # ── Private: DnD list ─────────────────────────────────────────────────────

    def _sorted_team_units(
        self, team_units: List[Tuple[int, str]]
    ) -> List[Tuple[int, str, int, int]]:
        sortable: List[Tuple[int, int, int, str, int, int]] = []
        for pos, (uid, label) in enumerate(team_units):
            builds = self._preset_store.get_unit_builds(self.mode, uid)
            b0 = builds[0] if builds else Build.default_any()
            turn = int(getattr(b0, "turn_order", 0) or 0)
            key = int(pos) if self._order_teams is not None else (turn if turn > 0 else 999)
            spd_tick = int(getattr(b0, "spd_tick", 0) or 0)
            min_cfg = dict(getattr(b0, "min_stats", {}) or {})
            min_spd_val = int(min_cfg.get("SPD", 0) or 0) or int(min_cfg.get("SPD_NO_BASE", 0) or 0)
            sortable.append((key, pos, uid, label, spd_tick, min_spd_val))
        sortable.sort(key=lambda x: (x[0], x[1]))
        return [(uid, label, spd_tick, min_spd_val) for _, _, uid, label, spd_tick, min_spd_val in sortable]

    def _create_spd_tick_combo(self, uid: int, spd_tick: int) -> _NoScrollComboBox:
        tick_cmb = _NoScrollComboBox()
        tick_labels: List[str] = ["-"]
        tick_cmb.addItem("-", 0)
        for tick in allowed_spd_ticks(self.mode):
            tick_i = int(tick)
            if str(self.mode).strip().lower() != "rta" and tick_i == int(LEO_LOW_SPD_TICK):
                low_max = int(max_spd_for_tick(tick_i, self.mode) or 0)
                threshold = int(low_max + 1) if low_max > 0 else 130
                label_txt = f"11 (<{threshold})"
                tick_cmb.addItem(label_txt, tick_i)
                tick_labels.append(label_txt)
                continue
            spd_bp = min_spd_for_tick(tick_i, self.mode)
            label_txt = f"{tick_i} (>={spd_bp})"
            tick_cmb.addItem(label_txt, tick_i)
            tick_labels.append(label_txt)
        max_text_px = max((tick_cmb.fontMetrics().horizontalAdvance(tl) for tl in tick_labels), default=0)
        tick_cmb.setFixedWidth(max(dp(46), int(max_text_px + dp(30))))
        idx = tick_cmb.findData(int(spd_tick))
        tick_cmb.setCurrentIndex(idx if idx >= 0 else 0)
        tick_cmb.setToolTip(tr("tooltip.spd_tick"))
        tick_cmb.currentIndexChanged.connect(
            lambda _, _uid=int(uid), _cmb=tick_cmb: self._on_team_spd_tick_changed(_uid, _cmb)
        )
        self._team_spd_tick_combo_by_unit.setdefault(int(uid), []).append(tick_cmb)
        return tick_cmb

    def _create_turn_effect_controls(
        self,
        team_idx: int,
        uid: int,
        effect_spd_buff: bool,
        can_spd_buff: bool,
        spd_buff_icon_file: str,
        effect_atb_boost_pct: int,
        can_atb_boost: bool,
        atb_boost_icon_file: str,
        max_atb_boost_pct: int,
    ) -> Tuple[QCheckBox, QCheckBox, QSpinBox]:
        if can_spd_buff:
            spd_buff_chk = QCheckBox()
            _skill_icon = self._load_skill_icon(spd_buff_icon_file)
            if _skill_icon:
                spd_buff_chk.setIcon(_skill_icon)
                spd_buff_chk.setIconSize(QSize(dp(20), dp(20)))
            else:
                spd_buff_chk.setText("S")
            spd_buff_chk.setChecked(bool(effect_spd_buff))
            spd_buff_chk.setToolTip(tr("tooltip.effect_spd_buff"))
        else:
            spd_buff_chk = QCheckBox()
            spd_buff_chk.setChecked(False)
            spd_buff_chk.setVisible(False)

        if can_atb_boost:
            atb_boost_chk = QCheckBox()
            _atb_icon = self._load_skill_icon(atb_boost_icon_file)
            if _atb_icon:
                atb_boost_chk.setIcon(_atb_icon)
                atb_boost_chk.setIconSize(QSize(dp(20), dp(20)))
            else:
                atb_boost_chk.setText("A")
            atb_boost_chk.setChecked(bool(effect_atb_boost_pct > 0))
            atb_boost_chk.setToolTip(tr("tooltip.effect_atb_boost"))
            atb_boost_spin = QSpinBox()
            atb_boost_spin.setMinimum(0)
            atb_boost_spin.setMaximum(int(max_atb_boost_pct))
            atb_boost_spin.setSingleStep(5)
            atb_boost_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
            atb_boost_spin.setSuffix("%")
            atb_boost_spin.setMaximumWidth(dp(56))
            if int(effect_atb_boost_pct) > 0:
                atb_boost_spin.setValue(min(int(effect_atb_boost_pct), int(max_atb_boost_pct)))
            else:
                atb_boost_spin.setValue(min(30, int(max_atb_boost_pct)))
            atb_boost_spin.setEnabled(bool(atb_boost_chk.isChecked()))
            atb_boost_chk.toggled.connect(lambda checked, spin=atb_boost_spin: spin.setEnabled(bool(checked)))
        else:
            atb_boost_chk = QCheckBox()
            atb_boost_chk.setChecked(False)
            atb_boost_chk.setVisible(False)
            atb_boost_spin = QSpinBox()
            atb_boost_spin.setValue(0)
            atb_boost_spin.setVisible(False)

        self._team_effect_controls[(int(team_idx), int(uid))] = (spd_buff_chk, atb_boost_chk, atb_boost_spin)
        return spd_buff_chk, atb_boost_chk, atb_boost_spin

    def _create_team_row_widget(
        self, team_idx: int, uid: int, label: str, spd_tick: int, min_spd_val: int
    ) -> Tuple[QWidget, int]:
        """Portrait-card style row: bigger icon, name+SPD stacked, tick combo right-aligned."""
        c = _theme.C

        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(dp(8), dp(6), dp(8), dp(6))
        row_layout.setSpacing(dp(10))

        icon_lbl = QLabel()
        icon = self._unit_icon_fn(uid)
        if not icon.isNull():
            icon_lbl.setPixmap(icon.pixmap(dp(44), dp(44)))
        icon_lbl.setAlignment(Qt.AlignVCenter)
        row_layout.addWidget(icon_lbl, 0, Qt.AlignVCenter)

        info_col = QVBoxLayout()
        info_col.setSpacing(dp(2))
        info_col.setAlignment(Qt.AlignVCenter)

        name_lbl = QLabel(str(label))
        name_lbl.setStyleSheet(f"font-weight: bold; font-size: {dp(12)}px;")
        name_lbl.setWordWrap(False)
        info_col.addWidget(name_lbl)

        if min_spd_val > 0:
            spd_lbl = QLabel(f"min SPD {min_spd_val}")
            spd_lbl.setStyleSheet(
                f"color: {c['text_dim']}; font-size: {dp(10)}px;"
            )
            info_col.addWidget(spd_lbl)

        info_widget = QWidget()
        info_widget.setLayout(info_col)
        row_layout.addWidget(info_widget, 1, Qt.AlignVCenter)

        tick_widget = QWidget()
        tick_h = QHBoxLayout(tick_widget)
        tick_h.setContentsMargins(0, 0, 0, 0)
        tick_h.setSpacing(dp(4))

        tick_lbl = QLabel(tr("label.spd_tick_short"))
        tick_lbl.setStyleSheet(f"color: {c['text_dim']}; font-size: {dp(9)}px;")
        tick_h.addWidget(tick_lbl, 0, Qt.AlignVCenter)

        tick_cmb = self._create_spd_tick_combo(int(uid), int(spd_tick))
        tick_h.addWidget(tick_cmb, 0, Qt.AlignVCenter)

        row_layout.addWidget(tick_widget, 0, Qt.AlignVCenter)

        row_min_height = max(dp(62), dp(44) + dp(16))
        row_widget.setMinimumHeight(row_min_height)
        return row_widget, row_min_height

    def _build_team_list(self, team_idx: int, team_units: List[Tuple[int, str]]) -> QListWidget:
        lw = QListWidget()
        lw.setDragDropMode(QAbstractItemView.InternalMove)
        lw.setDefaultDropAction(Qt.MoveAction)
        lw.setSelectionMode(QAbstractItemView.SingleSelection)
        lw.setIconSize(QSize(dp(44), dp(44)))
        lw.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sorted_units = self._sorted_team_units(team_units)
        lw.setMinimumHeight(max(dp(80), len(sorted_units) * dp(62) + dp(14)))
        for uid, label, spd_tick, min_spd_val in sorted_units:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, int(uid))
            lw.addItem(it)
            row_widget, row_min_height = self._create_team_row_widget(
                int(team_idx), int(uid), label, int(spd_tick), int(min_spd_val)
            )
            it.setSizeHint(QSize(0, int(row_min_height)))
            lw.setItemWidget(it, row_widget)
        self._team_order_lists.append(lw)
        lw.currentItemChanged.connect(
            lambda current, _prev, _lw=lw: self._on_team_list_item_changed(_lw, current)
        )
        return lw

    def _on_team_spd_tick_changed(self, uid: int, source_cmb: QComboBox) -> None:
        if self._syncing_team_spd_tick:
            return
        combos = list(self._team_spd_tick_combo_by_unit.get(int(uid), []) or [])
        if len(combos) <= 1:
            return
        target_tick = int(source_cmb.currentData() or 0)
        self._syncing_team_spd_tick = True
        try:
            for cmb in combos:
                if cmb is source_cmb:
                    continue
                idx = cmb.findData(int(target_tick))
                if idx >= 0 and cmb.currentIndex() != idx:
                    cmb.setCurrentIndex(idx)
        finally:
            self._syncing_team_spd_tick = False

    def _on_team_list_item_changed(
        self, source_list: QListWidget, current: QListWidgetItem | None
    ) -> None:
        if self._syncing_focus_selection:
            return
        if source_list not in self._team_order_lists:
            return
        if current is None:
            return
        uid = int(current.data(Qt.UserRole) or 0)
        if uid <= 0:
            return
        self._syncing_focus_selection = True
        try:
            for lw in self._team_order_lists:
                if lw is source_list:
                    continue
                if lw.currentRow() >= 0:
                    lw.setCurrentRow(-1)
                lw.clearSelection()
            self.unit_selected.emit(int(uid))
        finally:
            self._syncing_focus_selection = False

    def _load_skill_icon(self, icon_filename: str) -> QIcon | None:
        if not icon_filename or not self._skill_icons_dir:
            return None
        path = self._skill_icons_dir / icon_filename
        if not path.exists():
            return None
        pix = QPixmap(str(path))
        if pix.isNull():
            return None
        return QIcon(pix)
