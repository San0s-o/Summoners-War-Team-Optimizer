"""Card grid for rune/artifact inventories: a virtualised QListView plus shared card painting."""
from __future__ import annotations

from typing import Any, Callable, List

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLineEdit, QListView, QStyle, QStyledItemDelegate, QWidget,
)

from desktop_app.ui import theme as _theme
from desktop_app.ui.dpi import dp

# Efficiency bar range in %: wide enough for 130%+ runes, tight enough that 90 vs 100 is visible.
EFF_BAR_MIN = 40.0
EFF_BAR_MAX = 130.0


def filter_bar(search_box: QLineEdit) -> tuple[QFrame, QHBoxLayout]:
    """Toolbar frame shared by the rune/artifact/relic tabs: search field, separator, then filters."""
    c = _theme.C
    frame = QFrame()
    frame.setObjectName("inventoryFilterBar")
    frame.setStyleSheet(
        f"QFrame#inventoryFilterBar {{ background: {c['bg_mid']}; border-radius: {dp(8)}px; border: none; }}"
        f"QFrame#inventoryFilterBar QLabel {{ color: {c['text_dim']}; border: none; background: transparent; }}"
    )
    bar = QHBoxLayout(frame)
    bar.setContentsMargins(dp(10), dp(7), dp(10), dp(7))
    bar.setSpacing(dp(8))
    search_box.setClearButtonEnabled(True)
    search_box.setMinimumWidth(dp(220))
    search_box.setMaximumWidth(dp(400))
    bar.addWidget(search_box)
    sep = QFrame()
    sep.setFrameShape(QFrame.VLine)
    sep.setFixedWidth(1)
    sep.setStyleSheet(f"background: {c['border']}; border: none;")
    bar.addWidget(sep)
    return frame, bar


