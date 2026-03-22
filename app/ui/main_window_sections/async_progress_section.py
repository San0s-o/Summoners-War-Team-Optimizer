from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict

from PySide6.QtCore import Qt, QTimer, QThreadPool, QEventLoop, Signal
from PySide6.QtWidgets import (
    QApplication, QLabel, QProgressBar, QDialog, QPushButton,
    QVBoxLayout, QHBoxLayout,
)

from app.i18n import tr
from app.ui.async_worker import _TaskWorker
from app.ui.dpi import dp


def build_pass_progress_callback(window, label: QLabel, prefix: str) -> Callable[[int, int], None]:
    def _cb(current_pass: int, total_passes: int) -> None:
        show_extra = bool(getattr(window, "_show_extra_info_enabled", lambda: False)())
        if show_extra:
            text = tr("status.pass_progress", prefix=prefix, current=int(current_pass), total=int(total_passes))
        else:
            text = prefix
        label.setText(text)
        if show_extra:
            window.statusBar().showMessage(text)
        QApplication.processEvents()

    return _cb


class _ModernProgressDialog(QDialog):
    """Modern drop-in replacement for QProgressDialog."""

    canceled = Signal()

    def __init__(self, text: str, title: str, parent=None):
        super().__init__(parent)
        from app.ui import theme as _theme
        c = _theme.C

        self.setWindowTitle(title)
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(dp(460))
        self._cancelled = False

        root = QVBoxLayout(self)
        root.setContentsMargins(dp(32), dp(30), dp(32), dp(24))
        root.setSpacing(0)

        # ── status label ────────────────────────────────────────────────
        self._label = QLabel(text, self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            f"color: {c['text']}; font-size: {dp(13)}px; background: transparent;"
        )
        root.addWidget(self._label)
        root.addSpacing(dp(22))

        # ── progress bar ─────────────────────────────────────────────────
        self._bar = QProgressBar(self)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(dp(7))
        self._bar.setStyleSheet(
            f"""
            QProgressBar {{
                background-color: {c['bg_input']};
                border: none;
                border-radius: {dp(3)}px;
            }}
            QProgressBar::chunk {{
                background-color: {c['accent']};
                border-radius: {dp(3)}px;
            }}
            """
        )
        root.addWidget(self._bar)
        root.addSpacing(dp(24))

        # ── cancel button ────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        self._cancel_btn = QPushButton(tr("btn.cancel"), self)
        self._cancel_btn.setFixedWidth(dp(130))
        self._cancel_btn.setFixedHeight(dp(34))
        self._cancel_btn.setAutoDefault(False)
        self._cancel_btn.setDefault(False)
        self._cancel_btn.setFocusPolicy(Qt.NoFocus)
        self._cancel_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: transparent;
                color: {c['text_dim']};
                border: 1px solid {c['border']};
                border-radius: {dp(6)}px;
                font-size: {dp(12)}px;
            }}
            QPushButton:hover {{
                color: {c['text']};
                border-color: {c['text_dim']};
                background-color: {c['bg_mid']};
            }}
            QPushButton:pressed {{
                background-color: {c['bg_input']};
            }}
            """
        )
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addStretch()
        btn_row.addWidget(self._cancel_btn)
        root.addLayout(btn_row)

        self.setStyleSheet(
            f"QDialog {{ background-color: {c['bg_card']}; border: 1px solid {c['border']}; }}"
        )

    def _on_cancel(self) -> None:
        self._cancelled = True
        self.canceled.emit()

    def wasCanceled(self) -> bool:
        return self._cancelled

    def setValue(self, v: int) -> None:
        self._bar.setValue(v)

    def setLabelText(self, text: str) -> None:
        self._label.setText(text)

    def setRange(self, mn: int, mx: int) -> None:
        self._bar.setRange(mn, mx)

    # ── QProgressDialog compatibility stubs ──────────────────────────────
    def setMinimumDuration(self, _): pass
    def setAutoClose(self, _): pass
    def setAutoReset(self, _): pass
    def setCancelButtonText(self, _): pass
    def setCancelButton(self, _): pass


def run_with_busy_progress(
    window,
    text: str,
    work_fn: Callable[[Callable[[], bool], Callable[[Any], None], Callable[[int, int], None]], Any],
) -> Any:
    show_extra = bool(getattr(window, "_show_extra_info_enabled", lambda: False)())
    dlg = _ModernProgressDialog(text, tr("btn.optimize"), parent=window)
    dlg.setRange(0, 100)
    dlg.setValue(0)
    dlg.show()
    QApplication.processEvents()

    cancel_event = threading.Event()
    solver_lock = threading.Lock()
    active_solvers: list[Any] = []
    progress_lock = threading.Lock()
    start_ts = float(time.monotonic())
    progress_state: Dict[str, float] = {
        "current": 0.0,
        "total": 0.0,
    }
    done_event = threading.Event()
    last_progress_current = 0

    def _is_cancelled() -> bool:
        return bool(cancel_event.is_set())

    def _register_solver(solver_obj: Any) -> None:
        with solver_lock:
            active_solvers.append(solver_obj)

    def _report_progress(current: int, total: int) -> None:
        with progress_lock:
            prev_current = int(progress_state.get("current", 0) or 0)
            prev_total = int(progress_state.get("total", 0) or 0)
            new_current = max(int(prev_current), max(0, int(current or 0)))
            new_total = max(int(prev_total), max(0, int(total or 0)))
            progress_state["current"] = float(new_current)
            progress_state["total"] = float(new_total)

    def _refresh_progress() -> None:
        nonlocal last_progress_current
        if cancel_event.is_set():
            return
        with progress_lock:
            current = int(progress_state.get("current", 0))
            total = int(progress_state.get("total", 0))
        if total <= 0:
            return
        pct = max(0, min(100, int(round((float(current) / float(total)) * 100.0))))
        if int(current) != int(last_progress_current):
            last_progress_current = int(current)
        # Avoid showing "100%" while work is still running; this looks stuck.
        if not done_event.is_set() and pct >= 100:
            pct = 99
        dlg.setValue(pct)
        elapsed_s = max(0, int(round(float(time.monotonic()) - float(start_ts))))
        elapsed_txt = f"{elapsed_s // 60:02d}:{elapsed_s % 60:02d}"
        if not show_extra:
            label_text = f"{text} ({pct}%)"
        elif not done_event.is_set() and int(current) >= int(total):
            label_text = f"{text} (Finalisierung, {current}/{total}, {pct}%, Laufzeit {elapsed_txt})"
        else:
            label_text = f"{text} ({current}/{total}, {pct}%, Laufzeit {elapsed_txt})"
        dlg.setLabelText(label_text)
        if show_extra:
            window.statusBar().showMessage(label_text)

    progress_timer = QTimer(dlg)
    progress_timer.timeout.connect(_refresh_progress)
    progress_timer.start(120)

    def _request_cancel() -> None:
        cancel_event.set()
        dlg.setLabelText(tr("opt.cancelled"))
        with solver_lock:
            solvers = list(active_solvers)
        for solver in solvers:
            try:
                if hasattr(solver, "StopSearch"):
                    solver.StopSearch()
                elif hasattr(solver, "stop_search"):
                    solver.stop_search()
            except Exception:
                continue

    dlg.canceled.connect(_request_cancel)

    wait_loop = QEventLoop()
    out: Dict[str, Any] = {}
    err: Dict[str, str] = {}
    worker = _TaskWorker(lambda: work_fn(_is_cancelled, _register_solver, _report_progress))

    def _on_finished(result: Any) -> None:
        out["result"] = result
        done_event.set()
        wait_loop.quit()

    def _on_failed(msg: str) -> None:
        err["msg"] = str(msg)
        done_event.set()
        wait_loop.quit()

    worker.signals.finished.connect(_on_finished)
    worker.signals.failed.connect(_on_failed)
    QThreadPool.globalInstance().start(worker)
    wait_loop.exec()

    progress_timer.stop()
    dlg.close()
    dlg.deleteLater()
    QApplication.processEvents()
    if "msg" in err:
        raise RuntimeError(err["msg"])
    return out.get("result")
