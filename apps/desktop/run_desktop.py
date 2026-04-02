from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    src = Path(__file__).resolve().parent / "src"
    src_str = str(src)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


if __name__ == "__main__":
    _ensure_src_on_path()
    from desktop_app.ui.main_window import run_app

    run_app()
