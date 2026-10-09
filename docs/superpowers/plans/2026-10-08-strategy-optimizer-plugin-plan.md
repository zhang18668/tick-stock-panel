# Strategy Optimizer Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the first usable vertical slice of the strategy optimizer plugin described in `docs/superpowers/specs/2026-10-08-strategy-optimizer-plugin-design.md`, without changing existing strategy behavior.

**Architecture:** Add a small versioned optimization gateway contract to the existing backend extension context, keep adaptive search, validation, scoring, and persistence as isolated pure/service modules, and expose them through an in-repository backend extension under `/api/custom/strategy-optimizer`. Add a frontend extension route that consumes the API. Existing backtest execution remains behind the gateway; the plugin will not import provider SDKs or duplicate trading simulation.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest, atomic JSON/JSONL persistence, React/TypeScript, TanStack Query, existing extension registries.

**Spec:** `docs/superpowers/specs/2026-10-08-strategy-optimizer-plugin-design.md`

## Global Constraints

- Only declared parameter contracts and registered signals may be optimized; no guessing ranges from names or historical values.
- API validation rejects unknown fields, non-finite numbers, invalid date ranges, out-of-budget limits, unknown strategies/signals, and invalid fixed parameters.
- Optimization runs are bounded: maximum 10 rounds, 50 candidates per round, finite total candidates, and finite parameter dimensions.
- Cancellation never produces a new recommendation; disconnecting SSE does not cancel a run.
- Ranking uses out-of-sample metrics and hard gates; missing/non-finite metrics are not converted to zero.
- The plugin never modifies, publishes, enables, or invalidates the original strategy.
- Existing behavior must be unchanged when the plugin is unavailable or fails to load.

## Review Focus

- Invalid or incomplete contracts must be reported as non-optimizable and never searched; test with malformed bounds, defaults, and cross-parameter constraints.
- Fixed random seed, input fingerprint, and candidate history must produce identical candidate order and scores; test repeatability and deduplication.
- Cancellation and interrupted persistence must not create Top 3 recommendations; test cancellation before and during a round.
- Corrupt or path-traversing run files must be isolated/rejected without affecting other runs; test atomic writes and path validation.
- Missing/non-finite OOS metrics and hard-gate failures must be excluded from Top 3 even when their raw score is high; test sparse candidates and fewer-than-three results.

### Task 1: Versioned optimizer contracts and pure validation

**Files:**
- Create: `backend/app/strategy_optimizer/contracts.py`
- Create: `backend/app/strategy_optimizer/validation.py`
- Test: `backend/tests/test_strategy_optimizer_contracts.py`

**Interfaces:** Define immutable parameter, signal, strategy contract, run config, candidate, and gateway protocol types. Validation returns normalized values or raises stable `ValueError` messages. Support int, float, bool, enum/select parameters, finite numeric checks, date ranges, budgets, weight totals, gates, and cross-parameter constraint callbacks.

- [ ] Write failing tests for valid contracts, malformed ranges/defaults, unknown fields, non-finite values, invalid weights/budgets, and cross-parameter constraints.
- [ ] Run `pytest tests/test_strategy_optimizer_contracts.py -q` and confirm failure because the module/API is absent.
- [ ] Implement the smallest dataclasses and validation functions required by the tests.
- [ ] Re-run the focused tests, then the full backend test suite.

### Task 2: Adaptive search, normalization, scoring, and Top 3 selection

**Files:**
- Create: `backend/app/strategy_optimizer/search.py`
- Create: `backend/app/strategy_optimizer/scoring.py`
- Test: `backend/tests/test_strategy_optimizer_search.py`
- Test: `backend/tests/test_strategy_optimizer_scoring.py`

**Interfaces:** `AdaptiveSearchService.first_round()`, `next_round()`, `score_candidates()`, and `select_top_candidates()` are deterministic for a supplied seed and contract. Implement 80/20 exploitation/exploration, no duplicate complete parameter+signal combinations, convergence after three improvements below threshold, finite round/candidate limits, robust `[0,1]` normalization, trade-count saturation, hard gates, and diversity filtering.

- [ ] Write failing tests for first-round coverage, deterministic sampling, 80/20 exploration, deduplication, convergence, cancellation stop, metric direction, gates, and fewer-than-three output.
- [ ] Run the focused tests and confirm the expected missing implementation failures.
- [ ] Implement pure deterministic search/scoring with no backtest or filesystem dependency.
- [ ] Run focused tests and the full backend suite.

