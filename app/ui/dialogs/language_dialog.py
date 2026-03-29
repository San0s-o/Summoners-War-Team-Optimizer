from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.dpi import dp


class LanguagePickerDialog(QDialog):
    """Shown on first launch to let the user choose their UI language.

    Intentionally bilingual (hardcoded) because no language preference
    has been saved yet when this dialog is displayed.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Sprache / Language")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(dp(360), dp(140))
        self._selected: str = "de"

        layout = QVBoxLayout(self)
        layout.setSpacing(dp(14))

        lbl = QLabel(
            "<b>Bitte wähle deine Sprache.</b><br>"
            "<b>Please choose your language.</b>"
        )
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.RichText)
        layout.addWidget(lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(dp(12))

        btn_de = QPushButton("Deutsch")
        btn_de.setDefault(True)
        btn_de.setFixedWidth(dp(140))
        btn_de.clicked.connect(lambda: self._pick("de"))
        btn_row.addStretch()
        btn_row.addWidget(btn_de)

        btn_en = QPushButton("English")
        btn_en.setFixedWidth(dp(140))
        btn_en.clicked.connect(lambda: self._pick("en"))
        btn_row.addWidget(btn_en)
        btn_row.addStretch()

        layout.addLayout(btn_row)

    def _pick(self, lang: str) -> None:
        self._selected = lang
        self.accept()

    @property
    def selected_language(self) -> str:
        return self._selected
