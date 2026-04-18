from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop_app.domain.models import AccountData, Relic
from desktop_app.i18n import tr
from desktop_app.ui.dpi import dp


# Short textual labels for the 16 known unique properties.
# Das offizielle Mapping ist noch nicht öffentlich dokumentiert, daher
# dienen diese Labels als Platzhalter. sec_effect[1] enthält den
# thresholdabhängigen Wert (z.B. 2500 ATK → "+1% DMG per 2500 ATK").
# Key = unique_property_id (entspricht dem "type" Feld im JSON).
_RELIC_GROUP_BY_ID: dict[int, str] = {
    11: "conquest",
    12: "resolute",
    13: "valiant",
    14: "timeless",
    15: "primal",
    16: "restore",
}

_DEPENDENCY_STAT_BY_META: dict[int, str] = {
    1: "atk",
    2: "def",
    3: "hp",
    4: "spd",
    100: "atk",
    101: "def",
    102: "hp",
    103: "spd",
}

# Empirically derived from live exports/UI:
# 16 unique properties are encoded as fixed ID variants.
# Format: unique_property_id -> (group, dependency stat).
_UNIQUE_PATTERN_BY_ID: dict[int, tuple[str, str]] = {
    1: ("conquest", "atk"),
    2: ("conquest", "def"),
    3: ("conquest", "hp"),
    4: ("resolute", "atk"),
    5: ("resolute", "def"),
    6: ("resolute", "hp"),
    7: ("valiant", "spd"),
    8: ("valiant", "def"),
    9: ("valiant", "hp"),
    10: ("timeless", "atk"),
    11: ("timeless", "spd"),
    12: ("timeless", "hp"),
    13: ("primal", "atk"),
    14: ("primal", "spd"),
    15: ("primal", "def"),
    16: ("restore", "hp"),
}

_ELEMENT_ORDER: dict[int, int] = {
    1: 0,  # Water
    2: 1,  # Fire
    3: 2,  # Wind
    4: 3,  # Light
    5: 4,  # Dark
}

class _SortableNumericItem(QTableWidgetItem):
    def __lt__(self, other) -> bool:
        if isinstance(other, QTableWidgetItem):
            a = self.data(Qt.UserRole)
            b = other.data(Qt.UserRole)
            try:
                return float(a) < float(b)
            except Exception:
                pass
        return super().__lt__(other)


def _int_item(value: int) -> QTableWidgetItem:
    item = _SortableNumericItem(str(int(value)))
    item.setData(Qt.UserRole, int(value))
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


# SW JSON main_property ids for relics (observed):
# 100=HP%, 101=ATK%, 102=DEF%
_MAIN_PROP_LABEL_KEYS: dict[int, str] = {
    100: "relic_opt.main.hp",
    101: "relic_opt.main.atk",
    102: "relic_opt.main.def",
}


def _main_property_text(relic: Relic) -> str:
    key = _MAIN_PROP_LABEL_KEYS.get(int(relic.main_property_type or 0))
    label = tr(key) if key else tr("relic_opt.main.unknown")
    val = float(relic.main_property_value or 0.0)
    if val > 0:
        val_str = str(int(val)) if abs(val - int(val)) < 1e-9 else f"{val:.1f}"
        return f"{label} +{val_str}"
    return label


