from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app.domain.models import AccountData
from app.domain.monster_db import MonsterDB
from app.importer.sw_json_importer import load_account_from_data
from .schemas import (
    AccountDetails,
    AccountSummary,
    AccountUnit,
    JobStatus,
    OptimizeJobAccepted,
    OptimizeJobRequest,
    OptimizeJobStatus,
)


@dataclass(frozen=True)
class ImportedAccount:
    account_id: str
    summary: AccountSummary
    account_data: AccountData


_MONSTER_DB: MonsterDB | None = None


def _monster_db() -> MonsterDB:
    global _MONSTER_DB
    if _MONSTER_DB is None:
        project_root = Path(__file__).resolve().parents[4]
        assets = project_root / "app" / "assets"
        db = MonsterDB(
            assets / "monsters.json",
            project_root / "app" / "domain" / "monster_meta.json",
        )
        db.load()
        _MONSTER_DB = db
    return _MONSTER_DB


class InMemoryJobStore:
    def __init__(self, accounts: "InMemoryAccountStore") -> None:
        self._jobs: dict[str, OptimizeJobStatus] = {}
        self._lock = Lock()
        self._accounts = accounts

    def create_job(self, request: OptimizeJobRequest) -> OptimizeJobAccepted:
        job_id = str(uuid4())
        account = self._accounts.get_account(request.account_id)
        account_summary = account.summary.model_dump() if account else None
        job = OptimizeJobStatus(
            job_id=job_id,
            status=JobStatus.QUEUED,
            created_at=OptimizeJobStatus.now_utc(),
            result={
                "mode": request.mode.value,
                "account_id": request.account_id,
                "payload_echo": request.payload,
                "account_summary": account_summary,
                "note": "Execution scaffold active. Real optimizer execution comes next.",
            },
        )
        with self._lock:
            self._jobs[job_id] = job
        return OptimizeJobAccepted(job_id=job_id)

    def get_job(self, job_id: str) -> OptimizeJobStatus | None:
        with self._lock:
            return self._jobs.get(job_id)


class InMemoryAccountStore:
    def __init__(self) -> None:
        self._accounts: dict[str, ImportedAccount] = {}
        self._lock = Lock()

    def import_account(self, account_id: str | None, raw_json: dict | str) -> AccountSummary:
        resolved_account_id = (account_id or "").strip() or str(uuid4())
        account = load_account_from_data(raw_json)
        summary = AccountSummary(
            account_id=resolved_account_id,
            units=len(account.units_by_id),
            runes=len(account.runes),
            artifacts=len(account.artifacts),
            siege_teams=len(account.siege_def_teams()),
            arena_def_units=len(account.arena_def_team()),
            arena_offense_teams=len(account.arena_offense_decks(limit=9999)),
            rta_active_units=len(account.rta_active_unit_ids()),
            imported_at=OptimizeJobStatus.now_utc(),
        )
        with self._lock:
            self._accounts[resolved_account_id] = ImportedAccount(
                account_id=resolved_account_id,
                summary=summary,
                account_data=account,
            )
        return summary

    def get_account(self, account_id: str) -> ImportedAccount | None:
        with self._lock:
            return self._accounts.get(account_id)

    def get_account_details(self, account_id: str) -> AccountDetails | None:
        imported = self.get_account(account_id)
        if imported is None:
            return None
        account = imported.account_data
        db = _monster_db()

        units: list[AccountUnit] = []
        for unit in sorted(
            account.units_by_id.values(),
            key=lambda u: (-int(u.unit_level or 0), int(u.unit_master_id or 0), int(u.unit_id or 0)),
        ):
            runes = len(account.equipped_runes_for(unit.unit_id, mode="pve"))
            artifacts = len(
                [a for a in account.artifacts if int(a.occupied_id or 0) == int(unit.unit_id)]
            )
            units.append(
                AccountUnit(
                    unit_id=int(unit.unit_id),
                    unit_master_id=int(unit.unit_master_id),
                    name=db.name_for(int(unit.unit_master_id)),
                    element=db.element_for(int(unit.unit_master_id)),
                    level=int(unit.unit_level or 0),
                    grade=int(unit.unit_class or 0),
                    equipped_runes=int(runes),
                    equipped_artifacts=int(artifacts),
                )
            )

        return AccountDetails(
            summary=imported.summary,
            units=units,
            siege_teams=account.siege_def_teams(),
            arena_defense=account.arena_def_team(),
            arena_offense=account.arena_offense_decks(limit=9999),
            rta_active=account.rta_active_unit_ids(),
        )


account_store = InMemoryAccountStore()
job_store = InMemoryJobStore(account_store)
