from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
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

from desktop_app.domain.models import AccountData, Artifact
from desktop_app.domain.artifact_effects import (
    artifact_rank_label,
    artifact_effect_text,
    ARTIFACT_MAIN_FOCUS_BY_EFFECT_ID,
)
from desktop_app.engine.efficiency import artifact_efficiency
from desktop_app.i18n import tr
from desktop_app.ui import theme as _theme
from desktop_app.ui.dpi import dp
from desktop_app.ui.siege_cards_widget import (
    _RUNE_QUALITY_BORDER,
    _artifact_center_slug,
    _artifact_quality_tier,
    _artifact_rich_tooltip,
    _artifact_type_icon,
)
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


_ASSETS_UI = Path(__file__).resolve().parents[1] / "assets" / "ui"


@lru_cache(maxsize=None)
def _symbol_icon(type_id: int, tier: str, slug: str) -> QIcon:
    """Element/archetype symbol in the quality's colour (flame, swirl, sword, ...)."""
    path = _ASSETS_UI / f"conversion_{slug}_{tier}.png"
    if slug and path.exists():
        return QIcon(str(path))
    return _artifact_type_icon(type_id, tier)


def _type_text(art: Artifact) -> str:
    t = int(art.type_ or 0)
    if t == 1:
        return tr("art_opt.type_attribute")
    if t == 2:
        return tr("art_opt.type_type")
    return f"Typ {t}"


def _rank(art: Artifact) -> int:
    rank = int(getattr(art, "original_rank", 0) or 0)
    return rank if rank > 0 else int(art.rank or 0)


def _mainstat_text(art: Artifact) -> str:
    if not art.pri_effect or len(art.pri_effect) < 2:
        return ""
    eid = int(art.pri_effect[0] or 0)
    val = art.pri_effect[1]
    focus = ARTIFACT_MAIN_FOCUS_BY_EFFECT_ID.get(eid)
    if focus:
        try:
            v = float(val)
            val_str = str(int(v)) if abs(v - int(v)) < 1e-9 else f"{v:.1f}"
            return f"{focus} +{val_str}"
        except Exception:
            return f"{focus} +{val}"
    return artifact_effect_text(eid, val)


@dataclass
class _ArtRow:
    art: Artifact
    eff: float
    title: str              # "Attribut · Feuer"
    quality: str
    quality_colour: QColor
    icon: QIcon
    main: str
    subs: List[Tuple[str, int, bool]] = field(default_factory=list)  # (text, rolls, swapped)
    monster_uid: int = 0
    monster: str = ""
    search: str = ""


# (i18n key of the sort entry, key function, descending)
_SORTS: List[Tuple[str, Callable[[_ArtRow], object], bool]] = [
    ("art_opt.col.efficiency", lambda r: r.eff, True),
    ("art_opt.col.quality", lambda r: (_rank(r.art), r.eff), True),
    ("art_opt.col.level", lambda r: (int(r.art.level or 0), r.eff), True),
    ("art_opt.col.type", lambda r: (int(r.art.type_ or 0), -r.eff), False),
]


def _build_row(art: Artifact, monster_name: str) -> _ArtRow:
    subs: List[Tuple[str, int, bool]] = []
    for sec in (art.sec_effects or []):
        if not sec or len(sec) < 2:
            continue
        rolls = int(sec[2] or 0) if len(sec) > 2 else 0
        swapped = bool(int(sec[3] or 0)) if len(sec) > 3 else False
        subs.append((artifact_effect_text(int(sec[0] or 0), sec[1]), rolls, swapped))
    slug = _artifact_center_slug(art)
    center = tr(f"art_opt.center.{slug}") if slug else ""
    rank = _rank(art)
    row = _ArtRow(
        art=art,
        eff=float(artifact_efficiency(art)),
        title=" · ".join(x for x in (_type_text(art), center) if x),
        quality=artifact_rank_label(rank),
        quality_colour=QColor(_RUNE_QUALITY_BORDER.get(rank, "#555555")),
        icon=_symbol_icon(int(art.type_ or 0), _artifact_quality_tier(art), slug),
        main=_mainstat_text(art),
        subs=subs,
        monster_uid=int(art.occupied_id or 0),
        monster=monster_name,
    )
    row.search = " ".join([row.title, row.quality, row.main, monster_name] + [s[0] for s in subs]).lower()
    return row


def _row_tooltip(row: _ArtRow) -> str:
    return _artifact_rich_tooltip(row.art) + f"<br><br>{tr('art_opt.col.efficiency')}: <b>{row.eff:.2f}%</b>"


