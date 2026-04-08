from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop_app.domain.models import AccountData, Rune, Unit
from desktop_app.domain.monster_db import MonsterDB, MonsterInfo
from desktop_app.domain.presets import EFFECT_ID_TO_MAINSTAT_KEY, SET_NAMES
from desktop_app.engine.efficiency import rune_efficiency, rune_efficiency_max
from desktop_app.i18n import tr
from desktop_app.ui import theme as _theme
from desktop_app.ui.dpi import dp

_PCT_KEYS = {"HP%", "ATK%", "DEF%", "CR", "CD", "RES", "ACC"}
_QUALITY_BASE_NAME = {
    1: "Normal",
    2: "Magic",
    3: "Rare",
    4: "Hero",
    5: "Legend",
    6: "Legend",
    11: "Normal",
    12: "Magic",
    13: "Rare",
    14: "Hero",
    15: "Legend",
    16: "Legend",
}
_ANCIENT_CLASS_IDS = {11, 12, 13, 14, 15, 16}


def _stat_label(eff_id: int, value: object) -> str:
    key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(eff_id or 0), f"#{eff_id}")
    base = key.rstrip("%")
    try:
        v = float(value)  # type: ignore[arg-type]
        val = str(int(v)) if abs(v - int(v)) < 1e-9 else f"{v:.1f}"
    except Exception:
        val = str(value)
    suffix = "%" if key in _PCT_KEYS else ""
    return f"{base} +{val}{suffix}"


def _quality_class_id(rune: Rune) -> int:
    origin = int(getattr(rune, "origin_class", 0) or 0)
    return origin if origin else int(rune.rune_class or 0)


def _quality_text(rune: Rune) -> str:
    cls_id = _quality_class_id(rune)
    base = _QUALITY_BASE_NAME.get(cls_id, f"{tr('ui.class_short')} {cls_id}")
    if cls_id in _ANCIENT_CLASS_IDS:
        return tr("rune_opt.quality_ancient", quality=base)
    return base


def _substats_text(rune: Rune) -> str:
    parts: list[str] = []
    for sec in (rune.sec_eff or []):
        if not sec:
            continue
        eff_id = int(sec[0] or 0) if len(sec) > 0 else 0
        base = int(sec[1] or 0) if len(sec) > 1 else 0
        gemmed = int(sec[2] or 0) if len(sec) > 2 else 0
        grind = int(sec[3] or 0) if len(sec) > 3 else 0
        pct = "%" if EFFECT_ID_TO_MAINSTAT_KEY.get(eff_id, "") in _PCT_KEYS else ""
        total = base + grind
        token = _stat_label(eff_id, total)
        if grind > 0:
            token += f" ({base}+{grind}{pct})"
        if gemmed > 0:
            token += " [Gem]"
        parts.append(token)
    return ", ".join(parts)


def _gem_grind_status(rune: Rune) -> str:
    gemmed = 0
    grinded = 0
    for sec in (rune.sec_eff or []):
        if not sec:
            continue
        gemmed += 1 if (len(sec) > 2 and int(sec[2] or 0) > 0) else 0
        grinded += 1 if (len(sec) > 3 and int(sec[3] or 0) > 0) else 0
    return tr("rune_opt.gem_grind_status", gems=gemmed, grinds=grinded)


def _unit_has_missing_skillups(unit: Unit, skill_max_levels: Dict[int, int]) -> bool:
    """Return True if the unit has at least one upgradeable skill below max level."""
    for skill_id, current_level in (unit.skills or ()):
        max_lvl = skill_max_levels.get(skill_id, 0)
        if max_lvl <= 1:
            continue
        if current_level < max_lvl:
            return True
    return False


def _count_missing_skillups(unit: Unit, skill_max_levels: Dict[int, int]) -> int:
    """Return total number of skill-up points still needed for this unit."""
    total = 0
    for skill_id, current_level in (unit.skills or ()):
        max_lvl = skill_max_levels.get(skill_id, 0)
        if max_lvl <= 1:
            continue
        if current_level < max_lvl:
            total += max_lvl - current_level
    return total


