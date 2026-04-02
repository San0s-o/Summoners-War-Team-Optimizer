## Desktop App

This folder is the monorepo entrypoint for the existing desktop application.

Current state:
- Runtime code still lives in the repository root `app/` package.
- This folder provides a stable place for desktop-specific scripts and docs.

Run (from repo root):
```powershell
python -m app
```

Future migration target:
- Move desktop-specific UI/runtime modules into `apps/desktop/src`.
- Keep shared optimization/domain logic in `packages/core-py`.
