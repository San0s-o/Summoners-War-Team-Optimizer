from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .schemas import (
    AccountDetails,
    AccountSummary,
    ImportAccountRequest,
    OptimizeJobAccepted,
    OptimizeJobRequest,
    OptimizeJobStatus,
)
from .service import account_store, job_store

app = FastAPI(title="SWTO Optimizer API", version="0.1.0")


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/accounts/import", response_model=AccountSummary)
def import_account(payload: ImportAccountRequest) -> AccountSummary:
    try:
        return account_store.import_account(payload.account_id, payload.raw_json)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"import_failed:{exc}") from exc


@app.get("/api/v1/accounts/{account_id}", response_model=AccountDetails)
def get_account(account_id: str) -> AccountDetails:
    details = account_store.get_account_details(account_id)
    if details is None:
        raise HTTPException(status_code=404, detail="account_not_found")
    return details


@app.post("/api/v1/optimize/jobs", response_model=OptimizeJobAccepted, status_code=202)
def create_optimize_job(payload: OptimizeJobRequest) -> OptimizeJobAccepted:
    return job_store.create_job(payload)


@app.get("/api/v1/optimize/jobs/{job_id}", response_model=OptimizeJobStatus)
def get_optimize_job(job_id: str) -> OptimizeJobStatus:
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return job