class _ArtifactCardDelegate(CardDelegate):
    def __init__(self, view: CardGridView, monster_icon_fn):
        super().__init__(view)
        self._monster_icon_fn = monster_icon_fn

    def paint_card(self, p: QPainter, rect, row: _ArtRow, hovered: bool, base: QFont) -> None:
        c = _theme.C
        text, dim = QColor(c["text"]), QColor(c["text_dim"])
        r = draw_card_frame(p, rect, row.quality_colour, hovered)
        x, y, w = r.left(), r.top(), r.width()

        badge = dp(44)
        draw_badge(p, QRectF(x, y, badge, badge), row.icon, row.quality_colour, icon_scale=0.78)
        tx = x + badge + dp(10)
        right_w = dp(48)
        draw_text(p, QRectF(tx, y, w - badge - dp(10) - right_w, badge / 2), row.title, font(base, 1.5, True), text)
        draw_text(p, QRectF(tx, y + badge / 2, w - badge - dp(10) - right_w, badge / 2), row.quality,
                  font(base, -0.5), row.quality_colour)
        draw_text(p, QRectF(r.right() - right_w, y, right_w, badge / 2), f"+{int(row.art.level or 0)}",
                  font(base, 1.5, True), text, Qt.AlignRight | Qt.AlignVCenter)

        y += badge + dp(8)
        line_h = dp(22)
        draw_text(p, QRectF(x, y, w, line_h), row.main, font(base, 2.0, True), text)
        y += line_h + dp(4)
        p.setPen(QPen(QColor(c["card_border"]), 1))
        p.drawLine(int(x), int(y), int(r.right()), int(y))
        y += dp(5)

        # substats with their upgrade rolls as pips on the right
        sub_h = dp(19)
        pip, pip_gap = dp(6), dp(4)
        pips_w = 4 * (pip + pip_gap)
        teal, accent = QColor("#1abc9c"), QColor(c["accent"])
        for sub_text, rolls, swapped in row.subs[:4]:
            draw_text(p, QRectF(x, y, w - pips_w - dp(6), sub_h), "• " + sub_text, font(base, 0.0), teal if swapped else text)
            p.setPen(Qt.NoPen)
            for i in range(min(rolls, 4)):
                px = r.right() - (4 - i) * (pip + pip_gap) + pip_gap
                p.setBrush(accent)
                p.drawEllipse(QRectF(px, y + (sub_h - pip) / 2, pip, pip))
            y += sub_h

        bar_h = dp(6)
        foot_h = dp(24)
        fy = r.bottom() - bar_h - dp(6) - foot_h
        eff_w = dp(76)
        if row.monster_uid and self._monster_icon_fn:
            draw_portrait(p, QRectF(x, fy, foot_h, foot_h), self._monster_icon_fn(row.monster_uid))
            draw_text(p, QRectF(x + foot_h + dp(8), fy, w - foot_h - dp(8) - eff_w, foot_h), row.monster, font(base), text)
        draw_text(p, QRectF(r.right() - eff_w, fy, eff_w, foot_h), f"{row.eff:.1f}%", font(base, 3.0, True),
                  eff_colour(row.eff), Qt.AlignRight | Qt.AlignVCenter)
        draw_eff_bar(p, QRectF(x, r.bottom() - bar_h, w, bar_h), row.eff)


