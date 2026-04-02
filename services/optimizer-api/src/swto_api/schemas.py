from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class OptimizeMode(str, Enum):
    SIEGE = "siege"
    WGB = "wgb"
    RTA = "rta"
    ARENA_RUSH = "arena_rush"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class OptimizeJobRequest(BaseModel):
    account_id: str = Field(min_length=1)
    mode: OptimizeMode
    payload: dict[str, Any]


class OptimizeJobAccepted(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.QUEUED


class OptimizeJobStatus(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)


class ImportAccountRequest(BaseModel):
    account_id: str | None = None
    raw_json: dict[str, Any] | str


class AccountSummary(BaseModel):
    account_id: str
    units: int
    runes: int
    artifacts: int
    siege_teams: int
    arena_def_units: int
    arena_offense_teams: int
    rta_active_units: int
    imported_at: datetime


class AccountUnit(BaseModel):
    unit_id: int
    unit_master_id: int
    name: str
    element: str
    level: int
    grade: int
    equipped_runes: int
    equipped_artifacts: int


class AccountDetails(BaseModel):
    summary: AccountSummary
    units: list[AccountUnit]
    siege_teams: list[list[int]]
    arena_defense: list[int]
    arena_offense: list[list[int]]
    rta_active: list[int]
