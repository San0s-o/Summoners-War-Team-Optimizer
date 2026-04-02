from __future__ import annotations

from math import ceil
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_app.domain.presets import Build, BuildStore
from desktop_app.domain.speed_ticks import LEO_LOW_SPD_TICK, allowed_spd_ticks, max_spd_for_tick, min_spd_for_tick
from desktop_app.i18n import tr
from desktop_app.ui.dpi import dp
from desktop_app.ui.widgets.selection_combos import _NoScrollComboBox


def _lock_team_list_height(lw: QListWidget) -> None:
    """Fix the list height so it cannot grow/shrink when embedded in a grid."""
    rows_total = 0
    for idx in range(lw.count()):
        item = lw.item(idx)
        if item is None:
            continue
        hint_h = int(item.sizeHint().height() or 0)
        if hint_h <= 0:
            hint_h = int(lw.sizeHintForRow(idx) or 0)
        rows_total += max(0, int(hint_h))
    row_gap = max(0, int(lw.spacing() or 0))
    if lw.count() > 1 and row_gap > 0:
        rows_total += row_gap * (lw.count() - 1)
    margins = lw.contentsMargins()
    frame_and_margins = (
        int(lw.frameWidth() * 2)
        + int(margins.top())
        + int(margins.bottom())
        + dp(6)
    )
    target_height = max(dp(120), int(rows_total + frame_and_margins))
    lw.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    lw.setMinimumHeight(target_height)
    lw.setMaximumHeight(target_height)
    lw.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)


