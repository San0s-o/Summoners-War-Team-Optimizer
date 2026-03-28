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

from app.i18n import tr
from app.services.license_service import save_consent
from app.ui.dpi import dp

_PRIVACY_FILENAME = "Datenschutz.txt"


def _privacy_policy_path() -> Path | None:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parents[3]  # project root
    candidate = base / _PRIVACY_FILENAME
    return candidate if candidate.exists() else None


class ConsentDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("consent.title"))
        self.resize(dp(660), dp(280))
        self.setWindowFlags(self.windowFlags() & ~0x00040000)  # no "?" button

        layout = QVBoxLayout(self)
        layout.setSpacing(dp(12))

        lbl = QLabel(tr("consent.body"))
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(dp(8))

        self.btn_privacy = QPushButton(tr("consent.privacy_policy"))
        self.btn_privacy.setEnabled(_privacy_policy_path() is not None)
        self.btn_privacy.clicked.connect(self._on_privacy_policy)
        btn_row.addWidget(self.btn_privacy)

        btn_row.addStretch()

        self.btn_decline = QPushButton(tr("consent.decline"))
        self.btn_decline.clicked.connect(self._on_decline)
        btn_row.addWidget(self.btn_decline)

        self.btn_accept = QPushButton(tr("consent.accept"))
        self.btn_accept.setDefault(True)
        self.btn_accept.clicked.connect(self._on_accept)
        btn_row.addWidget(self.btn_accept)

        layout.addLayout(btn_row)

    def _on_privacy_policy(self) -> None:
        path = _privacy_policy_path()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _on_accept(self) -> None:
        save_consent(True)
        self.accept()

    def _on_decline(self) -> None:
        save_consent(False)
        self.reject()