### Task 3: Atomic run store and lifecycle state machine

**Files:**
- Create: `backend/app/strategy_optimizer/store.py`
- Create: `backend/app/strategy_optimizer/lifecycle.py`
- Test: `backend/tests/test_strategy_optimizer_store.py`
- Test: `backend/tests/test_strategy_optimizer_lifecycle.py`

**Interfaces:** `OptimizationRunStore` manages `manifest.json`, bounded `events.jsonl`, `rounds.jsonl`, `candidates.jsonl`, and `top3.json` below one validated run directory. `RunLifecycle.transition()` enforces the documented state graph. Writes use temp files, flush/fsync, and atomic replacement; reads isolate corrupt runs.

- [ ] Write failing tests for legal/illegal transitions, atomic snapshots, event IDs, path traversal, corruption isolation, and old-schema read-only behavior.
- [ ] Run focused tests and confirm failure.
- [ ] Implement bounded store and state machine.
- [ ] Run focused tests and the full backend suite.

### Task 4: Backend extension gateway and API

**Files:**
- Modify: `backend/app/extensions/contracts.py`
- Modify: `backend/app/extensions/loader.py`
- Create: `backend/app/custom/strategy_optimizer.py`
- Create: `backend/app/strategy_optimizer/manager.py`
- Create: `backend/tests/test_strategy_optimizer_api.py`
- Create: `backend/tests/test_strategy_optimizer_extension.py`

**Interfaces:** Add `StrategyOptimizationGateway` and `ExtensionContext.strategy_optimization` as a versioned, optional contract. The plugin supplies list/contract/runs/run/events/cancel/resume/candidate routes. API performs validation/orchestration only; manager owns background execution, cancellation, bounded events, and shutdown. The initial gateway adapter delegates candidate evaluation to existing optimizer/backtest services where the current host exposes them, and returns an explicit unsupported-capability failure otherwise.

- [ ] Write failing API/extension tests for route registration, unavailable gateway isolation, strict request validation, lifecycle endpoints, cancellation, SSE replay/heartbeat, and no recommendation on cancellation.
- [ ] Run focused tests and confirm failure.
- [ ] Implement the optional contract plumbing, manager, and extension routes without changing core routes.
- [ ] Run focused tests and the full backend suite.

### Task 5: Frontend optimizer extension page

**Files:**
- Create: `frontend/src/custom/strategy-optimizer/extension.tsx`
- Create: `frontend/src/custom/strategy-optimizer/StrategyOptimizerPage.tsx`
- Create: `frontend/src/custom/strategy-optimizer/api.ts`
- Test: `frontend/src/custom/strategy-optimizer/StrategyOptimizerPage.test.tsx`

**Interfaces:** Register static route `/strategy-optimizer` and navigation item through the existing frontend extension registry. The page renders strategy/contract selection, bounded configuration, run state, cancel/resume controls, and Top 3 cards; it must show loading, empty, non-optimizable, validation error, queued/running/cancelling/interrupted/failed/insufficient/succeeded states and remain usable on narrow screens.

- [ ] Write failing component/API tests for registration, request shape, loading/error/running/cancel/success states, and mobile card layout.
- [ ] Run the focused frontend test and confirm failure.
- [ ] Implement the page using existing components/styles and centralized query keys.
- [ ] Run focused frontend tests and `pnpm build`.

### Task 6: Real gateway integration and end-to-end verification

**Files:**
- Modify: `backend/app/strategy_optimizer/gateway.py`
- Modify: `backend/app/strategy_optimizer/manager.py`
- Modify: `backend/tests/test_strategy_optimizer_api.py`
- Modify: `backend/tests/test_strategy_optimizer_gateway.py`

**Interfaces:** Map existing `StrategyEngine`, `StrategyOptimizer`, walk-forward service, matrix cache, and heavy-job limiter into the gateway contract. Preserve signal/transaction semantics and include strategy/version/params/signals/fold/data-generation/cost inputs in the evaluation fingerprint.

- [ ] Write failing integration tests with a fake existing backtest service for OOS-only ranking, cache-key differences, worker failure isolation, and limiter usage.
- [ ] Implement the adapter and manager integration.
- [ ] Run all affected pytest tests, Ruff, frontend tests/build, `git diff --check`, and `git status`.
