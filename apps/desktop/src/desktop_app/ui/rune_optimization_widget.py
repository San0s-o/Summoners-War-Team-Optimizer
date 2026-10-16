from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop_app.domain.models import AccountData, Rune
from desktop_app.domain.presets import SET_NAMES, EFFECT_ID_TO_MAINSTAT_KEY
from desktop_app.engine.efficiency import rune_efficiency, rune_efficiency_max
from desktop_app.i18n import tr
from desktop_app.ui.dpi import dp
from desktop_app.ui import theme as _theme
from desktop_app.ui.siege_cards_widget import _RUNE_QUALITY_BORDER, _rune_rich_tooltip
from desktop_app.ui.widgets.card_grid import (
    CardDelegate,
    CardGridView,
    CardListModel,
    draw_badge,
    draw_card_frame,
    draw_eff_bar,
    draw_portrait,
    draw_text,
    eff_colour,
    filter_bar,
    font,
)
from desktop_app.ui.widgets.selection_combos import _UnitSearchComboBox

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

# (i18n key of the sort entry, key function); every sort is descending except set/slot.
_SORTS: List[Tuple[str, Callable[["_RuneRow"], object], bool]] = [
    ("rune_opt.col.current_eff", lambda r: r.eff, True),
    ("rune_opt.col.hero_max_eff", lambda r: r.hero_max, True),
    ("rune_opt.col.legend_max_eff", lambda r: r.legend_max, True),
    ("rune_opt.col.hero_potential", lambda r: r.hero_max - r.eff, True),
    ("rune_opt.col.legend_potential", lambda r: r.legend_max - r.eff, True),
    ("rune_opt.col.set", lambda r: (r.set_name, -r.eff), False),
    ("rune_opt.col.slot", lambda r: (int(r.rune.slot_no or 0), -r.eff), False),
]


def _set_name_for(rune: Rune) -> str:
    sid = int(rune.set_id or 0)
    return str(SET_NAMES.get(sid, f"Set {sid}"))


def _quality_class_id(rune: Rune) -> int:
    origin = int(getattr(rune, "origin_class", 0) or 0)
    return origin if origin else int(rune.rune_class or 0)


def _quality_text(rune: Rune) -> str:
    cls_id = _quality_class_id(rune)
    base = _QUALITY_BASE_NAME.get(cls_id, f"{tr('ui.class_short')} {cls_id}")
    if cls_id in _ANCIENT_CLASS_IDS:
        return tr("rune_opt.quality_ancient", quality=base)
    return base


_PCT_KEYS = {"HP%", "ATK%", "DEF%", "CR", "CD", "RES", "ACC"}


def _stat_name(eff_id: int) -> str:
    key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(eff_id or 0), f"Eff {int(eff_id or 0)}")
    base = key.rstrip("%")
    translated = tr("card_stat." + base)
    return translated if not translated.startswith("card_stat.") else base


def _pct_suffix(eff_id: int) -> str:
    key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(eff_id or 0), "")
    return "%" if key in _PCT_KEYS else ""


def _stat_text(eff_id: int, value: int) -> str:
    return f"{_stat_name(eff_id)} +{int(value)}{_pct_suffix(eff_id)}"


@dataclass
class _Sub:
    text: str          # "CR +12%" incl. grind
    grind: str = ""    # "(+7%)" shown in orange
    gem: bool = False


@dataclass
class _RuneRow:
    rune: Rune
    eff: float
    hero_max: float
    legend_max: float
    set_name: str
    quality: str
    quality_colour: QColor
    main: str
    innate: str
    subs: List[_Sub] = field(default_factory=list)
    monster_uid: int = 0
    monster: str = ""
    search: str = ""


