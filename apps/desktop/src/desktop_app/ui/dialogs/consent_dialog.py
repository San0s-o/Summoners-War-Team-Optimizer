from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop_app.i18n import tr
from desktop_app.services.license_service import save_consent
from desktop_app.ui.dpi import dp


def _privacy_policy_path() -> Path | None:
    from desktop_app.i18n import get_language
    lang = get_language()

    if getattr(sys, "frozen", False):
        # In the EXE the files live inside _internal (sys._MEIPASS)
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parents[3]  # project root

    # Try the language-specific file first, then fall back to German
    for filename in (f"Datenschutz_{lang}.txt", "Datenschutz_de.txt"):
        candidate = base / filename
        if candidate.exists():
            return candidate
    return None


def open_privacy_policy() -> None:
    """Open the privacy policy document for the current language."""
    path = _privacy_policy_path()
    if path:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class ConsentDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("consent.title"))
        self.resize(dp(660), dp(260))
        self.setWindowFlags(self.windowFlags() & ~0x00040000)  # no "?" button

        layout = QVBoxLayout(self)
        layout.setSpacing(dp(12))

        lbl = QLabel(tr("consent.body"))
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(dp(8))
        btn_row.addStretch()

        self.btn_decline = QPushButton(tr("consent.decline"))
        self.btn_decline.clicked.connect(self._on_decline)
        btn_row.addWidget(self.btn_decline)

        self.btn_accept = QPushButton(tr("consent.accept"))
        self.btn_accept.setDefault(True)
        self.btn_accept.clicked.connect(self._on_accept)
        btn_row.addWidget(self.btn_accept)

        layout.addLayout(btn_row)

    def _on_accept(self) -> None:
        save_consent(True)
        self.accept()

    def _on_decline(self) -> None:
        save_consent(False)
        self.reject()