def _unique_property_text(relic: Relic) -> str:
    pid = int(relic.unique_property_id or 0)
    fixed = _UNIQUE_PATTERN_BY_ID.get(pid)
    if fixed:
        group, dep = fixed
    else:
        group = _RELIC_GROUP_BY_ID.get(pid)
        if not group:
            return f"Property {pid}" if pid > 0 else ""
        dep = _DEPENDENCY_STAT_BY_META.get(int(relic.unique_property_meta or 0))

    base_label = tr(f"relic_opt.group.{group}")
    val = float(relic.unique_property_value or 0.0)
    n = int(round(val)) if val > 0 else 0

    # Some exports appear to store MAX HP thresholds in shortened form.
    if dep == "hp" and 0 < n < 1000:
        n *= 100

    if n <= 0:
        return base_label

    n_str = f"{n:,}"
    dep_label = tr(f"relic_opt.dep.{dep}") if dep else tr("relic_opt.dep.unknown")

    if group == "conquest":
        return tr("relic_opt.unique.conquest", n=n_str, dep=dep_label)
    if group == "resolute":
        return tr("relic_opt.unique.resolute", n=n_str, dep=dep_label)
    if group == "valiant":
        return tr("relic_opt.unique.valiant", n=n_str, dep=dep_label)
    if group == "timeless":
        return tr("relic_opt.unique.timeless", n=n_str, dep=dep_label)
    if group == "primal":
        return tr("relic_opt.unique.primal", n=n_str, dep=dep_label)
    if group == "restore":
        return tr("relic_opt.unique.restore", n=n_str)
    return f"{base_label} ({n_str})"