def _build_row(rune: Rune, monster_name: str) -> _RuneRow:
    subs: List[_Sub] = []
    for sec in (rune.sec_eff or []):
        if not sec:
            continue
        eff_id = int(sec[0] or 0)
        base = int(sec[1] or 0) if len(sec) > 1 else 0
        gem = bool(int(sec[2] or 0)) if len(sec) > 2 else False
        grind = int(sec[3] or 0) if len(sec) > 3 else 0
        subs.append(_Sub(_stat_text(eff_id, base + grind), f"(+{grind}{_pct_suffix(eff_id)})" if grind else "", gem))
    main = _stat_text(int(rune.pri_eff[0] or 0), int(rune.pri_eff[1] or 0)) if rune.pri_eff else ""
    innate = ""
    if rune.prefix_eff and int(rune.prefix_eff[0] or 0):
        innate = _stat_text(int(rune.prefix_eff[0] or 0), int(rune.prefix_eff[1] or 0))
    row = _RuneRow(
        rune=rune,
        eff=float(rune_efficiency(rune)),
        hero_max=float(rune_efficiency_max(rune, "hero")),
        legend_max=float(rune_efficiency_max(rune, "legend")),
        set_name=_set_name_for(rune),
        quality=_quality_text(rune),
        quality_colour=QColor(_RUNE_QUALITY_BORDER.get(_quality_class_id(rune), "#555555")),
        main=main,
        innate=innate,
        subs=subs,
        monster_uid=int(rune.occupied_id or 0) if int(rune.occupied_type or 0) == 1 else 0,
        monster=monster_name,
    )
    row.search = " ".join([row.set_name, row.quality, main, innate, monster_name] + [s.text for s in subs]).lower()
    return row


def _row_tooltip(row: _RuneRow) -> str:
    return (
        _rune_rich_tooltip(row.rune)
        + "<br><br>"
        + f"{tr('rune_opt.col.current_eff')}: <b>{row.eff:.2f}%</b><br>"
        + f"{tr('rune_opt.col.hero_max_eff')}: {row.hero_max:.2f}% "
        + f"({tr('rune_opt.col.hero_potential')} +{max(0.0, row.hero_max - row.eff):.2f}%)<br>"
        + f"{tr('rune_opt.col.legend_max_eff')}: {row.legend_max:.2f}% "
        + f"({tr('rune_opt.col.legend_potential')} +{max(0.0, row.legend_max - row.eff):.2f}%)"
    )