class CardListModel(QAbstractListModel):
    """Rows are plain Python objects; the delegate reads them from Qt.UserRole."""

    def __init__(self, tooltip_fn: Callable[[Any], str] | None = None, parent=None):
        super().__init__(parent)
        self._rows: List[Any] = []
        self._tooltip_fn = tooltip_fn

    def set_rows(self, rows: List[Any]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role == Qt.UserRole:
            return row
        if role == Qt.ToolTipRole and self._tooltip_fn is not None:
            return self._tooltip_fn(row)  # built on hover only
        return None


class CardGridView(QListView):
    """Wrapping grid whose cards stretch so each row fills the width."""

    def __init__(self, min_card_width: int, card_height: int, parent: QWidget | None = None):
        super().__init__(parent)
        self._min_w = int(min_card_width)
        self._card_h = int(card_height)
        self.gap = dp(10)
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(dp(28))
        self.setFrameShape(QFrame.NoFrame)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WA_Hover, True)
        self.setStyleSheet("QListView { background: transparent; border: none; }")
        self._fit_grid()

    def card_size(self) -> QSize:
        g = self.gridSize()
        return QSize(g.width() - self.gap, g.height() - self.gap)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._fit_grid()
        super().resizeEvent(event)

    def _fit_grid(self) -> None:
        avail = max(self._min_w, self.viewport().width() - dp(2))
        cols = max(1, avail // (self._min_w + self.gap))
        size = QSize(avail // cols, self._card_h + self.gap)
        if size != self.gridSize():
            self.setGridSize(size)


class CardDelegate(QStyledItemDelegate):
    """Base delegate: subclasses implement paint_card(painter, rect, row, hovered)."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        view = self.parent()
        return view.card_size() if isinstance(view, CardGridView) else QSize(dp(300), dp(200))

    def paint(self, painter: QPainter, option, index) -> None:
        row = index.data(Qt.UserRole)
        if row is None:
            return
        view = self.parent()
        size = view.card_size() if isinstance(view, CardGridView) else option.rect.size()
        rect = QRect(option.rect.topLeft(), size)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        try:
            self.paint_card(painter, rect, row, bool(option.state & QStyle.State_MouseOver), option.font)
        finally:
            painter.restore()

    def paint_card(self, p: QPainter, rect: QRect, row: Any, hovered: bool, base_font: QFont) -> None:
        raise NotImplementedError


# ── shared painting helpers ─────────────────────────────────────

def font(base: QFont, delta_pt: float = 0.0, bold: bool = False) -> QFont:
    f = QFont(base)
    if delta_pt:
        f.setPointSizeF(max(6.0, f.pointSizeF() + delta_pt))
    f.setBold(bold)
    return f


def eff_colour(value: float) -> QColor:
    """Same tiers as the old tables: gold >= 120, accent >= 100, green >= 80, dim below."""
    c = _theme.C
    if value >= 120.0:
        return QColor(c["orange"])
    if value >= 100.0:
        return QColor(c["accent"])
    if value >= 80.0:
        return QColor(c["green"])
    return QColor(c["text_dim"])


def draw_card_frame(p: QPainter, rect: QRect, accent: QColor, hovered: bool) -> QRectF:
    """Rounded card with a quality-coloured stripe on the left; returns the content rect."""
    c = _theme.C
    r = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
    radius = dp(10)
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    p.fillPath(path, QColor(c["bg_mid"] if hovered else c["card_bg"]))
    p.save()
    p.setClipPath(path)
    p.fillRect(QRectF(r.left(), r.top(), dp(4), r.height()), accent)
    p.restore()
    p.setPen(QPen(QColor(c["border_hover"] if hovered else c["card_border"]), 1))
    p.drawPath(path)
    pad = dp(12)
    return r.adjusted(pad + dp(4), pad, -pad, -pad)


def draw_badge(p: QPainter, rect: QRectF, icon: QIcon, ring: QColor, icon_scale: float = 0.66) -> None:
    """Rounded square with a coloured ring and a centred icon (rune set glyph / artifact)."""
    c = _theme.C
    path = QPainterPath()
    path.addRoundedRect(rect, dp(8), dp(8))
    p.fillPath(path, QColor(c["bg_input"]))
    if not icon.isNull():
        side = rect.width() * icon_scale
        target = QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
        p.drawPixmap(target.toRect(), icon.pixmap(QSize(int(side * 2), int(side * 2))))
    p.setPen(QPen(ring, 1.5))
    p.drawPath(path)


def draw_portrait(p: QPainter, rect: QRectF, icon: QIcon) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, dp(5), dp(5))
    p.save()
    p.setClipPath(path)
    p.fillPath(path, QColor(_theme.C["bg_input"]))
    if not icon.isNull():
        p.drawPixmap(rect.toRect(), icon.pixmap(QSize(int(rect.width() * 2), int(rect.height() * 2))))
    p.restore()


def draw_text(p: QPainter, rect: QRectF, text: str, f: QFont, colour: QColor,
              align=Qt.AlignLeft | Qt.AlignVCenter) -> float:
    """Draw elided single-line text; returns the drawn width."""
    p.setFont(f)
    p.setPen(colour)
    fm = QFontMetrics(f)
    shown = fm.elidedText(text, Qt.ElideRight, int(rect.width()))
    p.drawText(rect, int(align), shown)
    return float(fm.horizontalAdvance(shown))


def draw_eff_bar(p: QPainter, rect: QRectF, current: float, reachable: float | None = None) -> None:
    """Track + current efficiency; *reachable* (e.g. Legend max) shows as a faded extension."""
    c = _theme.C

    def x_for(v: float) -> float:
        frac = (v - EFF_BAR_MIN) / (EFF_BAR_MAX - EFF_BAR_MIN)
        return rect.left() + rect.width() * max(0.0, min(1.0, frac))

    radius = rect.height() / 2
    track = QPainterPath()
    track.addRoundedRect(rect, radius, radius)
    p.fillPath(track, QColor(c["bg_input"]))
    colour = eff_colour(current)
    p.save()
    p.setClipPath(track)
    if reachable is not None and reachable > current:
        ghost = QColor(colour)
        ghost.setAlpha(70)
        p.fillRect(QRectF(rect.left(), rect.top(), x_for(reachable) - rect.left(), rect.height()), ghost)
    p.fillRect(QRectF(rect.left(), rect.top(), x_for(current) - rect.left(), rect.height()), colour)
    p.restore()
