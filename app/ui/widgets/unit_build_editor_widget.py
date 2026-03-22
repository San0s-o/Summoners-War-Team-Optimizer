from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.domain.artifact_effects import artifact_effect_is_legacy, artifact_effect_label
from app.domain.build_editor_helpers import (
    min_mode_for_build,
    min_value_for_build,
    parse_set_options_to_slot_ids,
    unit_base_stats_for_min,
)
from app.domain.presets import (
    ARTIFACT_MAIN_KEYS,
    Build,
    MAINSTAT_KEYS,
    SLOT2_DEFAULT,
    SLOT4_DEFAULT,
    SLOT6_DEFAULT,
)
from app.i18n import tr
from app.ui.dpi import dp
from app.ui import theme as _theme
from app.ui.widgets.selection_combos import _MainstatMultiCombo, _NoScrollComboBox, _SetMultiCombo

if TYPE_CHECKING:
    from app.domain.models import AccountData


_MIN_BASE_STATS = ("SPD", "HP", "ATK", "DEF")


def _artifact_kind_label(type_id: int) -> str:
    if type_id == 1:
        return tr("artifact.attribute")
    if type_id == 2:
        return tr("artifact.type")
    return str(type_id)


def _artifact_effect_label_str(effect_id: int) -> str:
    return artifact_effect_label(effect_id, fallback_prefix="Effekt")


def set_art_focus_combo_value(cmb: QComboBox, value: str) -> None:
    sval = str(value or "").upper()
    if sval not in ("HP", "ATK", "DEF"):
        return
    idx = cmb.findData(sval)
    if idx >= 0:
        cmb.setCurrentIndex(idx)


def set_art_sub_combo_value(cmb: QComboBox, effect_id: int) -> None:
    eid = int(effect_id or 0)
    if eid <= 0:
        return
    idx = cmb.findData(eid)
    if idx < 0:
        cmb.addItem(_artifact_effect_label_str(eid), eid)
        idx = cmb.findData(eid)
    if idx >= 0:
        cmb.setCurrentIndex(idx)


@dataclass
class UnitEditorRefs:
    set1: Any
    set2: Any
    set3: Any
    ms2: Any
    ms4: Any
    ms6: Any
    art_attr_focus: Any
    art_type_focus: Any
    art_attr_sub1: Any
    art_attr_sub2: Any
    art_type_sub1: Any
    art_type_sub2: Any
    min_mode: Any
    min_spd: Any
    min_hp: Any
    min_atk: Any
    min_def: Any
    min_cr: Any
    min_cd: Any
    min_res: Any
    min_acc: Any
    community_status_label: Any

    def all_min_spins(self) -> Dict[str, Any]:
        return {
            "SPD": self.min_spd,
            "HP": self.min_hp,
            "ATK": self.min_atk,
            "DEF": self.min_def,
            "CR": self.min_cr,
            "CD": self.min_cd,
            "RES": self.min_res,
            "ACC": self.min_acc,
        }


