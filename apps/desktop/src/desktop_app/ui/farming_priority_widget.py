from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop_app.domain.models import AccountData, Artifact
from desktop_app.domain.monster_db import MonsterDB
from desktop_app.domain.presets import BuildStore, SET_NAMES
from desktop_app.engine.efficiency import artifact_efficiency, rune_efficiency, rune_efficiency_max
from desktop_app.i18n import tr
from desktop_app.ui import theme as _theme
from desktop_app.ui.dpi import dp


_GRIND_GAIN_PRIORITY = 5.0
_SET_TARGET_EFF = 85.0
_ARTIFACT_TARGET_EFF = 72.0
_SET_MIN_CARD_W = 300
_DUNGEON_MIN_CARD_W = 300
_MAX_SET_COLS = 6
_MAX_DUNGEON_COLS = 4
_ANCIENT_RUNE_CLASSES = {11, 12, 13, 14, 15, 16}
_GRINDABLE_EFF_IDS = {1, 2, 3, 4, 5, 6, 8}
_HERO_GRIND_CAP = {1: 430.0, 2: 7.0, 3: 22.0, 4: 7.0, 5: 22.0, 6: 7.0, 8: 4.0}
_HERO_GRIND_CAP_ANCIENT = {1: 510.0, 2: 9.0, 3: 26.0, 4: 9.0, 5: 26.0, 6: 9.0, 8: 5.0}

_PRIO_GRINDS = 0
_PRIO_FARM_SET = 1
_PRIO_OK = 2


_SET_TO_DUNGEON_KEY: Dict[str, str] = {
    # Giants
    "Swift": "farming.dungeon_giants",
    "Energy": "farming.dungeon_giants",
    "Blade": "farming.dungeon_giants",
    "Fatal": "farming.dungeon_giants",
    "Despair": "farming.dungeon_giants",
    # Dragons
    "Violent": "farming.dungeon_dragons",
    "Revenge": "farming.dungeon_dragons",
    "Focus": "farming.dungeon_dragons",
    "Guard": "farming.dungeon_dragons",
    "Endure": "farming.dungeon_dragons",
    "Shield": "farming.dungeon_dragons",
    # Necropolis
    "Rage": "farming.dungeon_necro",
    "Vampire": "farming.dungeon_necro",
    "Nemesis": "farming.dungeon_necro",
    "Destroy": "farming.dungeon_necro",
    "Will": "farming.dungeon_necro",
    # Spiritual Realm
    "Fight": "farming.dungeon_spiritual",
    "Determination": "farming.dungeon_spiritual",
    "Enhance": "farming.dungeon_spiritual",
    "Accuracy": "farming.dungeon_spiritual",
    "Tolerance": "farming.dungeon_spiritual",
    "Seal": "farming.dungeon_spiritual",
    # Intangible has no fixed dungeon.
}


@dataclass
class SetFarmReport:
    set_name: str
    rune_count: int
    avg_eff: float
    avg_hero_max_eff: float
    avg_gain: float
    dungeon_key: Optional[str]
    priority: int


@dataclass
class ArtifactFarmReport:
    artifact_count: int
    avg_eff_t1: float
    avg_eff_t2: float
    avg_eff: float
    recommendation_key: str


@dataclass
class DungeonFarmReport:
    dungeon_key: str
    quality_pct: float
    base_quality_pct: float
    potential_pct: float
    note: str
    is_raid: bool = False
    raid_plus12_to_15_count: int = 0
    raid_at_or_over_hero_max_count: int = 0
    raid_missing_grinds_count: int = 0
    raid_one_grind_missing_count: int = 0


class FarmingPriorityWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._account: Optional[AccountData] = None
        self._monster_db: Optional[MonsterDB] = None
        self._presets: Optional[BuildStore] = None
        self._assets_dir: Optional[Path] = None
        self._set_reports: List[SetFarmReport] = []
        self._dungeon_reports: List[DungeonFarmReport] = []
        self._artifact_report: Optional[ArtifactFarmReport] = None
        self._last_set_cols: int = -1
        self._last_dungeon_cols: int = -1
        self._layout_scheduled: bool = False

        root = QVBoxLayout(self)
        root.setContentsMargins(dp(12), dp(12), dp(12), dp(12))
        root.setSpacing(dp(8))

        top = QHBoxLayout()
        btn_refresh = QPushButton(tr("farming.btn_refresh"))
        btn_refresh.clicked.connect(self._refresh)
        top.addWidget(btn_refresh)
        top.addStretch(1)

        self._lbl_summary = QLabel("")
        self._lbl_summary.setStyleSheet(f"color: {_theme.C['text_dim']}; font-size: {dp(10)}px;")
        top.addWidget(self._lbl_summary)
        root.addLayout(top)

        self._lbl_dungeon_header = QLabel(tr("farming.dungeon_overview_header"))
        self._lbl_dungeon_header.setStyleSheet(f"font-size: {dp(11)}px; font-weight: 600; color: {_theme.C['text_dim']};")
        root.addWidget(self._lbl_dungeon_header)

        self._dungeon_host = QWidget()
        self._dungeon_grid = QGridLayout(self._dungeon_host)
        self._dungeon_grid.setContentsMargins(0, 0, 0, 0)
        self._dungeon_grid.setHorizontalSpacing(dp(8))
        self._dungeon_grid.setVerticalSpacing(dp(8))
        self._dungeon_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        root.addWidget(self._dungeon_host)

        self._lbl_art_header = QLabel(tr("farming.artifacts_header"))
        self._lbl_art_header.setStyleSheet(f"font-size: {dp(11)}px; font-weight: 600; color: {_theme.C['text_dim']};")
        root.addWidget(self._lbl_art_header)

        art_row = QHBoxLayout()
        art_row.setSpacing(dp(8))
        self._card_art_t1 = _ArtifactTypeCard(tr("farming.artifacts_attr"))
        self._card_art_t2 = _ArtifactTypeCard(tr("farming.artifacts_type"))
        art_row.addWidget(self._card_art_t1, 1)
        art_row.addWidget(self._card_art_t2, 1)
        root.addLayout(art_row)

        self._lbl_art_reco = QLabel("")
        self._lbl_art_reco.setStyleSheet(f"font-size: {dp(10)}px; color: {_theme.C['text_dim']};")
        root.addWidget(self._lbl_art_reco)

        self._lbl_sets_header = QLabel(tr("farming.sets_header"))
        self._lbl_sets_header.setStyleSheet(f"font-size: {dp(11)}px; font-weight: 600; color: {_theme.C['text_dim']};")
        root.addWidget(self._lbl_sets_header)

        self._sets_scroll = QScrollArea()
        self._sets_scroll.setWidgetResizable(True)
        self._sets_scroll.setFrameShape(QFrame.NoFrame)
        self._sets_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._sets_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._sets_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._sets_host = QWidget()
        self._sets_grid = QGridLayout(self._sets_host)
        self._sets_grid.setContentsMargins(0, 0, 0, 0)
        self._sets_grid.setHorizontalSpacing(dp(8))
        self._sets_grid.setVerticalSpacing(dp(8))
        self._sets_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self._sets_scroll.setWidget(self._sets_host)
        self._sets_scroll.setMinimumHeight(dp(360))
        self._sets_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self._sets_scroll, 1)

    def set_context(
        self,
        account: Optional[AccountData],
        monster_db: MonsterDB,
        presets: BuildStore,
        assets_dir: Path,
    ) -> None:
        self._account = account
        self._monster_db = monster_db
        self._presets = presets
        self._assets_dir = assets_dir
        self._refresh()
        self._schedule_layout()

    def _refresh(self) -> None:
        self._clear_set_cards()
        self._clear_dungeon_cards()
        self._set_reports = []
        self._dungeon_reports = []
        self._artifact_report = None
        self._last_set_cols = -1
        self._last_dungeon_cols = -1
        self._lbl_summary.setText("")
        self._lbl_art_reco.setText("")
        self._card_art_t1.set_value(None)
        self._card_art_t2.set_value(None)

        if not self._account:
            return

        set_reports = _compute_set_reports(self._account)
        artifact_report = _compute_artifact_report(self._account)
        self._set_reports = set_reports
        self._artifact_report = artifact_report

        if not set_reports:
            self._lbl_summary.setText(tr("farming.no_runes"))
            return

        total_runes = sum(r.rune_count for r in set_reports)
        all_eff = sum(r.avg_eff * r.rune_count for r in set_reports) / max(1, total_runes)
        all_gain = sum(r.avg_gain * r.rune_count for r in set_reports) / max(1, total_runes)
        self._lbl_summary.setText(
            tr("farming.summary_sets", sets=len(set_reports), runes=total_runes, eff=f"{all_eff:.1f}", gain=f"{all_gain:.1f}")
        )

        dungeon_reports = _compute_dungeon_reports(set_reports, artifact_report, self._account)
        self._dungeon_reports = dungeon_reports
        self._lbl_dungeon_header.setText(tr("farming.dungeon_overview_header_count", count=len(dungeon_reports)))
        self._layout_cards(force=True)
        self._schedule_layout()

        self._card_art_t1.set_value(artifact_report.avg_eff_t1 if artifact_report.avg_eff_t1 >= 0 else None)
        self._card_art_t2.set_value(artifact_report.avg_eff_t2 if artifact_report.avg_eff_t2 >= 0 else None)
        self._lbl_art_reco.setText(tr("farming.artifacts_reco", recommendation=tr(artifact_report.recommendation_key)))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_cards(force=False)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._schedule_layout()

    def _schedule_layout(self) -> None:
        if self._layout_scheduled:
            return
        self._layout_scheduled = True

        def _run() -> None:
            self._layout_scheduled = False
            self._layout_cards(force=False)

        QTimer.singleShot(0, _run)

    def _layout_cards(self, force: bool = False) -> None:
        if not self._set_reports and not self._dungeon_reports:
            return

        set_available = self._sets_scroll.viewport().width()
        if set_available <= dp(220):
            set_available = self._sets_scroll.width()
        if set_available <= dp(220):
            set_available = self.width() - dp(24)

        dungeon_available = self._dungeon_host.width()
        if dungeon_available <= dp(220):
            dungeon_available = self.width() - dp(24)

        set_cols = _fit_columns(
            available_px=set_available,
            min_card_px=dp(_SET_MIN_CARD_W),
            gap_px=max(0, self._sets_grid.horizontalSpacing()),
            max_cols=_MAX_SET_COLS,
        )
        dungeon_cols = _fit_columns(
            available_px=dungeon_available,
            min_card_px=dp(_DUNGEON_MIN_CARD_W),
            gap_px=max(0, self._dungeon_grid.horizontalSpacing()),
            max_cols=_MAX_DUNGEON_COLS,
        )

        if not force and set_cols == self._last_set_cols and dungeon_cols == self._last_dungeon_cols:
            return

        self._last_set_cols = set_cols
        self._last_dungeon_cols = dungeon_cols

        self._clear_set_cards()
        self._clear_dungeon_cards()

        self._apply_grid_stretch(self._sets_grid, set_cols)
        self._apply_grid_stretch(self._dungeon_grid, dungeon_cols)

        for idx, report in enumerate(self._set_reports, start=1):
            row = (idx - 1) // set_cols
            col = (idx - 1) % set_cols
            self._sets_grid.addWidget(_SetRankCard(idx, report), row, col)

        for idx, dr in enumerate(self._dungeon_reports, start=1):
            row = (idx - 1) // dungeon_cols
            col = (idx - 1) % dungeon_cols
            self._dungeon_grid.addWidget(_DungeonRankCard(idx, dr), row, col)

    def _apply_grid_stretch(self, grid: QGridLayout, columns: int) -> None:
        for idx in range(_MAX_SET_COLS + 1):
            grid.setColumnStretch(idx, 0)
        for idx in range(columns):
            grid.setColumnStretch(idx, 1)

    def _clear_dungeon_cards(self) -> None:
        while self._dungeon_grid.count() > 0:
            item = self._dungeon_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _clear_set_cards(self) -> None:
        while self._sets_grid.count() > 0:
            item = self._sets_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()