class _RuneCardDelegate(CardDelegate):
    def __init__(self, view: CardGridView, set_icon_fn, monster_icon_fn):
        super().__init__(view)
        self._set_icon_fn = set_icon_fn
        self._monster_icon_fn = monster_icon_fn

    def paint_card(self, p: QPainter, rect, row: _RuneRow, hovered: bool, base: QFont) -> None:
        c = _theme.C
        text, dim = QColor(c["text"]), QColor(c["text_dim"])
        r = draw_card_frame(p, rect, row.quality_colour, hovered)
        x, y, w = r.left(), r.top(), r.width()

        # header: set badge, set + quality, level + slot
        badge = dp(42)
        icon = self._set_icon_fn(int(row.rune.set_id or 0)) if self._set_icon_fn else QIcon()
        draw_badge(p, QRectF(x, y, badge, badge), icon, row.quality_colour)
        tx = x + badge + dp(10)
        right_w = dp(64)
        draw_text(p, QRectF(tx, y, w - badge - dp(10) - right_w, badge / 2), row.set_name, font(base, 1.5, True), text)
        draw_text(p, QRectF(tx, y + badge / 2, w - badge - dp(10) - right_w, badge / 2), row.quality,
                  font(base, -0.5), row.quality_colour)
        draw_text(p, QRectF(r.right() - right_w, y, right_w, badge / 2), f"+{int(row.rune.upgrade_curr or 0)}",
                  font(base, 1.5, True), text, Qt.AlignRight | Qt.AlignVCenter)
        draw_text(p, QRectF(r.right() - right_w, y + badge / 2, right_w, badge / 2),
                  f"{tr('ui.slot')} {int(row.rune.slot_no or 0)}", font(base, -0.5), dim, Qt.AlignRight | Qt.AlignVCenter)

        # main stat (+ innate)
        y += badge + dp(8)
        line_h = dp(22)
        main_w = draw_text(p, QRectF(x, y, w, line_h), row.main, font(base, 2.0, True), text)
        if row.innate:
            draw_text(p, QRectF(x + main_w + dp(12), y, w - main_w - dp(12), line_h), row.innate, font(base, -0.5), dim,
                      Qt.AlignRight | Qt.AlignVCenter)
        y += line_h + dp(4)
        p.setPen(QPen(QColor(c["card_border"]), 1))
        p.drawLine(int(x), int(y), int(r.right()), int(y))
        y += dp(5)

        # substats: gems in teal, grinds as orange suffix
        sub_h = dp(19)
        teal, orange = QColor("#1abc9c"), QColor(c["orange"])
        sub_font = font(base, 0.0)
        for sub in row.subs[:4]:
            colour = teal if sub.gem else text
            sw = draw_text(p, QRectF(x, y, w, sub_h), ("◆ " if sub.gem else "• ") + sub.text, sub_font, colour)
            if sub.grind:
                draw_text(p, QRectF(x + sw + dp(5), y, w - sw - dp(5), sub_h), sub.grind, font(base, -0.5), orange)
            y += sub_h

        # footer: wearer + efficiency, bar with the Legend-max reach
        bar_h = dp(6)
        foot_h = dp(24)
        fy = r.bottom() - bar_h - dp(6) - foot_h
        eff_w = dp(76)
        if row.monster_uid and self._monster_icon_fn:
            draw_portrait(p, QRectF(x, fy, foot_h, foot_h), self._monster_icon_fn(row.monster_uid))
            draw_text(p, QRectF(x + foot_h + dp(8), fy, w - foot_h - dp(8) - eff_w, foot_h), row.monster, font(base), text)
        draw_text(p, QRectF(r.right() - eff_w, fy, eff_w, foot_h), f"{row.eff:.1f}%", font(base, 3.0, True),
                  eff_colour(row.eff), Qt.AlignRight | Qt.AlignVCenter)
        max_w = dp(70)
        draw_eff_bar(p, QRectF(x, r.bottom() - bar_h, w - max_w - dp(8), bar_h), row.eff, row.legend_max)
        draw_text(p, QRectF(r.right() - max_w, r.bottom() - dp(14), max_w, dp(14)),
                  tr("rune_opt.card_max", v=f"{row.legend_max:.1f}"), font(base, -1.0), dim, Qt.AlignRight | Qt.AlignVCenter)


