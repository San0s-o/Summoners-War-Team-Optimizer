from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QBoxLayout, QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from desktop_app.ui import theme as _theme
from desktop_app.ui.dpi import dp
from desktop_app.ui.widgets.selection_combos import _UnitSearchComboBox

# Role on the shared unit-combo model holding the monster's element ("Fire", "Water", ...).
ELEMENT_ROLE = Qt.UserRole + 1


def element_colour(element: str) -> QColor:
    c = _theme.C
    key = {"fire": "elem_fire", "water": "elem_water", "wind": "elem_wind",
           "light": "elem_light", "dark": "elem_dark"}.get(str(element or "").strip().lower())
    return QColor(c[key]) if key else QColor(c["border"])


class _Portrait(QWidget):
    """Rounded monster portrait with an element-coloured ring; '+' when the slot is empty."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._icon = QIcon()
        self._ring = QColor(_theme.C["border"])
        self.setCursor(Qt.PointingHandCursor)

    def set_unit(self, icon: QIcon, ring: QColor) -> None:
        self._icon = icon
        self._ring = ring
        self.update()

    def paintEvent(self, _event) -> None:
        c = _theme.C
        side = min(self.width(), self.height())
        rect = QRectF((self.width() - side) / 2 + 1, (self.height() - side) / 2 + 1, side - 2, side - 2)
        radius = side * 0.16
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.fillPath(path, QColor(c["bg_input"]))
        if not self._icon.isNull():
            p.save()
            p.setClipPath(path)
            p.drawPixmap(rect.toRect(), self._icon.pixmap(QSize(int(side * 2), int(side * 2))))
            p.restore()
            p.setPen(QPen(self._ring, max(2.0, side / 32)))
        else:
            p.setPen(QColor(c["text_dim"]))
            font = QFont(self.font())
            font.setPixelSize(max(12, int(side * 0.45)))
            p.setFont(font)
            p.drawText(rect, Qt.AlignCenter, "+")
            p.setPen(QPen(QColor(c["border"]), 1.5, Qt.DashLine))
        p.drawPath(path)
        p.end()

    def mousePressEvent(self, event) -> None:
        card = self.parent()
        if isinstance(card, UnitSlotCard):
            card.combo.setFocus()
            card.combo.showPopup()
        super().mousePressEvent(event)


class UnitSlotCard(QFrame):
    """Builder slot: big portrait + the existing monster search combo.

    Horizontal cards let the portrait follow the card height, so builder rows grow with the
    window instead of leaving it empty; vertical cards stack a fixed-size portrait above the combo.
    """

    def __init__(self, combo: _UnitSearchComboBox, title: str = "", vertical: bool = False,
                 portrait: int = 112, parent: QWidget | None = None):
        super().__init__(parent)
        self.combo = combo
        self._vertical = bool(vertical)
        self.setObjectName("UnitSlotCard")
        self._portrait = _Portrait(self)
        combo.setMinimumWidth(dp(160))
        combo.show_field_icon = False
        combo.set_unit_icon_size(QSize(dp(40), dp(40)))

        if self._vertical:
            lay = QVBoxLayout(self)
            lay.setContentsMargins(dp(12), dp(10), dp(12), dp(12))
            lay.setSpacing(dp(8))
            if title:
                self.title_label = QLabel(title)
                self.title_label.setObjectName("UnitSlotTitle")
                lay.addWidget(self.title_label)
            self._portrait.setFixedSize(dp(portrait), dp(portrait))
            lay.addWidget(self._portrait, 0, Qt.AlignHCenter)
            lay.addWidget(combo)
        else:
            lay = QBoxLayout(QBoxLayout.LeftToRight, self)
            lay.setContentsMargins(dp(8), dp(6), dp(10), dp(6))
            lay.setSpacing(dp(12))
            lay.addWidget(self._portrait)
            lay.addWidget(combo, 1, Qt.AlignVCenter)
            self.setMinimumHeight(dp(60))
            self.setMaximumHeight(dp(132))
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        combo.currentIndexChanged.connect(self._sync)
        self._sync()

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return hint if self._vertical else QSize(hint.width(), dp(84))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._vertical:
            m = self.layout().contentsMargins()
            side = max(dp(40), self.height() - m.top() - m.bottom())
            if self._portrait.width() != side:
                self._portrait.setFixedSize(side, side)

    def _sync(self, *_args) -> None:
        idx = self.combo.currentIndex()
        uid = int(self.combo.itemData(idx) or 0) if idx >= 0 else 0
        if uid <= 0:
            self._portrait.set_unit(QIcon(), QColor(_theme.C["border"]))
            accent = _theme.C["card_border"]
        else:
            ring = element_colour(str(self.combo.itemData(idx, ELEMENT_ROLE) or ""))
            self._portrait.set_unit(self.combo.itemIcon(idx), ring)
            accent = ring.name()
        self.setStyleSheet(self._style_for(accent))

    @staticmethod
    def _style_for(accent: str) -> str:
        c = _theme.C
        return (
            f"QFrame#UnitSlotCard {{ background: {c['card_bg']}; border: 1px solid {c['card_border']};"
            f" border-left: 3px solid {accent}; border-radius: {dp(10)}px; }}"
            f"QLabel#UnitSlotTitle {{ color: {c['text_dim']}; font-size: 9pt; font-weight: 600; background: transparent; border: none; }}"
            f"QFrame#UnitSlotCard QComboBox {{ background: transparent; border: 1px solid transparent;"
            f" font-size: 10.5pt; font-weight: 600; }}"
            f"QFrame#UnitSlotCard QComboBox:hover, QFrame#UnitSlotCard QComboBox:focus {{"
            f" background: {c['bg_input']}; border-color: {c['border']}; }}"
        )