class _ArtifactTypeCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FarmingArtifactTypeCard")
        self.setFixedHeight(dp(120))
        self.setMinimumWidth(dp(280))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        c = _theme.C
        self.setStyleSheet(
            f"QFrame#FarmingArtifactTypeCard {{"
            f" background: {c['card_bg']};"
            f" border: 1px solid {c['card_border']};"
            f" border-radius: {dp(10)}px;"
            f" }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(dp(14), dp(12), dp(14), dp(12))
        lay.setSpacing(dp(4))

        self._title = QLabel(title)
        self._title.setStyleSheet(f"font-size: {dp(12)}px; color: {c['text_dim']};")
        lay.addWidget(self._title)

        self._value = QLabel("—")
        self._value.setStyleSheet(f"font-size: {dp(42)}px; font-weight: 700; color: {c['text']};")
        lay.addWidget(self._value)

    def set_value(self, value: Optional[float]) -> None:
        if value is None:
            self._value.setText("—")
            self._value.setStyleSheet(f"font-size: {dp(42)}px; font-weight: 700; color: {_theme.C['text_dim']};")
            return
        col = _eff_color(value)
        self._value.setText(f"{value:.1f}%")
        self._value.setStyleSheet(f"font-size: {dp(42)}px; font-weight: 700; color: {col};")


class _DungeonRankCard(QFrame):
    def __init__(self, rank: int, report: DungeonFarmReport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FarmingDungeonCard")
        self.setFixedHeight(dp(170))
        self.setMinimumWidth(dp(280))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        c = _theme.C
        tone = _eff_color(report.quality_pct)
        self.setStyleSheet(
            f"QFrame#FarmingDungeonCard {{ background: {c['card_bg']}; border: 1px solid {c['card_border']}; border-radius: {dp(10)}px; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(dp(12), dp(10), dp(12), dp(10))
        lay.setSpacing(dp(4))

        head = QHBoxLayout()
        title = QLabel(tr(report.dungeon_key))
        title.setStyleSheet(f"font-size: {dp(12)}px; font-weight: 700; color: {c['text']};")
        head.addWidget(title)
        head.addStretch(1)
        rank_lbl = QLabel(f"#{rank}")
        rank_lbl.setStyleSheet(f"font-size: {dp(10)}px; font-weight: 700; color: {c['text_dim']};")
        head.addWidget(rank_lbl)
        lay.addLayout(head)

        val = QLabel(f"{report.quality_pct:.1f}%")
        val.setStyleSheet(f"font-size: {dp(46)}px; font-weight: 700; color: {tone};")
        lay.addWidget(val)

        details = QLabel(
            (
                f"{tr('farming.raid_breakdown')}: +12-15={report.raid_plus12_to_15_count}"
                f" | >=Hero={report.raid_at_or_over_hero_max_count}"
                f" | {tr('farming.raid_missing')}: {report.raid_missing_grinds_count}"
                if report.is_raid
                else (
                    f"{tr('farming.dungeon_component_quality')}: {report.base_quality_pct:.1f}%"
                    f"  |  {tr('farming.dungeon_component_potential')}: "
                    f"{f'+{report.potential_pct:.1f}%' if report.potential_pct >= 0 else '—'}"
                )
            )
        )
        details.setStyleSheet(f"font-size: {dp(10)}px; color: {c['text_dim']};")
        lay.addWidget(details)

        if report.is_raid:
            raid_sub = QLabel(tr("farming.raid_one_missing", count=report.raid_one_grind_missing_count))
            raid_sub.setStyleSheet(f"font-size: {dp(10)}px; color: {c['text_dim']};")
            lay.addWidget(raid_sub)

        note = QLabel(report.note)
        note.setStyleSheet(f"font-size: {dp(10)}px; color: {c['text_dim']};")
        lay.addWidget(note)


class _SetRankCard(QFrame):
    def __init__(self, rank: int, report: SetFarmReport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FarmingSetCard")
        self.setFixedHeight(dp(150))
        self.setMinimumWidth(dp(300))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        c = _theme.C
        tone = _eff_color(report.avg_eff)
        self.setStyleSheet(
            f"QFrame#FarmingSetCard {{ background: {c['card_bg']}; border: 1px solid {c['card_border']}; border-radius: {dp(12)}px; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(dp(14), dp(12), dp(14), dp(12))
        root.setSpacing(dp(4))

        head = QHBoxLayout()
        name = QLabel(report.set_name)
        name.setStyleSheet(f"font-size: {dp(12)}px; font-weight: 700; color: {c['text']};")
        head.addWidget(name)
        head.addStretch(1)
        rank_lbl = QLabel(f"#{rank}")
        rank_lbl.setStyleSheet(f"font-size: {dp(10)}px; color: {c['text_dim']};")
        head.addWidget(rank_lbl)
        root.addLayout(head)

        val = QLabel(f"{report.avg_eff:.1f}%")
        val.setStyleSheet(f"font-size: {dp(48)}px; font-weight: 700; color: {tone};")
        root.addWidget(val)

        meta = QLabel(
            f"{tr('farming.col_hero_max')}: {report.avg_hero_max_eff:.1f}%"
            f"  |  {tr('farming.col_potential')}: +{report.avg_gain:.1f}%"
            f"  |  {tr('farming.col_count')}: {report.rune_count}"
        )
        meta.setStyleSheet(f"font-size: {dp(10)}px; color: {c['text_dim']};")
        root.addWidget(meta)

        action = QLabel(_set_recommendation_text(report))
        action.setStyleSheet(f"font-size: {dp(10)}px; color: {c['text_dim']};")
        root.addWidget(action)


def _eff_color(eff: float) -> str:
    c = _theme.C
    if eff < _SET_TARGET_EFF:
        return c["red"]
    if eff < (_SET_TARGET_EFF + 5.0):
        return c.get("orange", "#f0a000")
    return c.get("green", "#2fbf6b")


def _fit_columns(available_px: int, min_card_px: int, gap_px: int, max_cols: int) -> int:
    available = max(1, int(available_px))
    min_card = max(1, int(min_card_px))
    gap = max(0, int(gap_px))
    cols = (available + gap) // (min_card + gap)
    return max(1, min(int(max_cols), int(cols)))


def _compute_set_reports(account: AccountData) -> List[SetFarmReport]:
    grouped: Dict[str, List[tuple[float, float]]] = {}
    for rune in (account.runes or []):
        set_name = SET_NAMES.get(int(rune.set_id or 0), f"Set{int(rune.set_id or 0)}")
        grouped.setdefault(set_name, []).append((float(rune_efficiency(rune)), float(rune_efficiency_max(rune, "hero"))))

    reports: List[SetFarmReport] = []
    for set_name, values in grouped.items():
        count = len(values)
        avg_eff = sum(v[0] for v in values) / max(1, count)
        avg_hero = sum(v[1] for v in values) / max(1, count)
        avg_gain = max(0.0, avg_hero - avg_eff)
        if avg_gain >= _GRIND_GAIN_PRIORITY:
            priority = _PRIO_GRINDS
        elif avg_eff < _SET_TARGET_EFF:
            priority = _PRIO_FARM_SET
        else:
            priority = _PRIO_OK
        reports.append(
            SetFarmReport(
                set_name=set_name,
                rune_count=count,
                avg_eff=avg_eff,
                avg_hero_max_eff=avg_hero,
                avg_gain=avg_gain,
                dungeon_key=_SET_TO_DUNGEON_KEY.get(set_name),
                priority=priority,
            )
        )

    reports.sort(key=lambda r: (r.priority, r.avg_eff, -r.avg_gain, -r.rune_count))
    return reports


def _compute_artifact_report(account: AccountData) -> ArtifactFarmReport:
    arts: List[Artifact] = [a for a in (account.artifacts or []) if a.sec_effects]
    if not arts:
        return ArtifactFarmReport(artifact_count=0, avg_eff_t1=-1.0, avg_eff_t2=-1.0, avg_eff=-1.0, recommendation_key="farming.artifacts_no_data")

    t1 = [a for a in arts if int(a.type_ or 0) == 1]
    t2 = [a for a in arts if int(a.type_ or 0) == 2]
    avg_t1 = (sum(float(artifact_efficiency(a)) for a in t1) / len(t1)) if t1 else -1.0
    avg_t2 = (sum(float(artifact_efficiency(a)) for a in t2) / len(t2)) if t2 else -1.0
    vals = [v for v in (avg_t1, avg_t2) if v >= 0]
    avg_eff = (sum(vals) / len(vals)) if vals else -1.0
    worst = min(vals) if vals else -1.0
    rec_key = "farming.artifacts_farm" if (worst >= 0 and worst < _ARTIFACT_TARGET_EFF) else "farming.artifacts_ok"
    return ArtifactFarmReport(
        artifact_count=len(arts),
        avg_eff_t1=avg_t1,
        avg_eff_t2=avg_t2,
        avg_eff=avg_eff,
        recommendation_key=rec_key,
    )


def _compute_dungeon_reports(
    set_reports: List[SetFarmReport], artifact_report: ArtifactFarmReport, account: AccountData
) -> List[DungeonFarmReport]:
    by_dungeon: Dict[str, List[SetFarmReport]] = {}
    for sr in set_reports:
        if sr.dungeon_key:
            by_dungeon.setdefault(sr.dungeon_key, []).append(sr)

    merged: Dict[str, DungeonFarmReport] = {}

    def _merge(dungeon_key: str, quality: float, note: str, base_quality: float, potential: float) -> None:
        q = max(0.0, min(100.0, quality))
        bq = max(0.0, min(100.0, base_quality))
        pot = float(potential)
        cur = merged.get(dungeon_key)
        if cur is None:
            merged[dungeon_key] = DungeonFarmReport(
                dungeon_key=dungeon_key,
                quality_pct=q,
                base_quality_pct=bq,
                potential_pct=pot,
                note=note,
            )
            return
        if q < cur.quality_pct:
            cur.quality_pct = q
            cur.base_quality_pct = bq
            cur.potential_pct = pot
        if note and note not in cur.note:
            cur.note = f"{cur.note} | {note}" if cur.note else note

    for dungeon_key, items in by_dungeon.items():
        total = sum(i.rune_count for i in items)
        if total <= 0:
            continue
        avg_eff = sum(i.avg_eff * i.rune_count for i in items) / total
        avg_gain = sum(i.avg_gain * i.rune_count for i in items) / total
        quality = max(0.0, min(100.0, avg_eff))
        _merge(
            dungeon_key,
            quality,
            tr("farming.dungeon_note_sets", sets=len(items), runes=total),
            base_quality=avg_eff,
            potential=avg_gain,
        )

    raid = _compute_raid_grind_breakdown(account)
    if raid["total_runes"] > 0:
        _merge(
            "farming.dungeon_raid",
            float(raid["progress_pct"]),
            tr("farming.dungeon_note_grinds", gain=f"{raid['avg_gain_pct']:.1f}"),
            base_quality=float(raid["progress_pct"]),
            potential=float(raid["avg_gain_pct"]),
        )
        cur = merged.get("farming.dungeon_raid")
        if cur is not None:
            cur.is_raid = True
            cur.raid_plus12_to_15_count = int(raid["plus12_to_15_count"])
            cur.raid_at_or_over_hero_max_count = int(raid["at_or_over_hero_max_count"])
            cur.raid_missing_grinds_count = int(raid["missing_grinds_count"])
            cur.raid_one_grind_missing_count = int(raid["one_grind_missing_count"])

    if artifact_report.artifact_count > 0:
        note = tr("farming.dungeon_note_artifacts", count=artifact_report.artifact_count)
        if artifact_report.avg_eff_t1 >= 0:
            _merge(
                "farming.dungeon_steel",
                artifact_report.avg_eff_t1,
                note,
                base_quality=artifact_report.avg_eff_t1,
                potential=-1.0,
            )
        if artifact_report.avg_eff_t2 >= 0:
            _merge(
                "farming.dungeon_punisher",
                artifact_report.avg_eff_t2,
                note,
                base_quality=artifact_report.avg_eff_t2,
                potential=-1.0,
            )

    result = list(merged.values())
    result.sort(key=lambda x: x.quality_pct)
    return result


def _is_ancient_rune(rune) -> bool:
    cls = int(getattr(rune, "origin_class", 0) or 0)
    if cls <= 0:
        cls = int(getattr(rune, "rune_class", 0) or 0)
    return cls in _ANCIENT_RUNE_CLASSES


def _compute_raid_grind_breakdown(account: AccountData) -> Dict[str, float]:
    runes = list(account.runes or [])
    plus12_to_15_count = 0
    at_or_over_hero_max_count = 0
    missing_grinds_count = 0
    one_grind_missing_count = 0
    total_cap = 0.0
    current_grind_total = 0.0
    weighted_gain = 0.0

    for rune in runes:
        lvl = int(getattr(rune, "upgrade_curr", 0) or 0)
        if 12 <= lvl <= 15:
            plus12_to_15_count += 1

        cur_eff = float(rune_efficiency(rune))
        hero_eff = float(rune_efficiency_max(rune, "hero"))
        if cur_eff >= (hero_eff - 0.05):
            at_or_over_hero_max_count += 1
        weighted_gain += max(0.0, hero_eff - cur_eff)

        caps = _HERO_GRIND_CAP_ANCIENT if _is_ancient_rune(rune) else _HERO_GRIND_CAP
        for sec in (getattr(rune, "sec_eff", None) or []):
            if not sec:
                continue
            try:
                eff_id = int(sec[0] or 0)
                if eff_id not in _GRINDABLE_EFF_IDS:
                    continue
                cap = float(caps.get(eff_id, 0.0))
                if cap <= 0:
                    continue
                grind = float(sec[3] or 0.0) if len(sec) >= 4 else 0.0
                cur = max(0.0, min(grind, cap))
                total_cap += cap
                current_grind_total += cur
                missing = cap - cur
                if missing > 1e-6:
                    missing_grinds_count += 1
                    if missing <= 1.0:
                        one_grind_missing_count += 1
            except Exception:
                continue

    progress_pct = (current_grind_total / total_cap * 100.0) if total_cap > 0 else 100.0
    avg_gain = (weighted_gain / len(runes)) if runes else 0.0
    return {
        "total_runes": float(len(runes)),
        "plus12_to_15_count": float(plus12_to_15_count),
        "at_or_over_hero_max_count": float(at_or_over_hero_max_count),
        "missing_grinds_count": float(missing_grinds_count),
        "one_grind_missing_count": float(one_grind_missing_count),
        "progress_pct": float(max(0.0, min(100.0, progress_pct))),
        "avg_gain_pct": float(avg_gain),
    }


def _set_recommendation_text(report: SetFarmReport) -> str:
    if report.set_name == "Intangible":
        return tr("farming.reco_intangible")
    if report.avg_gain >= _GRIND_GAIN_PRIORITY:
        return tr("farming.reco_grinds", dungeon=tr("farming.dungeon_raid"))
    if report.avg_eff < _SET_TARGET_EFF:
        dungeon = tr(report.dungeon_key) if report.dungeon_key else tr("farming.dungeon_unknown")
        return tr("farming.reco_farm_set", dungeon=dungeon)
    return tr("farming.reco_ok")


def _top_recommendation_text(set_reports: List[SetFarmReport], artifact_report: ArtifactFarmReport) -> tuple[str, int]:
    if not set_reports:
        return tr("farming.top_no_data"), _PRIO_OK

    best_gain_set = max(set_reports, key=lambda r: r.avg_gain)
    if best_gain_set.avg_gain >= _GRIND_GAIN_PRIORITY:
        return (
            tr("farming.top_grinds", set_name=best_gain_set.set_name, gain=f"{best_gain_set.avg_gain:.1f}", dungeon=tr("farming.dungeon_raid")),
            _PRIO_GRINDS,
        )

    art_vals = [v for v in (artifact_report.avg_eff_t1, artifact_report.avg_eff_t2) if v >= 0]
    art_worst = min(art_vals) if art_vals else -1.0
    if artifact_report.artifact_count > 0 and art_worst >= 0 and art_worst < _ARTIFACT_TARGET_EFF:
        return (
            tr("farming.top_artifacts", eff=f"{art_worst:.1f}", dungeon=tr("farming.dungeon_artifacts")),
            _PRIO_FARM_SET,
        )

    farmable_sets = [r for r in set_reports if r.dungeon_key]
    if not farmable_sets:
        return tr("farming.top_no_data"), _PRIO_OK
    worst_set = min(farmable_sets, key=lambda r: r.avg_eff)
    dungeon = tr(worst_set.dungeon_key) if worst_set.dungeon_key else tr("farming.dungeon_unknown")
    return (
        tr("farming.top_set", set_name=worst_set.set_name, eff=f"{worst_set.avg_eff:.1f}", dungeon=dungeon),
        _PRIO_FARM_SET,
    )