class ArtifactOptimizationWidget(QWidget):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        monster_name_fn: Callable[[int], str] | None = None,
        monster_icon_fn: Callable[[int], QIcon] | None = None,
    ):
        super().__init__(parent)
        self._account: Optional[AccountData] = None
        self._monster_name_fn = monster_name_fn
        self._updating_filters = False
        self._search_text: str = ""
        self._rows: List[_ArtRow] = []

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

        self.lbl_filter_type = _dim_label()
        self.combo_filter_type = QComboBox()
        self.combo_filter_type.setMinimumWidth(dp(120))
        self.combo_filter_type.currentIndexChanged.connect(self._on_filters_changed)
        fb.addWidget(self.combo_filter_type)

        self.lbl_filter_monster = _dim_label()
        self.combo_filter_monster = _UnitSearchComboBox()
        self.combo_filter_monster.setMinimumWidth(dp(200))
        self.combo_filter_monster.currentIndexChanged.connect(self._on_filters_changed)
        fb.addWidget(self.combo_filter_monster)

        self.lbl_sort = _dim_label()
        self.combo_sort = QComboBox()
        self.combo_sort.setMinimumWidth(dp(140))
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

        self.view = CardGridView(min_card_width=dp(380), card_height=dp(226))
        self.model = CardListModel(_row_tooltip, self.view)
        self.view.setModel(self.model)
        self.view.setItemDelegate(_ArtifactCardDelegate(self.view, monster_icon_fn))
        layout.addWidget(self.view, 1)

        self.retranslate()

    def retranslate(self) -> None:
        self.lbl_filter_type.setText(tr("art_opt.filter_type"))
        self.lbl_filter_monster.setText(tr("art_opt.filter_monster"))
        self.lbl_sort.setText(tr("rune_opt.sort_label"))
        self.btn_reset_filters.setText(tr("art_opt.filter_reset"))
        self._search_box.setPlaceholderText(tr("art_opt.search_placeholder"))
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
        name_fn = self._monster_name_fn or (lambda _uid: "")
        self._rows = [
            _build_row(a, name_fn(int(a.occupied_id or 0)) if int(a.occupied_id or 0) > 0 else "")
            for a in (account.artifacts if account else [])
        ]
        self._populate_filters()
        self.refresh()

    def _on_filters_changed(self, _index: int) -> None:
        if self._updating_filters:
            return
        self.refresh()

    def _on_reset_filters(self) -> None:
        self._updating_filters = True
        self.combo_filter_type.blockSignals(True)
        self.combo_filter_monster.blockSignals(True)
        try:
            self.combo_filter_type.setCurrentIndex(0)
            self.combo_filter_monster.set_filter_suspended(True)
            self.combo_filter_monster.setCurrentIndex(0)
            self.combo_filter_monster.set_filter_suspended(False)
            self.combo_filter_monster._reset_search_field()
        finally:
            self.combo_filter_type.blockSignals(False)
            self.combo_filter_monster.blockSignals(False)
            self._updating_filters = False
        self.refresh()

    def _populate_filters(self) -> None:
        current_type = int(self.combo_filter_type.currentData() or 0)
        current_monster_uid = int(self.combo_filter_monster.currentData(Qt.UserRole) or 0)

        monster_model = QStandardItemModel()
        all_item = QStandardItem(tr("art_opt.filter_all"))
        all_item.setData(0, Qt.UserRole)
        monster_model.appendRow(all_item)
        for uid, name in sorted({(r.monster_uid, r.monster) for r in self._rows if r.monster_uid}, key=lambda x: x[1]):
            item = QStandardItem(name)
            item.setData(uid, Qt.UserRole)
            monster_model.appendRow(item)

        self._updating_filters = True
        self.combo_filter_type.blockSignals(True)
        self.combo_filter_monster.blockSignals(True)
        try:
            self.combo_filter_type.clear()
            self.combo_filter_type.addItem(tr("art_opt.filter_all"), 0)
            self.combo_filter_type.addItem(tr("art_opt.type_attribute"), 1)
            self.combo_filter_type.addItem(tr("art_opt.type_type"), 2)
            idx_type = self.combo_filter_type.findData(current_type)
            self.combo_filter_type.setCurrentIndex(idx_type if idx_type >= 0 else 0)

            self.combo_filter_monster.set_filter_suspended(True)
            self.combo_filter_monster.set_source_model(monster_model)
            idx_monster = self.combo_filter_monster.findData(current_monster_uid, role=Qt.UserRole)
            self.combo_filter_monster.setCurrentIndex(idx_monster if idx_monster >= 0 else 0)
            self.combo_filter_monster.set_filter_suspended(False)
            self.combo_filter_monster._sync_line_edit_to_current()
        finally:
            self.combo_filter_type.blockSignals(False)
            self.combo_filter_monster.blockSignals(False)
            self._updating_filters = False

    def refresh(self) -> None:
        if not self._account:
            self.lbl_info.setText(tr("art_opt.hint_no_import"))
            self.model.set_rows([])
            return
        if not self._rows:
            self.lbl_info.setText(tr("art_opt.hint_no_rows"))
            self.model.set_rows([])
            return

        selected_type = int(self.combo_filter_type.currentData() or 0)
        selected_uid = int(self.combo_filter_monster.currentData(Qt.UserRole) or 0)
        needle = self._search_text
        rows = [
            r for r in self._rows
            if (selected_type <= 0 or int(r.art.type_ or 0) == selected_type)
            and (selected_uid <= 0 or r.monster_uid == selected_uid)
            and (not needle or needle in r.search)
        ]
        _key, key_fn, descending = _SORTS[max(0, self.combo_sort.currentIndex())]
        rows.sort(key=key_fn, reverse=descending)

        if not rows:
            self.lbl_info.setText(tr("art_opt.hint_no_filter_rows"))
        elif len(rows) == len(self._rows):
            self.lbl_info.setText(tr("art_opt.count", n=len(rows)))
        else:
            self.lbl_info.setText(tr("art_opt.count_filtered", shown=len(rows), total=len(self._rows)))
        self.model.set_rows(rows)
        self.view.scrollToTop()

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self.refresh()