class RuneOptimizationWidget(QWidget):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        rune_set_icon_fn: Callable[[int], QIcon] | None = None,
        monster_name_fn: Callable[[int], str] | None = None,
        monster_icon_fn: Callable[[int], QIcon] | None = None,
    ):
        super().__init__(parent)
        self._account: Optional[AccountData] = None
        self._rune_set_icon_fn = rune_set_icon_fn
        self._monster_name_fn = monster_name_fn
        self._updating_filters = False
        self._search_text: str = ""
        self._rows: List[_RuneRow] = []  # all +12 runes, built once per account

        layout = QVBoxLayout(self)
        layout.setContentsMargins(dp(8), dp(8), dp(8), dp(8))
        layout.setSpacing(dp(8))

        self._search_box = QLineEdit()
        self._search_box.textChanged.connect(self._on_search_changed)
        filter_frame, fb = filter_bar(self._search_box)

        def _dim_label() -> QLabel:
            lbl = QLabel("")
            fb.addWidget(lbl)
            return lbl

        self.lbl_filter_set = _dim_label()
        self.combo_filter_set = QComboBox()
        self.combo_filter_set.setMinimumWidth(dp(150))
        self.combo_filter_set.currentIndexChanged.connect(self._on_filters_changed)
        fb.addWidget(self.combo_filter_set)

        self.lbl_filter_slot = _dim_label()
        self.combo_filter_slot = QComboBox()
        self.combo_filter_slot.setMinimumWidth(dp(80))
        self.combo_filter_slot.currentIndexChanged.connect(self._on_filters_changed)
        fb.addWidget(self.combo_filter_slot)

        self.lbl_filter_monster = _dim_label()
        self.combo_filter_monster = _UnitSearchComboBox()
        self.combo_filter_monster.setMinimumWidth(dp(190))
        self.combo_filter_monster.currentIndexChanged.connect(self._on_filters_changed)
        fb.addWidget(self.combo_filter_monster)

        self.lbl_sort = _dim_label()
        self.combo_sort = QComboBox()
        self.combo_sort.setMinimumWidth(dp(170))
        self.combo_sort.currentIndexChanged.connect(self._on_filters_changed)
        fb.addWidget(self.combo_sort)

        self.btn_reset_filters = QPushButton("")
        self.btn_reset_filters.setProperty("ghost", True)
        self.btn_reset_filters.clicked.connect(self._on_reset_filters)
        fb.addWidget(self.btn_reset_filters)

        fb.addStretch(1)

        self.lbl_info = QLabel("")
        fb.addWidget(self.lbl_info)

        layout.addWidget(filter_frame)

        self.view = CardGridView(min_card_width=dp(300), card_height=dp(222))
        self.model = CardListModel(_row_tooltip, self.view)
        self.view.setModel(self.model)
        self.view.setItemDelegate(_RuneCardDelegate(self.view, rune_set_icon_fn, monster_icon_fn))
        layout.addWidget(self.view, 1)

        self.retranslate()

    def retranslate(self) -> None:
        self.lbl_filter_set.setText(tr("rune_opt.filter_set"))
        self.lbl_filter_slot.setText(tr("rune_opt.filter_slot"))
        self.lbl_filter_monster.setText(tr("rune_opt.filter_monster"))
        self.lbl_sort.setText(tr("rune_opt.sort_label"))
        self.btn_reset_filters.setText(tr("rune_opt.filter_reset"))
        self._search_box.setPlaceholderText(tr("rune_opt.search_placeholder"))
        current_sort = max(0, self.combo_sort.currentIndex())
        self.combo_sort.blockSignals(True)
        self.combo_sort.clear()
        for key, _fn, _desc in _SORTS:
            self.combo_sort.addItem(tr(key))
        self.combo_sort.setCurrentIndex(current_sort)
        self.combo_sort.blockSignals(False)
        self.set_account(self._account)  # rows hold translated texts

    def set_account(self, account: Optional[AccountData]) -> None:
        self._account = account
        runes = [r for r in (account.runes if account else []) if int(r.upgrade_curr or 0) >= 12]
        name_fn = self._monster_name_fn or (lambda _uid: "")
        self._rows = [
            _build_row(r, name_fn(int(r.occupied_id or 0)) if int(r.occupied_type or 0) == 1 else "")
            for r in runes
        ]
        self._populate_filters()
        self.refresh()

    def _on_filters_changed(self, _index: int) -> None:
        if self._updating_filters:
            return
        self.refresh()

    def _on_reset_filters(self) -> None:
        self._updating_filters = True
        self.combo_filter_set.blockSignals(True)
        self.combo_filter_slot.blockSignals(True)
        self.combo_filter_monster.blockSignals(True)
        try:
            self.combo_filter_set.setCurrentIndex(0)
            self.combo_filter_slot.setCurrentIndex(0)
            self.combo_filter_monster.set_filter_suspended(True)
            self.combo_filter_monster.setCurrentIndex(0)
            self.combo_filter_monster.set_filter_suspended(False)
            self.combo_filter_monster._reset_search_field()
        finally:
            self.combo_filter_set.blockSignals(False)
            self.combo_filter_slot.blockSignals(False)
            self.combo_filter_monster.blockSignals(False)
            self._updating_filters = False
        self.refresh()

    def _populate_filters(self) -> None:
        current_set = int(self.combo_filter_set.currentData() or 0)
        current_slot = int(self.combo_filter_slot.currentData() or 0)
        current_monster_uid = int(self.combo_filter_monster.currentData(Qt.UserRole) or 0)
        set_ids = sorted({int(r.rune.set_id or 0) for r in self._rows if int(r.rune.set_id or 0) > 0},
                         key=lambda sid: str(SET_NAMES.get(sid, sid)))
        slot_nos = sorted({int(r.rune.slot_no or 0) for r in self._rows if int(r.rune.slot_no or 0) > 0})

        monster_model = QStandardItemModel()
        all_item = QStandardItem(tr("rune_opt.filter_all"))
        all_item.setData(0, Qt.UserRole)
        monster_model.appendRow(all_item)
        for uid, name in sorted({(r.monster_uid, r.monster) for r in self._rows if r.monster_uid}, key=lambda x: x[1]):
            item = QStandardItem(name)
            item.setData(uid, Qt.UserRole)
            monster_model.appendRow(item)

        self._updating_filters = True
        self.combo_filter_set.blockSignals(True)
        self.combo_filter_slot.blockSignals(True)
        self.combo_filter_monster.blockSignals(True)
        try:
            self.combo_filter_set.clear()
            self.combo_filter_set.addItem(tr("rune_opt.filter_all"), 0)
            for sid in set_ids:
                icon = self._rune_set_icon_fn(sid) if self._rune_set_icon_fn else QIcon()
                self.combo_filter_set.addItem(icon, str(SET_NAMES.get(sid, f"Set {sid}")), sid)
            idx_set = self.combo_filter_set.findData(current_set)
            self.combo_filter_set.setCurrentIndex(idx_set if idx_set >= 0 else 0)

            self.combo_filter_slot.clear()
            self.combo_filter_slot.addItem(tr("rune_opt.filter_all"), 0)
            for slot in slot_nos:
                self.combo_filter_slot.addItem(str(slot), slot)
            idx_slot = self.combo_filter_slot.findData(current_slot)
            self.combo_filter_slot.setCurrentIndex(idx_slot if idx_slot >= 0 else 0)

            self.combo_filter_monster.set_filter_suspended(True)
            self.combo_filter_monster.set_source_model(monster_model)
            idx_monster = self.combo_filter_monster.findData(current_monster_uid, role=Qt.UserRole)
            self.combo_filter_monster.setCurrentIndex(idx_monster if idx_monster >= 0 else 0)
            self.combo_filter_monster.set_filter_suspended(False)
            self.combo_filter_monster._sync_line_edit_to_current()
        finally:
            self.combo_filter_set.blockSignals(False)
            self.combo_filter_slot.blockSignals(False)
            self.combo_filter_monster.blockSignals(False)
            self._updating_filters = False

    def refresh(self) -> None:
        if not self._account:
            self.lbl_info.setText(tr("rune_opt.hint_no_import"))
            self.model.set_rows([])
            return
        if not self._rows:
            self.lbl_info.setText(tr("rune_opt.hint_no_rows"))
            self.model.set_rows([])
            return

        selected_set = int(self.combo_filter_set.currentData() or 0)
        selected_slot = int(self.combo_filter_slot.currentData() or 0)
        selected_uid = int(self.combo_filter_monster.currentData(Qt.UserRole) or 0)
        needle = self._search_text
        rows = [
            r for r in self._rows
            if (selected_set <= 0 or int(r.rune.set_id or 0) == selected_set)
            and (selected_slot <= 0 or int(r.rune.slot_no or 0) == selected_slot)
            and (selected_uid <= 0 or r.monster_uid == selected_uid)
            and (not needle or needle in r.search)
        ]
        _key, key_fn, descending = _SORTS[max(0, self.combo_sort.currentIndex())]
        rows.sort(key=key_fn, reverse=descending)

        if rows:
            self.lbl_info.setText(tr("rune_opt.count_filtered", shown=len(rows), total=len(self._rows)))
        else:
            self.lbl_info.setText(tr("rune_opt.hint_no_filter_rows"))
        self.model.set_rows(rows)
        self.view.scrollToTop()

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self.refresh()