class RelicOverviewWidget(QWidget):
    """Table overview of all owned Relics.

    Since Relics can be engraved on up to 100 monsters simultaneously, the
    relationship is many-to-many and differs from the 1:1 rune/artifact model.
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        monster_name_fn: Callable[[int], str] | None = None,
        monster_icon_fn: Callable[[int], QIcon] | None = None,
    ):
        super().__init__(parent)
        self._account: Optional[AccountData] = None
        self._monster_name_fn = monster_name_fn
        self._monster_icon_fn = monster_icon_fn
        self._updating_filters = False
        self._search_text: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(dp(8), dp(8), dp(8), dp(8))
        layout.setSpacing(dp(6))

        # ── search bar ───────────────────────────────────────────
        search_row = QHBoxLayout()
        search_row.setSpacing(dp(6))
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(tr("relic_opt.search_placeholder"))
        self._search_box.setClearButtonEnabled(True)
        self._search_box.setMaximumWidth(dp(400))
        self._search_box.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self._search_box)
        search_row.addStretch(1)
        layout.addLayout(search_row)

        # ── filter row ───────────────────────────────────────────
        top = QHBoxLayout()
        self.lbl_info = QLabel("")
        top.addWidget(self.lbl_info)
        top.addStretch(1)
        self.lbl_filter_main = QLabel("")
        top.addWidget(self.lbl_filter_main)
        self.combo_filter_main = QComboBox()
        self.combo_filter_main.setMinimumWidth(dp(120))
        self.combo_filter_main.currentIndexChanged.connect(self._on_filters_changed)
        top.addWidget(self.combo_filter_main)
        self.btn_reset_filters = QPushButton("")
        self.btn_reset_filters.clicked.connect(self._on_reset_filters)
        top.addWidget(self.btn_reset_filters)
        top.addStretch(1)
        layout.addLayout(top)

        # ── table ────────────────────────────────────────────────
        self.table = QTableWidget(0, 5)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        self.retranslate()

    def _sorted_engraved_unit_ids(self, relic: Relic) -> list[int]:
        unit_ids = [int(uid) for uid in (relic.engraved_units or ()) if int(uid or 0) > 0]
        if not unit_ids:
            return []

        def _sort_key(uid: int) -> tuple[int, str, int]:
            attr = 999
            if self._account:
                unit = self._account.units_by_id.get(int(uid))
                if unit is not None:
                    attr = int(getattr(unit, "attribute", 0) or 0)
            order = _ELEMENT_ORDER.get(attr, 99)
            name = ""
            if self._monster_name_fn:
                try:
                    name = str(self._monster_name_fn(int(uid)) or "").lower()
                except Exception:
                    name = ""
            return (order, name, int(uid))

        return sorted(unit_ids, key=_sort_key)

    def _engraved_icons_widget(self, relic: Relic) -> tuple[QWidget, int] | None:
        if not self._monster_icon_fn:
            return None
        unit_ids = self._sorted_engraved_unit_ids(relic)
        if not unit_ids:
            return None

        icon_px = int(dp(48))
        count = len(unit_ids)
        rows_used = 1 if count <= 12 else (2 if count <= 36 else 3)
        per_row = max(1, (count + rows_used - 1) // rows_used)
        width_px = per_row * icon_px
        height_px = rows_used * icon_px

        strip = QPixmap(width_px, height_px)
        strip.fill(Qt.transparent)
        painter = QPainter(strip)
        tooltips: list[tuple[tuple[int, int, int, int], str]] = []
        try:
            for i, uid in enumerate(unit_ids):
                row_idx = i // per_row
                col_idx = i % per_row
                x = col_idx * icon_px
                y = row_idx * icon_px

                try:
                    icon = self._monster_icon_fn(int(uid))
                except Exception:
                    icon = QIcon()
                if icon.isNull():
                    continue
                pm = self._tight_icon_pixmap(icon, icon_px)
                if pm.isNull():
                    continue
                painter.drawPixmap(x, y, pm)

                if self._monster_name_fn:
                    try:
                        tip = str(self._monster_name_fn(int(uid)) or "")
                        if tip:
                            tooltips.append(((x, y, icon_px, icon_px), tip))
                    except Exception:
                        pass
        finally:
            painter.end()

        host = QWidget()
        host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        lbl = QLabel()
        lbl.setPixmap(strip)
        lbl.setFixedSize(width_px, height_px)
        row.addWidget(lbl, 0, Qt.AlignLeft | Qt.AlignTop)

        # Keep basic tooltip behavior: show first hovered monster name would require
        # custom event handling; for now provide an aggregated tooltip list.
        if tooltips:
            lbl.setToolTip("\n".join(t for _, t in tooltips[:20]))

        return host, rows_used

    def _tight_icon_pixmap(self, icon: QIcon, size: int) -> QPixmap:
        # Crop transparent padding but do not cut content at top/bottom.
        src = icon.pixmap(size * 3, size * 3)
        if src.isNull():
            return QPixmap()
        img = src.toImage().convertToFormat(QImage.Format_ARGB32)
        w = img.width()
        h = img.height()
        min_x = w
        min_y = h
        max_x = -1
        max_y = -1
        for y in range(h):
            for x in range(w):
                if img.pixelColor(x, y).alpha() > 8:
                    if x < min_x:
                        min_x = x
                    if y < min_y:
                        min_y = y
                    if x > max_x:
                        max_x = x
                    if y > max_y:
                        max_y = y
        if max_x < min_x or max_y < min_y:
            return src.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

        crop_w = max_x - min_x + 1
        crop_h = max_y - min_y + 1
        tight = QPixmap.fromImage(img.copy(min_x, min_y, crop_w, crop_h))
        scaled = tight.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        canvas = QPixmap(size, size)
        canvas.fill(Qt.transparent)
        p = QPainter(canvas)
        try:
            x = (size - scaled.width()) // 2
            y = (size - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        finally:
            p.end()
        return canvas

    # ── Public API ───────────────────────────────────────────────
    def retranslate(self) -> None:
        self.lbl_filter_main.setText(tr("relic_opt.filter_main"))
        self.btn_reset_filters.setText(tr("relic_opt.filter_reset"))
        self._search_box.setPlaceholderText(tr("relic_opt.search_placeholder"))
        self.table.setHorizontalHeaderLabels([
            tr("relic_opt.col.main_property"),
            tr("relic_opt.col.unique_property"),
            tr("relic_opt.col.level"),
            tr("relic_opt.col.durability"),
            tr("relic_opt.col.engraved"),
        ])
        self.refresh()

    def set_account(self, account: Optional[AccountData]) -> None:
        self._account = account
        self.refresh()

    # ── Handlers ─────────────────────────────────────────────────
    def _on_search_changed(self, text: str) -> None:
        self._search_text = (text or "").strip().lower()
        self.refresh()

    def _on_filters_changed(self, _index: int) -> None:
        if self._updating_filters:
            return
        self.refresh()

    def _on_reset_filters(self) -> None:
        self._updating_filters = True
        self.combo_filter_main.blockSignals(True)
        try:
            self.combo_filter_main.setCurrentIndex(0)
        finally:
            self.combo_filter_main.blockSignals(False)
            self._updating_filters = False
        self._search_box.clear()
        self._search_text = ""
        self.refresh()

    # ── Filters / population ─────────────────────────────────────
    def _populate_filters(self) -> None:
        current_type = int(self.combo_filter_main.currentData() or 0)
        self._updating_filters = True
        self.combo_filter_main.blockSignals(True)
        try:
            self.combo_filter_main.clear()
            self.combo_filter_main.addItem(tr("relic_opt.filter_all"), 0)
            self.combo_filter_main.addItem(tr("relic_opt.main.atk"), 100)
            self.combo_filter_main.addItem(tr("relic_opt.main.def"), 101)
            self.combo_filter_main.addItem(tr("relic_opt.main.hp"), 102)
            # Restore previous selection
            for i in range(self.combo_filter_main.count()):
                if int(self.combo_filter_main.itemData(i) or 0) == current_type:
                    self.combo_filter_main.setCurrentIndex(i)
                    break
        finally:
            self.combo_filter_main.blockSignals(False)
            self._updating_filters = False

    def _row_matches_search(self, relic: Relic) -> bool:
        if not self._search_text:
            return True
        haystack_parts = [
            _main_property_text(relic).lower(),
            _unique_property_text(relic).lower(),
        ]
        if self._monster_name_fn:
            for uid in relic.engraved_units:
                try:
                    haystack_parts.append(self._monster_name_fn(uid).lower())
                except Exception:
                    pass
        return any(self._search_text in part for part in haystack_parts if part)

    # ── Rendering ────────────────────────────────────────────────
    def refresh(self) -> None:
        relics: list[Relic] = list(self._account.relics) if self._account else []

        if self.combo_filter_main.count() == 0:
            self._populate_filters()

        type_filter = int(self.combo_filter_main.currentData() or 0)
        filtered: list[Relic] = []
        for r in relics:
            if type_filter and int(r.main_property_type or 0) != type_filter:
                continue
            if not self._row_matches_search(r):
                continue
            filtered.append(r)

        total = len(relics)
        shown = len(filtered)
        if total == 0:
            if self._account is None:
                self.lbl_info.setText(tr("relic_opt.hint_no_import"))
            else:
                self.lbl_info.setText(tr("relic_opt.hint_no_rows"))
        elif shown == 0:
            self.lbl_info.setText(tr("relic_opt.hint_no_filter_rows"))
        elif shown == total:
            self.lbl_info.setText(tr("relic_opt.count", n=total))
        else:
            self.lbl_info.setText(tr("relic_opt.count_filtered", shown=shown, total=total))

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(filtered))
        for row, relic in enumerate(filtered):
            self.table.setRowHeight(row, int(dp(36)))
            self.table.setItem(row, 0, QTableWidgetItem(_main_property_text(relic)))
            self.table.setItem(row, 1, QTableWidgetItem(_unique_property_text(relic)))
            self.table.setItem(row, 2, _int_item(int(relic.level or 0)))

            dur_item = _SortableNumericItem(
                tr("relic_opt.durability_fmt", cur=int(relic.durability or 0))
            )
            dur_item.setData(Qt.UserRole, int(relic.durability or 0))
            dur_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, dur_item)

            engraved_count = len(relic.engraved_units or ())
            engraved_item = _SortableNumericItem(
                tr("relic_opt.engraved_fmt", n=engraved_count)
            )
            engraved_item.setData(Qt.UserRole, engraved_count)
            self.table.setItem(row, 4, engraved_item)
        self.table.resizeColumnsToContents()
        for row, relic in enumerate(filtered):
            icons_bundle = self._engraved_icons_widget(relic)
            if icons_bundle is None:
                continue
            icons_widget, rows_used = icons_bundle
            item = self.table.item(row, 4)
            if item is not None:
                item.setText("")
            self.table.setCellWidget(row, 4, icons_widget)
            row_h = max(
                int(dp(36)),
                int(rows_used * dp(48) + dp(10)),
            )
            self.table.setRowHeight(row, row_h)

        self.table.setSortingEnabled(True)
