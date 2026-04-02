## Desktop App

This folder is the monorepo entrypoint for the desktop application.

Current state:
- Runtime code lives in `apps/desktop/src/desktop_app`.
- `run_desktop.py` is a convenience launcher for local development.

Run (from repo root):
```powershell
python .\apps\desktop\run_desktop.py
```

Alternative:
```powershell
$env:PYTHONPATH = ".\apps\desktop\src"
python -m desktop_app
```