class _MonsterDetailDialog(QDialog):
    """Full detail dialog opened when clicking a monster icon."""

    _ICON_SIZE = 72
    _SKILL_ICON_SIZE = 48

    def __init__(
        self,
        info: MonsterInfo,
        unit: Unit,
        account: AccountData,
        skill_max_levels: Dict[int, int],
        skill_icons: Dict[int, str],
        skill_names: Dict[int, str],
        assets_dir: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(str(info.name or ""))
        self.setMinimumSize(dp(920), dp(760))
        self.resize(dp(980), dp(820))
        self.setStyleSheet(
            f"QDialog {{ background: {_theme.C['bg']}; }}"
            f"QLabel {{ color: {_theme.C['text']}; }}"
            f"QTabWidget::pane {{ border: 1px solid {_theme.C['card_border']}; border-radius: {dp(4)}px; }}"
            f"QTabBar::tab {{ background: {_theme.C['card_bg']}; color: {_theme.C['text_dim']}; "
            f"  padding: {dp(5)}px {dp(12)}px; border-radius: {dp(4)}px; margin-right: {dp(2)}px; }}"
            f"QTabBar::tab:selected {{ background: {_theme.C['accent']}; color: {_theme.C['text']}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(dp(16), dp(14), dp(16), dp(14))
        root.setSpacing(dp(12))

        # â”€â”€ Header â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        header = QHBoxLayout()
        header.setSpacing(dp(12))

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(dp(self._ICON_SIZE), dp(self._ICON_SIZE))
        icon_lbl.setAlignment(Qt.AlignCenter)
        px = self._load_monster_pixmap(info, assets_dir)
        if px:
            icon_lbl.setPixmap(px.scaled(dp(self._ICON_SIZE), dp(self._ICON_SIZE), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        header.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(dp(2))
        name_lbl = QLabel(str(info.name or ""))
        name_lbl.setStyleSheet(f"font-size: 14pt; font-weight: bold; color: {_theme.C['text']};")
        title_col.addWidget(name_lbl)
        element = str(info.element or "")
        unit_class = int(getattr(unit, "unit_class", 0) or 0)
        level = int(getattr(unit, "unit_level", 0) or 0)
        meta_lbl = QLabel(f"{element}  |  Lv{level}  |  â˜…{unit_class}")
        meta_lbl.setStyleSheet(f"color: {_theme.C['text_dim']};")
        title_col.addWidget(meta_lbl)

        teams = self._team_memberships(unit.unit_id, account)
        if teams:
            teams_lbl = QLabel("  Â·  ".join(teams))
            teams_lbl.setStyleSheet(f"color: {_theme.C['accent']}; font-size: 9pt;")
            title_col.addWidget(teams_lbl)

        header.addLayout(title_col)
        header.addStretch()
        root.addLayout(header)

        # â”€â”€ Skills â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        skills_label = QLabel(tr("collection.detail_skills"))
        skills_label.setStyleSheet(f"font-weight: bold; font-size: 10pt; color: {_theme.C['text']};")
        root.addWidget(skills_label)

        skills_row = QHBoxLayout()
        skills_row.setSpacing(dp(10))
        skills_row.setAlignment(Qt.AlignLeft)
        for idx, (skill_id, current_level) in enumerate(unit.skills or ()):
            max_lvl = skill_max_levels.get(skill_id, 0)
            col = QVBoxLayout()
            col.setSpacing(dp(2))
            col.setAlignment(Qt.AlignHCenter)

            icon_lbl2 = QLabel()
            sz = dp(self._SKILL_ICON_SIZE)
            icon_lbl2.setFixedSize(sz, sz)
            icon_lbl2.setAlignment(Qt.AlignCenter)
            icon_filename = skill_icons.get(skill_id, "")
            if icon_filename and assets_dir:
                p = assets_dir / "skills" / f"{icon_filename}.png"
                if p.exists():
                    icon_lbl2.setPixmap(QPixmap(str(p)).scaled(sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            if not icon_lbl2.pixmap() or icon_lbl2.pixmap().isNull():
                icon_lbl2.setText(f"S{idx + 1}")
                icon_lbl2.setStyleSheet(
                    f"background: {_theme.C['card_bg']}; border-radius: {dp(6)}px; "
                    f"color: {_theme.C['text']}; font-weight: bold;"
                )
            col.addWidget(icon_lbl2)

            skill_name = skill_names.get(skill_id, "")
            if skill_name:
                nm = QLabel(skill_name)
                nm.setAlignment(Qt.AlignCenter)
                nm.setWordWrap(True)
                nm.setFixedWidth(max(sz, dp(88)))
                nm.setStyleSheet(f"font-size: 9pt; color: {_theme.C['text_dim']};")
                col.addWidget(nm)

            if max_lvl <= 1:
                lv_text, lv_color = str(current_level), _theme.C["text_dim"]
            elif current_level >= max_lvl:
                lv_text, lv_color = tr("collection.skill_max"), _theme.C["green"]
            else:
                lv_text = tr("collection.skill_level", current=current_level, max=max_lvl)
                lv_color = _theme.C["orange"]
            lv_lbl = QLabel(lv_text)
            lv_lbl.setAlignment(Qt.AlignCenter)
            lv_lbl.setStyleSheet(f"font-size: 9pt; font-weight: 600; color: {lv_color};")
            col.addWidget(lv_lbl)

            col_w = QWidget()
            col_w.setLayout(col)
            skills_row.addWidget(col_w)

        skills_row.addStretch()
        root.addLayout(skills_row)

        # â”€â”€ Runes (tabs: PvE / Siege / RTA) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        runes_label = QLabel(tr("collection.detail_runes"))
        runes_label.setStyleSheet(f"font-weight: bold; color: {_theme.C['text']};")
        root.addWidget(runes_label)

        tab_widget = QTabWidget()
        rune_modes = [
            (tr("collection.detail_tab_pve"),   account.equipped_runes_for(unit.unit_id, "pve")),
            (tr("collection.detail_tab_siege"),  account.equipped_runes_for(unit.unit_id, "siege")),
            (tr("collection.detail_tab_rta"),    account.equipped_runes_for(unit.unit_id, "rta")),
        ]
        for tab_label, runes in rune_modes:
            tab_widget.addTab(self._rune_tab(runes), tab_label)
        root.addWidget(tab_widget)

        # â”€â”€ Close button â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _rune_tab(self, runes: list[Rune]) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background: {_theme.C['bg']};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(dp(8), dp(8), dp(8), dp(8))

        table = QTableWidget(6, 11, w)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(True)
        table.setStyleSheet(
            f"QTableWidget {{"
            f" background: {_theme.C['bg']}; color: {_theme.C['text']};"
            f" gridline-color: {_theme.C['card_border']}; font-size: 9pt;"
            f"}}"
            f"QHeaderView::section {{"
            f" background: {_theme.C['card_bg']}; color: {_theme.C['text_dim']};"
            f" border: 0; border-bottom: 1px solid {_theme.C['card_border']};"
            f" padding: {dp(5)}px;"
            f"}}"
        )
        table.setHorizontalHeaderLabels(
            [
                tr("rune_opt.col.slot"),
                tr("rune_opt.col.set"),
                tr("rune_opt.col.quality"),
                tr("rune_opt.col.upgrade"),
                tr("ui.main"),
                tr("ui.prefix"),
                tr("rune_opt.col.substats"),
                tr("rune_opt.col.gem_grind"),
                tr("rune_opt.col.current_eff"),
                tr("rune_opt.col.hero_max_eff"),
                tr("rune_opt.col.legend_max_eff"),
            ]
        )
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(9, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(10, QHeaderView.ResizeToContents)

        by_slot: Dict[int, Rune] = {r.slot_no: r for r in runes}
        for row, slot in enumerate(range(1, 7)):
            rune = by_slot.get(slot)
            slot_item = QTableWidgetItem(tr("collection.detail_slot", n=slot))
            slot_item.setForeground(QColor(_theme.C["text_dim"]))
            table.setItem(row, 0, slot_item)
            if rune is None:
                for col in range(1, 11):
                    table.setItem(row, col, QTableWidgetItem(tr("collection.detail_rune_empty")))
                continue

            set_name = SET_NAMES.get(rune.set_id, f"Set {rune.set_id}")
            main_stat = _stat_label(rune.pri_eff[0], rune.pri_eff[1]) if rune.pri_eff else "-"
            has_prefix = (
                rune.prefix_eff
                and len(rune.prefix_eff) >= 2
                and int(rune.prefix_eff[0] or 0) > 0
                and int(rune.prefix_eff[1] or 0) > 0
            )
            prefix_stat = _stat_label(rune.prefix_eff[0], rune.prefix_eff[1]) if has_prefix else "-"
            substats = _substats_text(rune) or "-"

            table.setItem(row, 1, QTableWidgetItem(str(set_name)))
            table.setItem(row, 2, QTableWidgetItem(_quality_text(rune)))
            table.setItem(row, 3, QTableWidgetItem(f"+{int(rune.upgrade_curr or 0)}"))
            main_item = QTableWidgetItem(main_stat)
            main_item.setForeground(QColor(_theme.C["accent"]))
            table.setItem(row, 4, main_item)
            table.setItem(row, 5, QTableWidgetItem(prefix_stat))
            subs_item = QTableWidgetItem(substats)
            subs_item.setToolTip(substats)
            table.setItem(row, 6, subs_item)
            table.setItem(row, 7, QTableWidgetItem(_gem_grind_status(rune)))
            table.setItem(row, 8, QTableWidgetItem(f"{float(rune_efficiency(rune)):.2f}%"))
            table.setItem(row, 9, QTableWidgetItem(f"{float(rune_efficiency_max(rune, 'hero')):.2f}%"))
            table.setItem(row, 10, QTableWidgetItem(f"{float(rune_efficiency_max(rune, 'legend')):.2f}%"))

            for col in (3, 8, 9, 10):
                item = table.item(row, col)
                if item is not None:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            slot_item.setToolTip(f"{tr('ui.rune_id')}: {int(rune.rune_id or 0)}")

        table.resizeRowsToContents()
        layout.addWidget(table)
        return w

    @staticmethod
    def _load_monster_pixmap(info: MonsterInfo, assets_dir: Path) -> Optional[QPixmap]:
        rel = str(info.icon or "").strip()
        if not rel or not assets_dir:
            return None
        p = (assets_dir / rel).resolve()
        return QPixmap(str(p)) if p.exists() else None

    @staticmethod
    def _team_memberships(unit_id: int, account: AccountData) -> List[str]:
        labels: List[str] = []
        if unit_id in account.rta_active_unit_ids():
            labels.append("RTA")
        for idx, team in enumerate(account.siege_def_teams()):
            if unit_id in team:
                labels.append(f"Siege T{idx + 1}")
        if unit_id in account.arena_def_team():
            labels.append("Arena Def")
        for idx, deck in enumerate(account.arena_offense_decks()):
            if unit_id in deck:
                labels.append(f"Arena Off T{idx + 1}")
        return labels


class _MonsterIcon(QWidget):
    """Icon widget that renders a monster icon, a missing-skillup dot, and opens a detail dialog on click."""

    def __init__(
        self,
        pixmap: Optional[QPixmap],
        icon_px: int,
        pad_px: int,
        has_missing_skillups: bool = False,
        skills: Tuple[Tuple[int, int], ...] = (),
        skill_max_levels: Optional[Dict[int, int]] = None,
        skill_icons: Optional[Dict[int, str]] = None,
        skill_names: Optional[Dict[int, str]] = None,
        assets_dir: Optional[Path] = None,
        monster_name: str = "",
        info: Optional["MonsterInfo"] = None,
        unit: Optional[Unit] = None,
        account: Optional[AccountData] = None,
    ):
        super().__init__()
        self._pixmap = pixmap
        self._icon_px = icon_px
        self._pad_px = pad_px
        self._has_missing = has_missing_skillups
        self._skills = skills
        self._skill_max_levels = skill_max_levels or {}
        self._skill_icons = skill_icons or {}
        self._skill_names = skill_names or {}
        self._assets_dir = assets_dir
        self._monster_name = monster_name
        self._info = info
        self._unit = unit
        self._account = account

        size = icon_px + pad_px * 2
        self.setFixedSize(size, size)
        self.setToolTip(monster_name)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Background
        p.fillRect(self.rect(), QColor("#1e1e2e"))
        p.setPen(QColor("#3a3a5a"))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), self._pad_px, self._pad_px)

        # Icon
        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self._icon_px, self._icon_px,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)

        # Missing skillup indicator dot (top-left corner)
        if self._has_missing:
            dot_r = max(4, self._icon_px // 9)
            p.setBrush(QColor(_theme.C["orange"]))
            p.setPen(Qt.NoPen)
            p.drawEllipse(self._pad_px, self._pad_px, dot_r * 2, dot_r * 2)

        p.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._info and self._unit and self._account and self._assets_dir:
            dlg = _MonsterDetailDialog(
                info=self._info,
                unit=self._unit,
                account=self._account,
                skill_max_levels=self._skill_max_levels,
                skill_icons=self._skill_icons,
                skill_names=self._skill_names,
                assets_dir=self._assets_dir,
                parent=self,
            )
            dlg.exec()
        super().mousePressEvent(event)


class MonsterCollectionWidget(QWidget):
    """Small-icon collection overview for owned and missing awakened monsters."""

    _ICON_SIZE = 66
    _ICON_PAD = 1
    _MAX_COLS = 18

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._account: Optional[AccountData] = None
        self._monster_db: Optional[MonsterDB] = None
        self._assets_dir: Optional[Path] = None
        self._missing_unit_ids: Set[int] = set()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(dp(8), dp(8), dp(8), dp(8))
        outer.setSpacing(dp(8))

        # Filter bar: summary label left, checkbox right
        filter_bar = QHBoxLayout()
        filter_bar.setContentsMargins(0, 0, 0, 0)
        filter_bar.setSpacing(dp(12))

        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(f"color: {_theme.C['text_dim']};")
        filter_bar.addWidget(self._summary_label)
        filter_bar.addStretch()

        self._filter_missing_cb = QCheckBox()
        self._filter_missing_cb.setChecked(False)
        self._filter_missing_cb.toggled.connect(self._rebuild)
        filter_bar.addWidget(self._filter_missing_cb)

        outer.addLayout(filter_bar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ border: 1px solid {_theme.C['card_border']}; border-radius: {dp(8)}px; background: {_theme.C['bg']}; }}"
        )
        outer.addWidget(self._scroll, 1)

        self._container = QWidget()
        self._container.setStyleSheet(f"background: {_theme.C['bg']};")
        self._content = QVBoxLayout(self._container)
        self._content.setContentsMargins(dp(8), dp(8), dp(8), dp(8))
        self._content.setSpacing(dp(12))
        self._scroll.setWidget(self._container)

        self._rebuild()

    def set_context(self, account: Optional[AccountData], monster_db: MonsterDB, assets_dir: Path) -> None:
        self._account = account
        self._monster_db = monster_db
        self._assets_dir = Path(assets_dir)
        self._rebuild()

    def retranslate(self) -> None:
        self._rebuild()

    def _clear_content(self) -> None:
        while self._content.count():
            item = self._content.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _rebuild(self) -> None:
        self._filter_missing_cb.setText(tr("collection.filter_missing_skillups"))

        self._clear_content()

        if not self._account or not self._monster_db:
            self._summary_label.setText(tr("collection.no_import"))
            hint = QLabel(tr("collection.no_import"))
            hint.setStyleSheet(f"color: {_theme.C['text_dim']};")
            hint.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self._content.addWidget(hint)
            self._content.addStretch(1)
            return

        # Merge skill max levels: MonsterDB (from skill_defs.json) + snapshot override
        merged_skill_max: Dict[int, int] = {}
        if self._monster_db:
            merged_skill_max.update(self._monster_db.skill_max_levels)
        merged_skill_max.update(self._account.skill_max_levels)
        merged_skill_icons: Dict[int, str] = {}
        if self._monster_db:
            merged_skill_icons.update(self._monster_db.skill_icons)
        merged_skill_icons.update(self._account.skill_icons)
        merged_skill_names: Dict[int, str] = {}
        if self._monster_db:
            merged_skill_names.update(self._monster_db.skill_names)
        self._merged_skill_max = merged_skill_max
        self._merged_skill_icons = merged_skill_icons
        self._merged_skill_names = merged_skill_names

        # Determine which unit IDs have missing skillups
        self._missing_unit_ids = {
            u.unit_id
            for u in self._account.units_by_id.values()
            if _unit_has_missing_skillups(u, merged_skill_max)
        }

        units = self._owned_6star_awakened_units()

        # Apply filter
        if self._filter_missing_cb.isChecked():
            units = [(info, u) for info, u in units if u.unit_id in self._missing_unit_ids]

        self._summary_label.setText(
            tr("collection.summary_owned", owned=len(units))
        )

        self._add_icon_section(
            title=tr("collection.section_owned"),
            units=units,
        )
        self._content.addStretch(1)

    def _owned_6star_awakened_units(self) -> List[Tuple[MonsterInfo, Unit]]:
        if not self._account or not self._monster_db:
            return []
        result: List[Tuple[MonsterInfo, Unit]] = []
        for unit in (self._account.units_by_id or {}).values():
            if int(getattr(unit, "unit_class", 0) or 0) < 6:
                continue
            mid = int(getattr(unit, "unit_master_id", 0) or 0)
            if mid <= 0:
                continue
            info = self._monster_db.get(mid)
            if info is None:
                continue
            if int(info.awaken_level or 0) <= 0:
                continue
            if int(info.natural_stars or 0) <= 0:
                continue
            result.append((info, unit))
        _elem = self._ELEMENT_ORDER
        return sorted(result, key=lambda x: (
            -int(x[0].natural_stars or 0),
            _elem.get(str(x[0].element or "").lower(), 99),
            str(x[0].name or "").lower(),
            int(x[0].com2us_id or 0),
            int(x[1].unit_id or 0),
        ))

    _ELEMENT_ORDER = {"fire": 0, "water": 1, "wind": 2, "light": 3, "dark": 4}

    def _add_icon_section(
        self,
        *,
        title: str,
        units: List[Tuple[MonsterInfo, Unit]],
    ) -> None:
        section = QFrame()
        section.setObjectName("CollectionSection")
        section.setStyleSheet(
            f"QFrame#CollectionSection {{ background: {_theme.C['card_bg']}; border: 1px solid {_theme.C['card_border']}; border-radius: {dp(8)}px; }}"
        )
        lay = QVBoxLayout(section)
        lay.setContentsMargins(dp(10), dp(10), dp(10), dp(10))
        lay.setSpacing(dp(8))

        hdr = QLabel(title)
        hdr.setStyleSheet(f"color: {_theme.C['text']}; font-weight: bold; background: transparent;")
        lay.addWidget(hdr)

        if not units:
            empty = QLabel(tr("collection.none"))
            empty.setStyleSheet(f"color: {_theme.C['text_dim']};")
            lay.addWidget(empty)
            self._content.addWidget(section)
            return

        by_nat: Dict[int, List[Tuple[MonsterInfo, Unit]]] = {}
        for info, unit in units:
            nat = int(info.natural_stars or 0)
            by_nat.setdefault(nat, []).append((info, unit))

        skill_max = getattr(self, "_merged_skill_max", {})

        for nat in sorted(by_nat.keys(), reverse=True):
            nat_units = by_nat[nat]

            missing_total = sum(_count_missing_skillups(u, skill_max) for _, u in nat_units)

            if missing_total > 0:
                nat_text = tr("collection.nat_group_devilmons", stars=int(nat), count=missing_total)
            else:
                nat_text = tr("collection.nat_group", stars=int(nat))
            row_label = QLabel(nat_text)
            row_label.setStyleSheet(f"color: {_theme.C['text_dim']}; background: transparent;")
            lay.addWidget(row_label)

            grid_host = QWidget()
            grid_host.setStyleSheet("background: transparent;")
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(dp(1))
            grid.setVerticalSpacing(dp(1))

            for idx, (info, unit) in enumerate(by_nat[nat]):
                r = idx // int(self._MAX_COLS)
                c = idx % int(self._MAX_COLS)
                grid.addWidget(self._icon_label_for(info, unit), r, c)
            lay.addWidget(grid_host)

        self._content.addWidget(section)

    def _icon_label_for(self, info: MonsterInfo, unit: Unit) -> QWidget:
        icon_px = dp(self._ICON_SIZE)
        pad_px = dp(self._ICON_PAD)

        has_missing = unit.unit_id in self._missing_unit_ids
        skill_max_levels = getattr(self, "_merged_skill_max", {})
        skill_icons = getattr(self, "_merged_skill_icons", {})
        skill_names = getattr(self, "_merged_skill_names", {})

        return _MonsterIcon(
            pixmap=self._monster_pixmap(info),
            icon_px=icon_px,
            pad_px=pad_px,
            has_missing_skillups=has_missing,
            skills=unit.skills,
            skill_max_levels=skill_max_levels,
            skill_icons=skill_icons,
            skill_names=skill_names,
            assets_dir=self._assets_dir,
            monster_name=str(info.name or ""),
            info=info,
            unit=unit,
            account=self._account,
        )

    def _monster_pixmap(self, info: MonsterInfo) -> Optional[QPixmap]:
        if not self._assets_dir:
            return None
        rel = str(info.icon or "").strip()
        if not rel:
            return None
        p = (Path(self._assets_dir) / rel).resolve()
        if not p.exists():
            return None
        return QPixmap(str(p))

