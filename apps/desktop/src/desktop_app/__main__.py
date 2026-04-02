from __future__ import annotations

import sys
from pathlib import Path


if __package__ in (None, ""):
    pkg_parent = Path(__file__).resolve().parents[1]
    pkg_parent_str = str(pkg_parent)
    if pkg_parent_str not in sys.path:
        sys.path.insert(0, pkg_parent_str)


def _is_apply_zip_mode(argv: list[str]) -> bool:
    for arg in argv:
        if arg == "--apply-zip-update":
            return True
    return False


def _is_updater_mode(argv: list[str]) -> bool:
    for arg in argv:
        if arg == "--updater-state" or arg.startswith("--updater-state="):
            return True
    return False


if __name__ == "__main__":
    if _is_apply_zip_mode(sys.argv[1:]):
        from desktop_app.update_apply import run_apply_zip_update

        raise SystemExit(run_apply_zip_update(sys.argv[1:]))

    if _is_updater_mode(sys.argv[1:]):
        from desktop_app.updater_main import run_updater

        raise SystemExit(run_updater(sys.argv[1:]))

    from desktop_app.ui.main_window import run_app

    run_app()

