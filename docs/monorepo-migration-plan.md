# Monorepo Migration Plan

## Goal

Keep desktop stable while adding Android and shared service layers in one repository.

## Target Layout

```txt
apps/
  desktop/
  android/
packages/
  core-py/
  contracts/
services/
  optimizer-api/
```

## Principles

1. No big-bang move of the existing `app/` package.
2. Shared business logic moves to `packages/core-py` incrementally.
3. Android never calls optimizer internals directly; it uses `optimizer-api`.
4. Contracts are explicit and versioned in `packages/contracts`.

## Incremental Steps

1. Scaffold shared layers (done in this iteration).
2. Move pure domain modules from `app/domain` to `packages/core-py`.
3. Move optimizer engines from `app/engine` to `packages/core-py`.
4. Replace API scaffold result with real optimizer execution.
5. Bootstrap Android app and integrate API contract.
6. Add cross-surface golden tests for deterministic parity.

## Definition of Done Per Step

1. Desktop app still starts and existing tests keep passing.
2. New package has tests and CI coverage.
3. No duplicated optimizer logic across desktop and service.
4. Contract changes are documented and versioned.