class UnitBuildEditorWidget(QScrollArea):
    """Self-contained per-unit build editor page.

    Emits action signals instead of calling dialog methods directly, so the
    dialog can connect and handle them without tight coupling.
    """

    load_pref_runes_requested = Signal(int)
    load_community_trends_requested = Signal(int)
    save_pref_runes_requested = Signal(int)
    load_pref_artifacts_requested = Signal(int)
    save_pref_artifacts_requested = Signal(int)
    # Emitted when any set-combo selection changes; the dialog syncs constraints.
    set_constraints_changed = Signal(int)

    def __init__(
        self,
        unit_id: int,
        build: Build,
        account: "AccountData | None",
        artifact_options_by_type: Dict[int, List[int]],
        has_rune_pref: bool,
        has_artifact_pref: bool,
        community_status_text: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._unit_id = int(unit_id)
        self._refs: UnitEditorRefs | None = None
        self._setup_ui(
            build, account, artifact_options_by_type,
            has_rune_pref, has_artifact_pref, community_status_text,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def refs(self) -> UnitEditorRefs:
        assert self._refs is not None, "UnitBuildEditorWidget not yet initialized"
        return self._refs

    def set_community_status(self, text: str) -> None:
        if self._refs is not None:
            self._refs.community_status_label.setText(str(text or ""))

    # ------------------------------------------------------------------
    # Widget factory helpers (stateless, no self-data needed)
    # ------------------------------------------------------------------

    @staticmethod
    def _make_mainstat_combo(defaults: List[str]) -> _MainstatMultiCombo:
        _ = defaults
        cmb = _MainstatMultiCombo(MAINSTAT_KEYS)
        cmb.setToolTip(tr("tooltip.mainstat_multi"))
        cmb.setMinimumWidth(dp(190))
        return cmb

    @staticmethod
    def _make_art_focus_combo() -> QComboBox:
        cmb = _NoScrollComboBox()
        cmb.addItem("Any", "")
        for key in ARTIFACT_MAIN_KEYS:
            cmb.addItem(str(key), str(key))
        cmb.setMinimumWidth(dp(190))
        return cmb

    @staticmethod
    def _make_art_sub_combo(artifact_type: int, options_by_type: Dict[int, List[int]]) -> QComboBox:
        cmb = _NoScrollComboBox()
        cmb.addItem("Any", 0)
        eids = list(options_by_type.get(int(artifact_type), []))
        eids.sort(key=lambda x: (artifact_effect_is_legacy(int(x)), int(x)))
        for eid in eids:
            cmb.addItem(_artifact_effect_label_str(int(eid)), int(eid))
        cmb.setToolTip(tr("tooltip.art_sub", kind=_artifact_kind_label(int(artifact_type))))
        cmb.setMinimumWidth(190)
        return cmb

    @staticmethod
    def _make_min_mode_combo(mode: str) -> QComboBox:
        cmb = _NoScrollComboBox()
        cmb.addItem(tr("min.mode.with_base"), "with_base")
        cmb.addItem(tr("min.mode.without_base"), "without_base")
        idx = cmb.findData(str(mode))
        cmb.setCurrentIndex(idx if idx >= 0 else 0)
        cmb.setMinimumWidth(190)
        return cmb

    @staticmethod
    def _make_min_stat_spin(value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setMinimum(0)
        spin.setMaximum(99999)
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setValue(int(value))
        spin.setMaximumWidth(dp(110))
        return spin

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(
        self,
        build: Build,
        account: "AccountData | None",
        artifact_options_by_type: Dict[int, List[int]],
        has_rune_pref: bool,
        has_artifact_pref: bool,
        community_status_text: str,
    ) -> None:
        uid = self._unit_id
        content = QWidget()
        content.setObjectName("unitBuildEditorRoot")
        self.setWidget(content)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(dp(10), dp(10), dp(10), dp(10))
        content_layout.setSpacing(dp(10))

        # ---- Set combos ----
        cmb_set1 = _SetMultiCombo()
        cmb_set2 = _SetMultiCombo()
        cmb_set3 = _SetMultiCombo()
        cmb_set1.setToolTip(tr("tooltip.set_multi"))
        cmb_set2.setToolTip(tr("tooltip.set_multi"))
        cmb_set3.setToolTip(tr("tooltip.set3"))
        cmb_set1.setMinimumWidth(dp(190))
        cmb_set2.setMinimumWidth(dp(190))
        cmb_set3.setMinimumWidth(dp(190))
        slot1_ids, slot2_ids, slot3_ids = parse_set_options_to_slot_ids(build.set_options or [])
        cmb_set1.set_checked_ids(slot1_ids)
        cmb_set2.set_checked_ids(slot2_ids)
        cmb_set3.set_checked_ids(slot3_ids)
        cmb_set1.selection_changed.connect(lambda: self.set_constraints_changed.emit(uid))
        cmb_set2.selection_changed.connect(lambda: self.set_constraints_changed.emit(uid))
        cmb_set3.selection_changed.connect(lambda: self.set_constraints_changed.emit(uid))

        # ---- Mainstat combos ----
        cmb2 = self._make_mainstat_combo(SLOT2_DEFAULT)
        cmb4 = self._make_mainstat_combo(SLOT4_DEFAULT)
        cmb6 = self._make_mainstat_combo(SLOT6_DEFAULT)
        if build.mainstats:
            if 2 in build.mainstats and build.mainstats[2]:
                cmb2.set_checked_values([str(x) for x in (build.mainstats[2] or [])])
            if 4 in build.mainstats and build.mainstats[4]:
                cmb4.set_checked_values([str(x) for x in (build.mainstats[4] or [])])
            if 6 in build.mainstats and build.mainstats[6]:
                cmb6.set_checked_values([str(x) for x in (build.mainstats[6] or [])])

        # ---- Artifact focus combos ----
        art_attr_focus = self._make_art_focus_combo()
        art_type_focus = self._make_art_focus_combo()
        art_attr_focus.setToolTip(tr("tooltip.art_attr_focus"))
        art_type_focus.setToolTip(tr("tooltip.art_type_focus"))
        artifact_focus = dict(getattr(build, "artifact_focus", {}) or {})
        attr_focus_values = [str(x).upper() for x in (artifact_focus.get("attribute") or []) if str(x)]
        type_focus_values = [str(x).upper() for x in (artifact_focus.get("type") or []) if str(x)]
        if attr_focus_values:
            set_art_focus_combo_value(art_attr_focus, attr_focus_values[0])
        if type_focus_values:
            set_art_focus_combo_value(art_type_focus, type_focus_values[0])

        # ---- Artifact substat combos ----
        art_attr_sub1 = self._make_art_sub_combo(1, artifact_options_by_type)
        art_attr_sub2 = self._make_art_sub_combo(1, artifact_options_by_type)
        art_type_sub1 = self._make_art_sub_combo(2, artifact_options_by_type)
        art_type_sub2 = self._make_art_sub_combo(2, artifact_options_by_type)
        artifact_substats = dict(getattr(build, "artifact_substats", {}) or {})
        attr_subs = [int(x) for x in (artifact_substats.get("attribute") or []) if int(x) > 0][:2]
        type_subs = [int(x) for x in (artifact_substats.get("type") or []) if int(x) > 0][:2]
        if attr_subs:
            set_art_sub_combo_value(art_attr_sub1, attr_subs[0])
        if len(attr_subs) > 1:
            set_art_sub_combo_value(art_attr_sub2, attr_subs[1])
        if type_subs:
            set_art_sub_combo_value(art_type_sub1, type_subs[0])
        if len(type_subs) > 1:
            set_art_sub_combo_value(art_type_sub2, type_subs[1])

        # ---- Min stats ----
        current_min = dict(getattr(build, "min_stats", {}) or {})
        base_stats = unit_base_stats_for_min(account, uid)
        min_mode = min_mode_for_build(current_min)
        min_mode_combo = self._make_min_mode_combo(min_mode)
        min_spd = self._make_min_stat_spin(min_value_for_build(current_min, "SPD", min_mode, base_stats))
        min_hp = self._make_min_stat_spin(min_value_for_build(current_min, "HP", min_mode, base_stats))
        min_atk = self._make_min_stat_spin(min_value_for_build(current_min, "ATK", min_mode, base_stats))
        min_def = self._make_min_stat_spin(min_value_for_build(current_min, "DEF", min_mode, base_stats))
        min_cr = self._make_min_stat_spin(min_value_for_build(current_min, "CR", min_mode, base_stats))
        min_cd = self._make_min_stat_spin(min_value_for_build(current_min, "CD", min_mode, base_stats))
        min_res = self._make_min_stat_spin(min_value_for_build(current_min, "RES", min_mode, base_stats))
        min_acc = self._make_min_stat_spin(min_value_for_build(current_min, "ACC", min_mode, base_stats))
        min_spins: Dict[str, QSpinBox] = {
            "SPD": min_spd, "HP": min_hp, "ATK": min_atk, "DEF": min_def,
            "CR": min_cr, "CD": min_cd, "RES": min_res, "ACC": min_acc,
        }
        min_base_prefix_labels: Dict[str, QLabel] = {}

        def _base_prefix(key: str) -> QLabel:
            lbl = QLabel(tr("label.min_base_prefix", value=int(base_stats.get(key, 0) or 0)))
            min_base_prefix_labels[str(key)] = lbl
            return lbl

        # ---- Layout: rune sets box ----
        rune_sets_box = QGroupBox(tr("group.build_rune_sets"))
        rune_sets_box.setObjectName("unitEditorSection")
        rune_sets_layout = QFormLayout(rune_sets_box)
        rune_sets_layout.addRow(tr("header.set1"), cmb_set1)
        rune_sets_layout.addRow(tr("header.set2"), cmb_set2)
        rune_sets_layout.addRow(tr("header.set3"), cmb_set3)
        pref_btn_row = QWidget()
        pref_btn_layout = QHBoxLayout(pref_btn_row)
        pref_btn_layout.setContentsMargins(0, 0, 0, 0)
        pref_btn_layout.setSpacing(dp(6))
        btn_load_pref_runes = QPushButton(tr("btn.load_preferred_runes"))
        btn_load_pref_runes.setToolTip(
            tr("tooltip.load_preferred_runes") if has_rune_pref else tr("tooltip.load_preferred_runes_missing")
        )
        btn_load_pref_runes.clicked.connect(lambda _chk=False: self.load_pref_runes_requested.emit(uid))
        btn_load_community = QPushButton(tr("btn.load_community_trends"))
        btn_load_community.setToolTip(tr("tooltip.load_community_trends"))
        btn_load_community.clicked.connect(lambda _chk=False: self.load_community_trends_requested.emit(uid))
        btn_save_pref_runes = QPushButton(tr("btn.save_preferred_runes"))
        btn_save_pref_runes.setToolTip(tr("tooltip.save_preferred_runes"))
        btn_save_pref_runes.clicked.connect(lambda _chk=False: self.save_pref_runes_requested.emit(uid))
        pref_btn_layout.addWidget(btn_load_pref_runes)
        pref_btn_layout.addWidget(btn_load_community)
        pref_btn_layout.addWidget(btn_save_pref_runes)
        pref_btn_layout.addStretch(1)
        rune_sets_layout.addRow("", pref_btn_row)

        # ---- Layout: mainstats box ----
        mainstats_box = QGroupBox(tr("group.build_mainstats"))
        mainstats_box.setObjectName("unitEditorSection")
        mainstats_layout = QFormLayout(mainstats_box)
        mainstats_layout.addRow(tr("header.slot2_main"), cmb2)
        mainstats_layout.addRow(tr("header.slot4_main"), cmb4)
        mainstats_layout.addRow(tr("header.slot6_main"), cmb6)

        # ---- Layout: artifacts box ----
        artifact_box = QGroupBox(tr("group.build_artifacts"))
        artifact_box.setObjectName("unitEditorSection")
        artifact_layout = QFormLayout(artifact_box)
        artifact_layout.addRow(tr("header.attr_main"), art_attr_focus)
        artifact_layout.addRow(tr("header.attr_sub1"), art_attr_sub1)
        artifact_layout.addRow(tr("header.attr_sub2"), art_attr_sub2)
        artifact_layout.addRow(tr("header.type_main"), art_type_focus)
        artifact_layout.addRow(tr("header.type_sub1"), art_type_sub1)
        artifact_layout.addRow(tr("header.type_sub2"), art_type_sub2)
        art_pref_btn_row = QWidget()
        art_pref_btn_layout = QHBoxLayout(art_pref_btn_row)
        art_pref_btn_layout.setContentsMargins(0, 0, 0, 0)
        art_pref_btn_layout.setSpacing(dp(6))
        btn_load_pref_artifacts = QPushButton(tr("btn.load_preferred_artifacts"))
        btn_load_pref_artifacts.setToolTip(
            tr("tooltip.load_preferred_artifacts") if has_artifact_pref
            else tr("tooltip.load_preferred_artifacts_missing")
        )
        btn_load_pref_artifacts.clicked.connect(lambda _chk=False: self.load_pref_artifacts_requested.emit(uid))
        btn_save_pref_artifacts = QPushButton(tr("btn.save_preferred_artifacts"))
        btn_save_pref_artifacts.setToolTip(tr("tooltip.save_preferred_artifacts"))
        btn_save_pref_artifacts.clicked.connect(lambda _chk=False: self.save_pref_artifacts_requested.emit(uid))
        art_pref_btn_layout.addWidget(btn_load_pref_artifacts)
        art_pref_btn_layout.addWidget(btn_save_pref_artifacts)
        art_pref_btn_layout.addStretch(1)
        artifact_layout.addRow("", art_pref_btn_row)

        # ---- Top 3-column grid ----
        top_grid = QGridLayout()
        top_grid.setContentsMargins(0, 0, 0, 0)
        top_grid.setHorizontalSpacing(10)
        top_grid.setVerticalSpacing(8)
        top_grid.addWidget(rune_sets_box, 0, 0)
        top_grid.addWidget(mainstats_box, 0, 1)
        top_grid.addWidget(artifact_box, 0, 2)
        top_grid.setColumnStretch(0, 1)
        top_grid.setColumnStretch(1, 1)
        top_grid.setColumnStretch(2, 1)
        content_layout.addLayout(top_grid)

        # ---- Min stats box ----
        min_stats_box = QGroupBox(tr("group.build_min_stats"))
        min_stats_box.setObjectName("unitEditorSection")
        min_stats_layout = QGridLayout(min_stats_box)
        min_stats_layout.setHorizontalSpacing(12)
        min_stats_layout.setVerticalSpacing(8)
        min_stats_layout.addWidget(QLabel(tr("label.min_mode")), 0, 0)
        min_stats_layout.addWidget(min_mode_combo, 0, 1, 1, 2)
        min_stats_layout.addWidget(QLabel(tr("label.min_mode_hint")), 1, 0, 1, 4)

        def _make_min_stat_cell(label_text: str, stat_key: str, spin: QSpinBox) -> QWidget:
            cell = QWidget()
            row = QHBoxLayout(cell)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(dp(6))
            lbl = QLabel(label_text)
            lbl.setMinimumWidth(dp(56))
            row.addWidget(lbl)
            base_lbl = _base_prefix(stat_key)
            base_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            base_lbl.setMinimumWidth(dp(56))
            row.addWidget(base_lbl)
            spin.setMaximumWidth(dp(92))
            row.addWidget(spin)
            row.addStretch(1)
            return cell

        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_hp"), "HP", min_hp), 2, 0)
        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_atk"), "ATK", min_atk), 2, 1)
        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_def"), "DEF", min_def), 2, 2)
        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_spd"), "SPD", min_spd), 2, 3)
        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_cr"), "CR", min_cr), 3, 0)
        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_cd"), "CD", min_cd), 3, 1)
        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_res"), "RES", min_res), 3, 2)
        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_acc"), "ACC", min_acc), 3, 3)
        min_stats_layout.setColumnStretch(4, 1)

        def _sync_min_mode_ui() -> None:
            mode = str(min_mode_combo.currentData() or "with_base")
            use_base = mode == "with_base"
            for lbl in min_base_prefix_labels.values():
                lbl.setVisible(use_base)

        _tracked_mode = [min_mode]

        def _on_min_mode_changed() -> None:
            new_mode = str(min_mode_combo.currentData() or "with_base")
            old_mode = _tracked_mode[0]
            if new_mode != old_mode:
                for key, spin in min_spins.items():
                    cur_val = int(spin.value())
                    if key in _MIN_BASE_STATS:
                        base = int(base_stats.get(key, 0) or 0)
                        if old_mode == "with_base" and new_mode == "without_base":
                            spin.setValue(base + cur_val)
                        elif old_mode == "without_base" and new_mode == "with_base":
                            spin.setValue(max(0, cur_val - base))
                _tracked_mode[0] = new_mode
            _sync_min_mode_ui()

        min_mode_combo.currentIndexChanged.connect(lambda *_args: _on_min_mode_changed())
        _sync_min_mode_ui()

        community_status_lbl = QLabel(community_status_text)
        community_status_lbl.setWordWrap(True)
        community_status_lbl.setStyleSheet("color: #8aa1b4;")
        content_layout.addWidget(community_status_lbl)
        content_layout.addWidget(min_stats_box)
        content_layout.addStretch(1)

        c = _theme.C
        content.setStyleSheet(
            f"""
            QGroupBox#unitEditorSection {{
                border: 1px solid {c['border']};
                border-radius: {dp(8)}px;
                margin-top: {dp(8)}px;
                padding-top: {dp(14)}px;
            }}
            QGroupBox#unitEditorSection::title {{
                subcontrol-origin: margin;
                left: {dp(10)}px;
                padding: 0 {dp(6)}px;
                color: {c['text_dim']};
            }}
            QComboBox, QSpinBox {{
                border-radius: {dp(6)}px;
            }}
            QPushButton {{
                border-radius: {dp(6)}px;
            }}
            """
        )

        self._refs = UnitEditorRefs(
            set1=cmb_set1, set2=cmb_set2, set3=cmb_set3,
            ms2=cmb2, ms4=cmb4, ms6=cmb6,
            art_attr_focus=art_attr_focus, art_type_focus=art_type_focus,
            art_attr_sub1=art_attr_sub1, art_attr_sub2=art_attr_sub2,
            art_type_sub1=art_type_sub1, art_type_sub2=art_type_sub2,
            min_mode=min_mode_combo,
            min_spd=min_spd, min_hp=min_hp, min_atk=min_atk, min_def=min_def,
            min_cr=min_cr, min_cd=min_cd, min_res=min_res, min_acc=min_acc,
            community_status_label=community_status_lbl,
        )
