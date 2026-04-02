from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from PySide6.QtCore import Qt, QRect, QPoint, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from desktop_app.domain.models import AccountData, Unit
from desktop_app.domain.monster_db import MonsterDB, MonsterInfo
from desktop_app.i18n import tr
from desktop_app.ui import theme as _theme
from desktop_app.ui.dpi import dp


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


class _SkillPopup(QFrame):
    """Frameless floating popup showing skill icons and levels for a monster."""

    _ICON_SIZE = 52

    def __init__(self) -> None:
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)  # type: ignore[arg-type]
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(
            f"QFrame {{ background: {_theme.C['popup_bg']}; "
            f"border: 1px solid {_theme.C['popup_border']}; "
            f"border-radius: {dp(6)}px; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(dp(10), dp(8), dp(10), dp(8))
        lay.setSpacing(dp(5))

        self._name_label = QLabel()
        self._name_label.setStyleSheet(
            f"color: {_theme.C['text']}; font-weight: bold; background: transparent; border: none;"
        )
        lay.addWidget(self._name_label)

        self._skills_widget = QWidget()
        self._skills_widget.setStyleSheet("background: transparent;")
        self._skills_row = QHBoxLayout(self._skills_widget)
        self._skills_row.setContentsMargins(0, 0, 0, 0)
        self._skills_row.setSpacing(dp(8))
        lay.addWidget(self._skills_widget)

    def populate(
        self,
        monster_name: str,
        skills: Tuple[Tuple[int, int], ...],
        skill_max_levels: Dict[int, int],
        skill_icons: Dict[int, str],
        skill_names: Dict[int, str],
        assets_dir: Path,
    ) -> None:
        while self._skills_row.count():
            item = self._skills_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._name_label.setText(monster_name)

        icon_size = dp(self._ICON_SIZE)
        col_width = max(icon_size, dp(70))

        for skill_id, current_level in skills:
            max_lvl = skill_max_levels.get(skill_id, 0)

            col_widget = QWidget()
            col_widget.setFixedWidth(col_width)
            col_widget.setStyleSheet("background: transparent;")
            col = QVBoxLayout(col_widget)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(dp(2))
            col.setAlignment(Qt.AlignHCenter)

            # Skill icon
            icon_lbl = QLabel()
            icon_lbl.setFixedSize(icon_size, icon_size)
            icon_lbl.setAlignment(Qt.AlignCenter)
            icon_lbl.setStyleSheet("background: transparent; border: none;")
            icon_filename = skill_icons.get(skill_id, "")
            if icon_filename and assets_dir:
                base = icon_filename.removesuffix(".png")
                icon_path = assets_dir / "skills" / f"{base}.png"
                if icon_path.exists():
                    px = QPixmap(str(icon_path)).scaled(
                        icon_size, icon_size,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                    icon_lbl.setPixmap(px)
            col.addWidget(icon_lbl, 0, Qt.AlignHCenter)

            # Skill name
            skill_name = skill_names.get(skill_id, "")
            if skill_name:
                name_lbl = QLabel(skill_name)
                name_lbl.setAlignment(Qt.AlignCenter)
                name_lbl.setWordWrap(True)
                name_lbl.setFixedWidth(col_width)
                name_lbl.setStyleSheet(
                    f"color: {_theme.C['text']}; font-size: 8pt; background: transparent; border: none;"
                )
                col.addWidget(name_lbl, 0, Qt.AlignHCenter)

            # Level label
            if max_lvl <= 1:
                level_text = f"{current_level}"
                color = _theme.C["text_dim"]
            elif current_level >= max_lvl:
                level_text = tr("collection.skill_max")
                color = _theme.C["green"]
            else:
                level_text = tr("collection.skill_level", current=current_level, max=max_lvl)
                color = _theme.C["orange"]

            lv_lbl = QLabel(level_text)
            lv_lbl.setAlignment(Qt.AlignCenter)
            lv_lbl.setStyleSheet(
                f"color: {color}; font-size: 8pt; background: transparent; border: none;"
            )
            col.addWidget(lv_lbl, 0, Qt.AlignHCenter)

            self._skills_row.addWidget(col_widget)

    def show_near(self, global_pos: QPoint) -> None:
        self.adjustSize()
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        x = global_pos.x() + dp(14)
        y = global_pos.y() + dp(14)
        sz = self.sizeHint()
        if avail:
            if x + sz.width() > avail.right():
                x = global_pos.x() - sz.width() - dp(6)
            if y + sz.height() > avail.bottom():
                y = global_pos.y() - sz.height() - dp(6)
            x = max(avail.left(), x)
            y = max(avail.top(), y)
        self.move(x, y)
        self.show()


class _MonsterIcon(QWidget):
    """Icon widget that optionally renders a count badge, a missing-skillup dot, and a hover popup."""

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
        self._popup: Optional[_SkillPopup] = None

        size = icon_px + pad_px * 2
        self.setFixedSize(size, size)
        if not skills:
            self.setToolTip(monster_name)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(100)
        self._hide_timer.timeout.connect(self._on_hide_timer)

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

    def enterEvent(self, event) -> None:
        self._hide_timer.stop()
        if self._skills and self._assets_dir:
            if self._popup is None:
                self._popup = _SkillPopup()
            self._popup.populate(
                self._monster_name,
                self._skills,
                self._skill_max_levels,
                self._skill_icons,
                self._skill_names,
                self._assets_dir,
            )
            self._popup.show_near(QCursor.pos())
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hide_timer.start()
        super().leaveEvent(event)

    def _on_hide_timer(self) -> None:
        if self._popup:
            self._popup.hide()


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