class TeamOrderSection(QWidget):
    """Turn-order section: drag-and-drop team lists, spd-tick combos, turn-effect controls."""

    unit_selected: Signal = Signal(int)  # uid — emitted when user selects a unit in a team list

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
        skill_icons_dir: Path | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.mode = mode
        self._preset_store = preset_store
        self._unit_icon_fn = unit_icon_fn
        self._skill_icons_dir = skill_icons_dir
        self._team_size = max(1, int(team_size))
        self._unit_rows = list(unit_rows)

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
        self._show_turn_effect_controls = bool(show_turn_effect_controls)
        self._order_turn_effect_capabilities: Dict[int, Dict[str, Any]] = {
            int(uid): dict(cfg or {})
            for uid, cfg in dict(order_turn_effect_capabilities).items()
            if int(uid or 0) > 0
        }
        self._show_speed_lead_controls = bool(show_speed_lead_controls)
        self._order_speed_leaders: List[int] = [int(uid or 0) for uid in order_speed_leaders]
        self._order_speed_lead_pct_by_unit: Dict[int, int] = {
            int(uid): int(pct or 0)
            for uid, pct in dict(order_speed_lead_pct_by_unit).items()
            if int(uid or 0) > 0 and int(pct or 0) > 0
        }
        self._order_speed_lead_pct_by_team: List[int] = [int(v or 0) for v in order_speed_lead_pct_by_team]

        self._team_order_lists: List[QListWidget] = []
        self._team_spd_tick_combo_by_unit: Dict[int, List[QComboBox]] = {}
        self._syncing_team_spd_tick = False
        self._team_effect_controls: Dict[Tuple[int, int], Tuple[QCheckBox, QCheckBox, QSpinBox]] = {}
        self._team_speed_lead_combo_by_team: Dict[int, QComboBox] = {}
        self._team_speed_lead_pct_spin_by_team: Dict[int, QSpinBox] = {}
        self._syncing_focus_selection = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if self._order_teams:
            teams: List[List[Tuple[int, str]]] = [list(t) for t in self._order_teams if t]
        else:
            teams = [
                self._unit_rows[i : i + self._team_size]
                for i in range(0, len(self._unit_rows), self._team_size)
                if self._unit_rows[i : i + self._team_size]
            ]

        order_box = QGroupBox(tr("group.turn_order"))
        order_outer = QVBoxLayout(order_box)
        if teams and self._order_teams:
            self._build_arena_rush_order_section(order_outer, teams)
        elif teams:
            self._build_paginated_order_section(order_outer, teams)

        if str(self.mode).strip().lower() == "arena_rush":
            layout.addWidget(order_box)
        else:
            order_scroll = QScrollArea()
            order_scroll.setWidgetResizable(True)
            order_scroll.setWidget(order_box)
            order_scroll.setMaximumHeight(dp(340))
            layout.addWidget(order_scroll)

    # ── Public read API ──────────────────────────────────────────────────────

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

    # ── Snapshot support ─────────────────────────────────────────────────────

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

    # ── Update support ───────────────────────────────────────────────────────

    def set_spd_tick_for_unit(self, uid: int, tick: int) -> None:
        for tick_cmb in list(self._team_spd_tick_combo_by_unit.get(int(uid), []) or []):
            idx = tick_cmb.findData(int(tick))
            tick_cmb.setCurrentIndex(int(idx) if idx >= 0 else 0)

    # ── Restore support ──────────────────────────────────────────────────────

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

    # ── Private: UI building ─────────────────────────────────────────────────

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

    def _build_arena_rush_order_section(
        self, order_outer: QVBoxLayout, teams: List[List[Tuple[int, str]]]
    ) -> None:
        def_title = self._order_team_titles[0] if self._order_team_titles else "Team 1"
        if self._show_speed_lead_controls:
            order_outer.addLayout(self._build_team_header_with_speed_lead(0, def_title, teams[0]))
        else:
            order_outer.addWidget(QLabel(f"<b>{def_title}</b>"))
        order_outer.addWidget(self._build_team_list(0, teams[0]))
        if len(teams) > 1:
            max_offense_cols = 5
            off_grid = QGridLayout()
            for t_off, team_units in enumerate(teams[1:], start=1):
                off_idx = int(t_off - 1)
                col = int(off_idx % max_offense_cols)
                header_row = int(off_idx // max_offense_cols) * 2
                team_title = (
                    self._order_team_titles[t_off]
                    if t_off < len(self._order_team_titles) and self._order_team_titles[t_off]
                    else f"Team {t_off + 1}"
                )
                if self._show_speed_lead_controls:
                    hdr = QWidget()
                    hdr.setLayout(self._build_team_header_with_speed_lead(int(t_off), team_title, team_units))
                    off_grid.addWidget(hdr, header_row, col)
                else:
                    off_grid.addWidget(QLabel(f"<b>{team_title}</b>"), header_row, col)
                off_grid.addWidget(self._build_team_list(t_off, team_units), header_row + 1, col)
            order_outer.addLayout(off_grid)

    def _build_dot_nav(self, num_pages: int, pages_stack: QStackedWidget) -> QHBoxLayout:
        _sz = dp(12)
        _arrow_ss = (
            "QPushButton {"
            " background: transparent; border: none; padding: 0px;"
            f" min-height: 0px; min-width: 0px; font-size: {dp(16)}px; color: #aaa;"
            "}"
            "QPushButton:hover { color: #fff; }"
        )

        def _dot_style(active: bool) -> str:
            col = "#3498db" if active else "#555"
            hov = "#5faee3" if active else "#777"
            r = _sz // 2
            return (
                f"QPushButton {{ background: {col}; border-radius: {r}px; border: none;"
                f" padding: 0px; min-height: {_sz}px; max-height: {_sz}px;"
                f" min-width: {_sz}px; max-width: {_sz}px; }}"
                f"QPushButton:hover {{ background: {hov}; }}"
            )

        page_dots: List[QPushButton] = []

        def _go_to_page(p: int) -> None:
            p = max(0, min(num_pages - 1, p))
            pages_stack.setCurrentIndex(p)
            for i, d in enumerate(page_dots):
                d.setStyleSheet(_dot_style(i == p))

        dot_bar = QHBoxLayout()
        dot_bar.setAlignment(Qt.AlignCenter)
        dot_bar.setSpacing(dp(8))
        dot_bar.setContentsMargins(0, dp(4), 0, 0)

        prev_btn = QPushButton("‹")
        prev_btn.setFixedSize(dp(20), dp(20))
        prev_btn.setStyleSheet(_arrow_ss)
        prev_btn.clicked.connect(lambda _=False: _go_to_page(pages_stack.currentIndex() - 1))
        dot_bar.addWidget(prev_btn)

        for pi in range(num_pages):
            dot = QPushButton()
            dot.setFixedSize(_sz, _sz)
            dot.setStyleSheet(_dot_style(pi == 0))
            dot.clicked.connect(lambda _, pp=pi: _go_to_page(pp))
            dot_bar.addWidget(dot)
            page_dots.append(dot)

        next_btn = QPushButton("›")
        next_btn.setFixedSize(dp(20), dp(20))
        next_btn.setStyleSheet(_arrow_ss)
        next_btn.clicked.connect(lambda _=False: _go_to_page(pages_stack.currentIndex() + 1))
        dot_bar.addWidget(next_btn)

        return dot_bar

    def _build_paginated_order_section(
        self, order_outer: QVBoxLayout, teams: List[List[Tuple[int, str]]]
    ) -> None:
        _teams_per_page = 5
        num_teams = len(teams)
        num_pages = max(1, ceil(num_teams / _teams_per_page))

        def _build_page_grid(page_idx: int) -> QWidget:
            page_widget = QWidget()
            page_grid = QGridLayout(page_widget)
            page_grid.setSpacing(dp(8))
            page_grid.setContentsMargins(0, 0, 0, 0)
            start = page_idx * _teams_per_page
            for local_col, t in enumerate(range(start, min(start + _teams_per_page, num_teams))):
                team_title = (
                    self._order_team_titles[t]
                    if t < len(self._order_team_titles) and self._order_team_titles[t]
                    else f"Team {t + 1}"
                )
                page_grid.addWidget(QLabel(f"<b>{team_title}</b>"), 0, local_col)
                page_grid.addWidget(self._build_team_list(t, teams[t]), 1, local_col)
            return page_widget

        if num_pages == 1:
            order_outer.addWidget(_build_page_grid(0))
        else:
            pages_stack = QStackedWidget()
            for pi in range(num_pages):
                pages_stack.addWidget(_build_page_grid(pi))
            order_outer.addWidget(pages_stack)
            order_outer.addLayout(self._build_dot_nav(num_pages, pages_stack))

    def _build_team_header_with_speed_lead(
        self, team_index: int, team_title: str, team_units: List[Tuple[int, str]]
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(dp(6))
        row.addWidget(QLabel(f"<b>{team_title}</b>"))
        row.addStretch(1)
        row.addWidget(QLabel("SPD Lead"))
        cmb = _NoScrollComboBox()
        cmb.setMinimumWidth(dp(180))
        cmb.addItem("-", 0)
        for uid, label in team_units:
            pct = int(self._order_speed_lead_pct_by_unit.get(int(uid), 0) or 0)
            if pct <= 0:
                continue
            cmb.addItem(f"{label} (+{pct}%)", int(uid))
        preferred_uid = int(self._order_speed_leaders[int(team_index)]) if int(team_index) < len(self._order_speed_leaders) else 0
        idx = cmb.findData(int(preferred_uid))
        if idx < 0 and cmb.count() > 1:
            idx = 1
        cmb.setCurrentIndex(max(0, idx))
        cmb.setEnabled(bool(cmb.count() > 1))
        row.addWidget(cmb)
        pct_spin = QSpinBox()
        pct_spin.setMinimum(0)
        pct_spin.setMaximum(100)
        pct_spin.setSingleStep(1)
        pct_spin.setSuffix("%")
        pct_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        pct_spin.setReadOnly(True)
        pct_spin.setMaximumWidth(dp(64))
        preferred_pct = int(self._order_speed_lead_pct_by_team[int(team_index)]) if int(team_index) < len(self._order_speed_lead_pct_by_team) else 0
        if preferred_pct <= 0:
            selected_uid = int(cmb.currentData() or 0)
            preferred_pct = int(self._order_speed_lead_pct_by_unit.get(int(selected_uid), 0) or 0)
        pct_spin.setValue(max(0, min(100, int(preferred_pct))))
        row.addWidget(pct_spin)

        def _sync_pct_from_selected(_idx: int, _cmb: QComboBox = cmb, _spin: QSpinBox = pct_spin) -> None:
            sel_uid = int(_cmb.currentData() or 0)
            known_pct = int(self._order_speed_lead_pct_by_unit.get(int(sel_uid), 0) or 0)
            _spin.setValue(max(0, min(100, int(known_pct))))

        cmb.currentIndexChanged.connect(_sync_pct_from_selected)
        self._team_speed_lead_combo_by_team[int(team_index)] = cmb
        self._team_speed_lead_pct_spin_by_team[int(team_index)] = pct_spin
        return row

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

    def _create_spd_tick_combo(self, uid: int, spd_tick: int) -> "_NoScrollComboBox":
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
        team_effect_cfg = dict(self._order_turn_effects[team_idx]) if team_idx < len(self._order_turn_effects) else {}
        effect_cfg = dict(team_effect_cfg.get(int(uid), {}) or {})
        capability_cfg = dict(self._order_turn_effect_capabilities.get(int(uid), {}) or {})
        effect_spd_buff = bool(effect_cfg.get("applies_spd_buff", False))
        effect_atb_boost_pct = int(float(effect_cfg.get("atb_boost_pct", 0.0) or 0.0))
        can_spd_buff = bool(capability_cfg.get("has_spd_buff", False))
        can_atb_boost = bool(capability_cfg.get("has_atb_boost", False))
        max_atb_boost_pct = int(capability_cfg.get("max_atb_boost_pct", 0) or 0) or 100
        spd_buff_icon_file = str(capability_cfg.get("spd_buff_skill_icon", "") or "")
        atb_boost_icon_file = str(capability_cfg.get("atb_boost_skill_icon", "") or "")

        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(dp(2), dp(4), dp(4), dp(4))
        row_layout.setSpacing(dp(4))

        icon_lbl = QLabel()
        icon = self._unit_icon_fn(uid)
        if not icon.isNull():
            icon_lbl.setPixmap(icon.pixmap(dp(28), dp(28)))
        row_layout.addWidget(icon_lbl)

        txt_lbl = QLabel(label)
        txt_lbl.setMinimumWidth(0)
        txt_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        txt_lbl.setWordWrap(False)
        row_layout.addWidget(txt_lbl, 1)

        spd_lbl = QLabel(f"SPD {min_spd_val}" if min_spd_val > 0 else "")
        spd_lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        row_layout.addWidget(spd_lbl)

        tick_lbl = QLabel(tr("label.spd_tick_short"))
        tick_lbl.setFixedWidth(dp(22))
        tick_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        tick_cmb = self._create_spd_tick_combo(int(uid), int(spd_tick))

        if self._show_turn_effect_controls:
            spd_buff_chk, atb_boost_chk, atb_boost_spin = self._create_turn_effect_controls(
                int(team_idx), int(uid),
                effect_spd_buff, can_spd_buff, spd_buff_icon_file,
                effect_atb_boost_pct, can_atb_boost, atb_boost_icon_file,
                max_atb_boost_pct,
            )
            if can_spd_buff:
                row_layout.addWidget(spd_buff_chk)
            if can_atb_boost:
                row_layout.addWidget(atb_boost_chk)
                row_layout.addWidget(atb_boost_spin)

        row_layout.addWidget(tick_lbl, 0, Qt.AlignVCenter)
        row_layout.addWidget(tick_cmb, 0, Qt.AlignVCenter)

        row_min_height = max(row_widget.sizeHint().height(), tick_cmb.sizeHint().height() + dp(8))
        row_widget.setMinimumHeight(row_min_height)
        return row_widget, row_min_height

    def _build_team_list(self, team_idx: int, team_units: List[Tuple[int, str]]) -> QListWidget:
        lw = QListWidget()
        lw.setDragDropMode(QAbstractItemView.InternalMove)
        lw.setDefaultDropAction(Qt.MoveAction)
        lw.setSelectionMode(QAbstractItemView.SingleSelection)
        lw.setIconSize(QSize(dp(36), dp(36)))
        sorted_units = self._sorted_team_units(team_units)
        lw.setMinimumHeight(max(dp(140), len(sorted_units) * dp(46) + dp(14)))
        lw.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for uid, label, spd_tick, min_spd_val in sorted_units:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, int(uid))
            lw.addItem(it)
            row_widget, row_min_height = self._create_team_row_widget(
                int(team_idx), int(uid), label, int(spd_tick), int(min_spd_val)
            )
            it.setSizeHint(QSize(0, int(row_min_height)))
            lw.setItemWidget(it, row_widget)
        if str(self.mode).strip().lower() == "arena_rush" and self._order_teams:
            _lock_team_list_height(lw)
        self._team_order_lists.append(lw)
        lw.currentItemChanged.connect(
            lambda current, _prev, _lw=lw: self._on_team_list_current_item_changed(_lw, current)
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

    def _on_team_list_current_item_changed(
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
