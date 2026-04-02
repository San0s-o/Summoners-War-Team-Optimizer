## SWTO Optimizer API

FastAPI service that exposes optimizer workflows for non-Python clients.

Run locally:
```powershell
pip install -e .[dev]
uvicorn swto_api.main:app --reload --port 8080
```

Endpoints:
- `GET /api/v1/health`
- `POST /api/v1/accounts/import`
- `GET /api/v1/accounts/{account_id}`
- `POST /api/v1/optimize/jobs`
- `GET /api/v1/optimize/jobs/{job_id}`

Current status:
- Uses the existing Python SWEX importer for real account JSON parsing.
- Stores imported account data in-memory and serves mobile-ready account details.
- Job execution remains scaffolded, but now includes imported account context.
