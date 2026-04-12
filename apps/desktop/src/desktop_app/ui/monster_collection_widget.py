from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_app.domain.artifact_effects import ARTIFACT_MAIN_FOCUS_BY_EFFECT_ID, artifact_effect_text
from desktop_app.domain.models import AccountData, Artifact, Rune, Unit
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

    _ICON_SIZE = 96
    _SKILL_ICON_SIZE = 52

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
        self._assets_dir = assets_dir
        self.setWindowTitle(str(info.name or ""))
        self.setMinimumSize(dp(980), dp(700))
        self.resize(dp(1100), dp(880))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(dp(24), dp(20), dp(24), dp(16))
        root.setSpacing(dp(18))
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # ── Header ────────────────────────────────────────────────────────────────────────
        element = str(info.element or "").lower()
        elem_color = _ELEMENT_COLORS.get(element, _theme.C["accent"])

        header_frame = QFrame()
        header_frame.setObjectName("detailHeader")
        header_frame.setStyleSheet(
            f"QFrame#detailHeader {{ background: {_theme.C['bg_mid']}; "
            f"border-radius: {dp(12)}px; border: none; }}"
        )
        header_h = QHBoxLayout(header_frame)
        header_h.setContentsMargins(dp(16), dp(16), dp(16), dp(16))
        header_h.setSpacing(dp(14))

        # Thin element color accent bar
        accent_bar = QFrame()
        accent_bar.setFixedWidth(dp(4))
        accent_bar.setStyleSheet(
            f"background: {elem_color}; border-radius: {dp(2)}px; border: none;"
        )
        header_h.addWidget(accent_bar)

        # Monster icon with element-colored border
        icon_size = dp(self._ICON_SIZE)
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(icon_size, icon_size)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet(
            f"border: 2px solid {elem_color}; border-radius: {dp(8)}px; "
            f"background: {_theme.C['bg']};"
        )
        px = self._load_monster_pixmap(info, assets_dir)
        if px:
            pad = dp(4)
            icon_lbl.setPixmap(
                px.scaled(icon_size - pad, icon_size - pad, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        header_h.addWidget(icon_lbl)

        # Name + metadata column
        name_col = QVBoxLayout()
        name_col.setSpacing(dp(5))

        name_lbl = QLabel(str(info.name or ""))
        name_lbl.setStyleSheet(
            f"font-size: 16pt; font-weight: bold; color: {_theme.C['text']}; border: none;"
        )
        name_col.addWidget(name_lbl)

        level = int(getattr(unit, "unit_level", 0) or 0)
        unit_class = int(getattr(unit, "unit_class", 0) or 0)
        meta_parts = []
        if element:
            meta_parts.append(element.capitalize())
        if level:
            meta_parts.append(f"Lv{level}")
        meta_lbl = QLabel("  ·  ".join(meta_parts))
        meta_lbl.setStyleSheet(
            f"font-size: 10pt; color: {_theme.C['text_dim']}; border: none;"
        )
        name_col.addWidget(meta_lbl)

        stars_lbl = QLabel("★" * unit_class + "☆" * max(0, 6 - unit_class))
        stars_lbl.setStyleSheet(
            f"font-size: 13pt; color: {elem_color}; border: none; letter-spacing: 2px;"
        )
        name_col.addWidget(stars_lbl)

        teams = self._team_memberships(unit.unit_id, account)
        if teams:
            teams_h = QHBoxLayout()
            teams_h.setSpacing(dp(6))
            teams_h.setContentsMargins(0, dp(2), 0, 0)
            for t in teams:
                badge = QLabel(t)
                badge.setStyleSheet(
                    f"background: transparent; color: {_theme.C['accent']}; "
                    f"border: 1px solid {_theme.C['accent']}; border-radius: {dp(10)}px; "
                    f"padding: {dp(2)}px {dp(8)}px; font-size: 8pt; font-weight: 600;"
                )
                teams_h.addWidget(badge)
            teams_h.addStretch()
            name_col.addLayout(teams_h)

        name_col.addStretch()
        header_h.addLayout(name_col)
        header_h.addStretch()
        root.addWidget(header_frame)

        # ── Skills ────────────────────────────────────────────────────────────────────────────
        self._add_section_title(root, tr("collection.detail_skills"))

        skills_h = QHBoxLayout()
        skills_h.setSpacing(dp(10))
        sz = dp(self._SKILL_ICON_SIZE)

        for idx, (skill_id, current_level) in enumerate(unit.skills or ()):
            max_lvl = skill_max_levels.get(skill_id, 0)

            card = QFrame()
            card.setObjectName("skillCard")
            card.setStyleSheet(
                f"QFrame#skillCard {{ background: {_theme.C['bg_mid']}; "
                f"border-radius: {dp(10)}px; border: none; }}"
            )
            cv = QVBoxLayout(card)
            cv.setContentsMargins(dp(12), dp(10), dp(12), dp(10))
            cv.setSpacing(dp(6))

            skill_icon_lbl = QLabel()
            skill_icon_lbl.setFixedSize(sz, sz)
            skill_icon_lbl.setAlignment(Qt.AlignCenter)
            icon_filename = skill_icons.get(skill_id, "")
            loaded = False
            if icon_filename and assets_dir:
                p = assets_dir / "skills" / f"{icon_filename}.png"
                if p.exists():
                    skill_icon_lbl.setPixmap(
                        QPixmap(str(p)).scaled(sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    )
                    loaded = True
            if not loaded:
                skill_icon_lbl.setText(f"S{idx + 1}")
                skill_icon_lbl.setStyleSheet(
                    f"background: {_theme.C['card_bg']}; border-radius: {dp(6)}px; "
                    f"color: {_theme.C['text']}; font-weight: bold; border: none;"
                )
            cv.addWidget(skill_icon_lbl, alignment=Qt.AlignHCenter)

            sname = skill_names.get(skill_id, "")
            nm = QLabel(sname)
            nm.setAlignment(Qt.AlignCenter)
            nm.setWordWrap(True)
            nm.setFixedWidth(max(sz, dp(90)))
            nm.setStyleSheet(
                f"font-size: 8pt; color: {_theme.C['text_dim']}; border: none;"
            )
            cv.addWidget(nm)

            if max_lvl <= 1:
                lv_text, lv_color = str(current_level), _theme.C["text_dim"]
            elif current_level >= max_lvl:
                lv_text, lv_color = tr("collection.skill_max"), _theme.C["green"]
            else:
                lv_text = tr("collection.skill_level", current=current_level, max=max_lvl)
                lv_color = _theme.C["orange"]

            lv_lbl = QLabel(lv_text)
            lv_lbl.setAlignment(Qt.AlignCenter)
            lv_lbl.setStyleSheet(
                f"font-size: 8pt; font-weight: 700; color: {lv_color}; border: none;"
            )
            cv.addWidget(lv_lbl)

            skills_h.addWidget(card)

        skills_h.addStretch()
        skills_w = QWidget()
        skills_w.setLayout(skills_h)
        root.addWidget(skills_w)

        # ── Runes (tabs: PvE / Siege / RTA) ──────────────────────────────────────────────────────
        self._add_section_title(root, tr("collection.detail_runes"))

        rune_tabs = QTabWidget()
        rune_tabs.setDocumentMode(True)
        for tab_label, runes in [
            (tr("collection.detail_tab_pve"),   account.equipped_runes_for(unit.unit_id, "pve")),
            (tr("collection.detail_tab_siege"),  account.equipped_runes_for(unit.unit_id, "siege")),
            (tr("collection.detail_tab_rta"),    account.equipped_runes_for(unit.unit_id, "rta")),
        ]:
            rune_tabs.addTab(self._rune_tab(runes), tab_label)
        root.addWidget(rune_tabs)

        # ── Artefakte ───────────────────────────────────────────────────────────────────────────────────────
        art_by_id: Dict[int, Artifact] = {a.artifact_id: a for a in account.artifacts}
        pve_arts = [a for a in account.artifacts if int(a.occupied_id or 0) == int(unit.unit_id)]
        siege_art_ids = account.guild_artifact_equip.get(int(unit.unit_id), [])
        siege_arts = [art_by_id[aid] for aid in siege_art_ids if aid in art_by_id]
        rta_art_ids = account.rta_artifact_equip.get(int(unit.unit_id), [])
        rta_arts = [art_by_id[aid] for aid in rta_art_ids if aid in art_by_id]

        self._add_section_title(root, tr("ui.artifacts_title"))

        art_tabs = QTabWidget()
        art_tabs.setDocumentMode(True)
        for tab_label, arts in [
            (tr("collection.detail_tab_pve"),   pve_arts),
            (tr("collection.detail_tab_siege"),  siege_arts),
            (tr("collection.detail_tab_rta"),    rta_arts),
        ]:
            art_tabs.addTab(self._artifact_tab(arts), tab_label)
        root.addWidget(art_tabs)

        # ── Close button (außerhalb des Scrollbereichs, immer sichtbar) ──────────────────────────────────
        btn_h = QHBoxLayout()
        btn_h.setContentsMargins(dp(16), dp(8), dp(16), dp(10))
        btn_h.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        btn_h.addWidget(btns)
        outer.addLayout(btn_h)

    def _add_section_title(self, layout: QVBoxLayout, text: str) -> None:
        """Adds a section header with a hairline separator below."""
        header_w = QWidget()
        hh = QVBoxLayout(header_w)
        hh.setContentsMargins(0, 0, 0, 0)
        hh.setSpacing(dp(6))

        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"font-size: 10pt; font-weight: 700; color: {_theme.C['text']}; border: none;"
        )
        hh.addWidget(lbl)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {_theme.C['card_border']}; border: none;")
        hh.addWidget(line)

        layout.addWidget(header_w)

    def _rune_tab(self, runes: list[Rune]) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(dp(4), dp(12), dp(4), dp(8))
        grid.setHorizontalSpacing(dp(10))
        grid.setVerticalSpacing(dp(10))
        by_slot: Dict[int, Rune] = {r.slot_no: r for r in runes}
        for idx, slot in enumerate(range(1, 7)):
            row, col = divmod(idx, 3)
            grid.addWidget(self._rune_card(by_slot.get(slot), slot), row, col)
        return w

    def _rune_card(self, rune: Optional[Rune], slot: int) -> QWidget:
        frame = QFrame()
        frame.setObjectName("runeCard")
        frame.setStyleSheet(
            f"QFrame#runeCard {{ border: 1px solid {_theme.C['card_border']}; "
            f"border-radius: {dp(10)}px; background: {_theme.C['bg_mid']}; }}"
        )
        frame.setMinimumWidth(dp(215))
        v = QVBoxLayout(frame)
        v.setSpacing(dp(4))
        v.setContentsMargins(dp(12), dp(10), dp(12), dp(10))

        if rune is None:
            slot_lbl = QLabel(f"{tr('ui.slot')} {slot}")
            slot_lbl.setStyleSheet(
                f"font-size: 9pt; font-weight: 600; color: {_theme.C['text_dim']}; "
                f"background: transparent; border: none;"
            )
            v.addWidget(slot_lbl)
            empty = QLabel(tr("collection.detail_rune_empty"))
            empty.setStyleSheet(
                f"color: {_theme.C['text_dim']}; font-size: 8pt; border: none;"
            )
            v.addWidget(empty)
            v.addStretch()
            return frame

        eff = float(rune_efficiency(rune))
        eff_color = (
            _theme.C["green"] if eff >= 80
            else _theme.C["orange"] if eff >= 60
            else _theme.C["text_dim"]
        )

        # Row 1: Slot label + efficiency value
        row1 = QHBoxLayout()
        row1.setSpacing(dp(4))
        slot_lbl = QLabel(f"{tr('ui.slot')} {slot}")
        slot_lbl.setStyleSheet(
            f"font-size: 8pt; font-weight: 600; color: {_theme.C['text_dim']}; "
            f"background: transparent; border: none;"
        )
        row1.addWidget(slot_lbl)
        row1.addStretch()
        eff_lbl = QLabel(f"{eff:.1f}%")
        eff_lbl.setStyleSheet(
            f"font-size: 8pt; font-weight: 700; color: {eff_color}; "
            f"background: transparent; border: none;"
        )
        row1.addWidget(eff_lbl)
        v.addLayout(row1)

        # Row 2: Set icon + set name + upgrade level
        row2 = QHBoxLayout()
        row2.setSpacing(dp(5))
        set_icon = self._load_set_icon(rune.set_id)
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(dp(20), dp(20))
        icon_lbl.setStyleSheet("border: none; background: transparent;")
        if set_icon and not set_icon.isNull():
            icon_lbl.setPixmap(set_icon.pixmap(dp(20), dp(20)))
        row2.addWidget(icon_lbl)
        set_name = SET_NAMES.get(rune.set_id, f"Set {rune.set_id}")
        set_lbl = QLabel(set_name)
        set_lbl.setStyleSheet(
            f"font-size: 8pt; font-weight: 600; color: {_theme.C['accent']}; border: none;"
        )
        row2.addWidget(set_lbl)
        upg_lbl = QLabel(f"+{int(rune.upgrade_curr or 0)}")
        upg_lbl.setStyleSheet(
            f"font-size: 8pt; color: {_theme.C['text_dim']}; border: none;"
        )
        row2.addWidget(upg_lbl)
        row2.addStretch()
        v.addLayout(row2)

        # Hairline divider
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {_theme.C['card_border']}; border: none;")
        v.addWidget(div)

        # Main stat
        if rune.pri_eff:
            main_lbl = QLabel(_stat_label(rune.pri_eff[0], rune.pri_eff[1]))
            main_lbl.setStyleSheet(
                f"font-size: 12pt; font-weight: bold; color: {_theme.C['text']}; "
                f"border: none; padding: {dp(2)}px 0 {dp(3)}px 0;"
            )
            v.addWidget(main_lbl)

        # Prefix stat
        has_prefix = (
            rune.prefix_eff
            and len(rune.prefix_eff) >= 2
            and int(rune.prefix_eff[0] or 0) > 0
            and int(rune.prefix_eff[1] or 0) > 0
        )
        if has_prefix:
            pfx = QLabel(f"{tr('ui.prefix')}: {_stat_label(rune.prefix_eff[0], rune.prefix_eff[1])}")
            pfx.setStyleSheet(
                f"font-size: 8pt; color: {_theme.C['text_dim']}; border: none;"
            )
            v.addWidget(pfx)

        # Substats
        for sec in (rune.sec_eff or []):
            if not sec:
                continue
            eff_id = int(sec[0] or 0)
            base_val = int(sec[1] or 0) if len(sec) > 1 else 0
            gem_flag = int(sec[2] or 0) if len(sec) > 2 else 0
            grind = int(sec[3] or 0) if len(sec) > 3 else 0
            total = base_val + grind
            pct = "%" if EFFECT_ID_TO_MAINSTAT_KEY.get(eff_id, "") in _PCT_KEYS else ""
            text = _stat_label(eff_id, total)
            if grind > 0:
                text += f" <span style='color:#FFD700;'>({base_val}+{grind}{pct})</span>"
            if gem_flag:
                text = f"<span style='color:#1abc9c'>{text} [Gem]</span>"
            lbl = QLabel(text)
            lbl.setTextFormat(Qt.RichText)
            lbl.setStyleSheet(
                f"font-size: 9pt; color: {_theme.C['text']}; border: none;"
            )
            v.addWidget(lbl)

        return frame

    def _load_set_icon(self, set_id: int) -> Optional[QIcon]:
        name = SET_NAMES.get(set_id, "")
        slug = name.lower().replace(" ", "_") if name else str(set_id)
        icon_path = self._assets_dir / "runes" / "sets" / f"{set_id}_{slug}.png"
        return QIcon(str(icon_path)) if icon_path.exists() else None

    def _artifact_tab(self, artifacts: list[Artifact]) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(dp(4), dp(12), dp(4), dp(8))
        h.setSpacing(dp(12))

        by_type: Dict[int, Artifact] = {a.type_: a for a in artifacts}
        for art_type in (1, 2):
            art = by_type.get(art_type)
            frame = QFrame()
            frame.setObjectName("artifactCard")
            frame.setStyleSheet(
                f"QFrame#artifactCard {{ border: 1px solid {_theme.C['card_border']}; "
                f"border-radius: {dp(10)}px; background: {_theme.C['bg_mid']}; }}"
            )
            v = QVBoxLayout(frame)
            v.setSpacing(dp(4))
            v.setContentsMargins(dp(12), dp(10), dp(12), dp(10))

            kind = tr("artifact.attribute") if art_type == 1 else tr("artifact.type")

            # Header row: kind label + upgrade level
            kind_h = QHBoxLayout()
            kind_h.setSpacing(dp(6))
            kind_lbl = QLabel(kind)
            kind_lbl.setStyleSheet(
                f"font-size: 9pt; font-weight: 600; color: {_theme.C['text_dim']}; border: none;"
            )
            kind_h.addWidget(kind_lbl)
            if art is not None:
                upg_lbl = QLabel(f"+{int(art.level or 0)}")
                upg_lbl.setStyleSheet(
                    f"font-size: 8pt; color: {_theme.C['text_dim']}; border: none;"
                )
                kind_h.addWidget(upg_lbl)
            kind_h.addStretch()
            v.addLayout(kind_h)

            # Hairline divider
            div = QFrame()
            div.setFixedHeight(1)
            div.setStyleSheet(f"background: {_theme.C['card_border']}; border: none;")
            v.addWidget(div)

            if art is None:
                empty = QLabel(tr("collection.detail_rune_empty"))
                empty.setStyleSheet(
                    f"color: {_theme.C['text_dim']}; font-size: 8pt; border: none;"
                )
                v.addWidget(empty)
                v.addStretch()
                h.addWidget(frame)
                continue

            if art.pri_effect:
                eid = int(art.pri_effect[0] or 0)
                val = art.pri_effect[1] if len(art.pri_effect) > 1 else 0
                focus = ARTIFACT_MAIN_FOCUS_BY_EFFECT_ID.get(eid, "")
                main_text = f"{focus} +{int(val)}" if focus else artifact_effect_text(eid, val)
                main_lbl = QLabel(main_text)
                main_lbl.setStyleSheet(
                    f"font-size: 11pt; font-weight: bold; color: {_theme.C['text']}; "
                    f"border: none; padding: {dp(2)}px 0 {dp(3)}px 0;"
                )
                v.addWidget(main_lbl)

            for sec in (art.sec_effects or []):
                if not sec:
                    continue
                try:
                    eid = int(sec[0] or 0)
                    val = sec[1] if len(sec) > 1 else 0
                except Exception:
                    continue
                lbl = QLabel(f"\u2022 {artifact_effect_text(eid, val)}")
                lbl.setStyleSheet(
                    f"font-size: 9pt; color: {_theme.C['text']}; border: none;"
                )
                v.addWidget(lbl)

            v.addStretch()
            h.addWidget(frame)

        h.addStretch()
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

_ELEMENT_COLORS: dict[str, str] = {
    "fire": "#E74C3C",
    "water": "#3498DB",
    "wind": "#2ECC71",
    "light": "#F1C40F",
    "dark": "#8E44AD",
}


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

        elem = (self._info.element or "").lower() if self._info else ""
        self._elem_color = _ELEMENT_COLORS.get(elem, _theme.C["accent"])

        self._hovered = False
        size = icon_px + pad_px * 2
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

        # Outer glow via drop-shadow (same as siege cards)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(dp(6))
        shadow.setOffset(0, 0)
        shadow.setColor(QColor(0, 0, 0, 55))
        self.setGraphicsEffect(shadow)
        self._shadow = shadow

        self._anim_shadow = QPropertyAnimation(shadow, b"blurRadius", self)
        self._anim_shadow.setDuration(160)
        self._anim_shadow.setEasingCurve(QEasingCurve.OutCubic)

    def enterEvent(self, event) -> None:
        self._hovered = True
        accent = QColor(self._elem_color)
        accent.setAlpha(180)
        self._shadow.setColor(accent)
        self._anim_shadow.stop()
        self._anim_shadow.setStartValue(int(self._shadow.blurRadius()))
        self._anim_shadow.setEndValue(dp(28))
        self._anim_shadow.start()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._shadow.setColor(QColor(0, 0, 0, 55))
        self._anim_shadow.stop()
        self._anim_shadow.setStartValue(int(self._shadow.blurRadius()))
        self._anim_shadow.setEndValue(dp(6))
        self._anim_shadow.start()
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        radius = self._pad_px + 3

        # Background
        p.fillRect(self.rect(), QColor("#1e1e2e"))
        p.setPen(QColor("#3a3a5a"))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), radius, radius)

        # Icon — slightly larger on hover (zoom effect)
        if self._pixmap and not self._pixmap.isNull():
            zoom_px = int(self._icon_px * 1.12) if self._hovered else self._icon_px
            scaled = self._pixmap.scaled(
                zoom_px, zoom_px,
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

