# RW5 Revenue Dashboard Improvement Roadmap

Last updated: 2026-07-23

Status: Draft implementation roadmap. Items remain in scope unless they are
explicitly rejected or replaced in the decision log.

## Purpose

This roadmap turns the July 2026 project review into an ordered implementation
plan. The first objective is to make every displayed financial result
trustworthy and visibly qualified by source completeness. Performance,
security, usability, and richer decision support follow after that foundation
is in place.

## Guiding decisions

- Keep FastAPI, `app_core`, and the buildless JavaScript frontend.
- Do not introduce a frontend framework unless the existing approach becomes a
  demonstrated constraint.
- Treat missing data as unknown, never as zero.
- Never publish a monthly or YTD export before its completeness checks pass.
- Separate official contractual reporting from user-created scenarios.
- Put business controls near the views they affect; move technical diagnostics
  out of the primary workflow.
- Prefer a smaller number of meaningful, actionable metrics over additional
  descriptive charts.

## Roadmap overview

| Phase | Outcome | Priority | Depends on |
|---|---|---:|---|
| 0 | Trustworthy calculations and explicit completeness | P0 ✅ | None |
| 1 | Safe, recoverable data publication | P0 | Phase 0 completeness rules |
| 2 | Faster and secured application delivery | P1 | Stable data contract |
| 3 | Responsive, clearer dashboard workflow | P1 | Phases 0 and 2 |
| 4 | Stronger commercial and operational decision support | P2 | Trusted metrics |
| 5 | Maintainable packages and development standards | P2 | Can progress incrementally |
| 6 | Regression protection, monitoring, and operating procedures | Continuous | All phases |

## Phase 0 — Calculation correctness and data trust

> **Status (2026-07-23): COMPLETE.** 0.1–0.5 implemented and verified (48 tests).
> 0.6 skipped by owner decision. Remaining open items are noted inline: SCADA
> excluded/future taxonomy (partial), blocking thresholds (intentionally warn-only),
> commercial-owner validation of provisional terms, and MTD (superseded by extrapolation).

### 0.1 Null-safe and empty-period calculations

- [x] Replace aggregate calls that turn all-missing columns into zero with
      null-preserving calculations such as `sum(min_count=1)`.
- [x] Apply the same rule to summary, monthly, benchmark, bridge, and narrative
      calculations.
- [x] Reject `start_date > end_date` with a clear client error.
- [x] Return an explicit no-data result for valid ranges containing no rows.
- [x] Prevent empty periods from producing “Positive”, zero-revenue, or other
      interpretive statements.
- [x] Normalize negative zero before display and export.

Acceptance criteria:

- An all-NaN revenue series displays `—` or “Unavailable”, never `€0`.
- An empty selection produces no financial narrative or positive/negative
  status.
- Invalid ranges return a validated 4xx response.
- Unit tests cover empty frames, all-NaN columns, zero denominators, and
  negative zero.

### 0.2 Unambiguous percentage semantics

- [x] Make the percent-labelled UI consistently interpret `1` as 1% and `0.5`
      as 0.5%.
- [x] Replace the mixed fraction/percentage API convention with an explicit
      contract.
- [x] Preserve backward compatibility only through a clearly deprecated legacy
      parameter if existing external clients require it.
- [x] Add input bounds and validation for discount, floor, GvO, strike price,
      anomaly row count, resampling rule, and chart group.

Acceptance criteria:

- UI, API schema, assumptions table, calculations, and tests all use the same
  percentage convention.
- Invalid or non-finite inputs cannot enter calculations.

### 0.3 Source-aware completeness

- [x] Define required source columns for market price, nomination, metering,
      imbalance, and SCADA.
- [x] Calculate completeness by source, date, month, and selected period.
- [x] Report missing dates and intervals, not only a total missing-cell count.
- [x] Track first timestamp, last timestamp, last complete timestamp, coverage
      percentage, and freshness for each source.
- [x] Add a completeness status to every aggregate payload.
- [ ] Distinguish missing source data, deliberately excluded SCADA intervals,
      frozen signals, and unavailable future intervals. (Partial: frozen/excluded
      SCADA handled via the valid-interval mask; the full future/excluded taxonomy
      is not yet split out.)
- [ ] Define blocking and warning thresholds for financial reporting. (Deferred:
      a warn-only model was chosen — gaps annotate totals, never block. Revisit if
      hard blocking is required.)

Initial known gaps in the July 2026 YTD export:

- Nomination data is missing for 96 intervals on 2026-01-01.
- EPEX price data is missing for 96 intervals on 2026-07-01.
- Total revenue is missing for 192 intervals across those dates.
- SCADA-derived analysis has additional excluded or unavailable intervals and
  currently ends before the market dataset.

Acceptance criteria:

- A user can identify the affected source, dates, and impact from the main
  dashboard without opening the recognized-columns table.
- Financial totals affected by missing required inputs are visibly marked
  incomplete and cannot appear as fully trustworthy totals.

### 0.4 Partial-period handling

- [x] Mark the current month as partial.
- [x] Show the coverage date or elapsed-day fraction in monthly tables and
      charts.
- [x] Avoid visually comparing a partial month directly with completed months
      without qualification.
- [ ] Add month-to-date comparisons using equivalent elapsed periods where
      useful. (Superseded: implemented run-rate extrapolation of the partial month
      to a full-month estimate instead, for additive metrics only.)

### 0.5 Effective-dated commercial assumptions

- [x] Decide whether Greenchoice and strike-price calculations are official
      contractual reporting, scenario analysis, or both.
- [x] Store official terms with effective start and end dates.
- [x] Keep user-entered scenarios separate from official results and label them
      visibly.
- [x] Add contract examples for positive, zero, and negative EPEX prices,
      including floor, GvO, and billable-price clipping behavior.
- [ ] Validate contract rules with the commercial owner before treating them as
      official KPIs. (Pending: official terms seeded provisionally with the current
      app defaults — 17% / €10 floor / €0 GvO — in app_core/contracts.py.)

### 0.6 Metric naming and interpretation

> **Skipped** — not needed (owner decision, 2026-07-23).

- [ ] Rename “Below-strike revenue” to “Nomination revenue during below-strike
      periods” unless a true lost-revenue calculation is added.
- [ ] Report below-strike exposure in both intervals and hours.
- [ ] Rename the global “Resampling” control to “Chart resolution”.
- [ ] Clearly distinguish revenue, avoided cost, loss, exposure, benchmark, and
      variance throughout the UI.

## Phase 1 — Pipeline integrity and publication safety

### 1.1 Detect all missing daily partitions

- [ ] Scan the expected calendar range for missing daily files instead of only
      continuing after the latest existing file.
- [ ] Include missing whole-day files in repair reporting.
- [ ] Make the lookback window a retry optimization, not the only integrity
      check.
- [ ] Use Amsterdam calendar days with DST-aware expected interval counts.

### 1.2 Validate before publish

- [ ] Build daily, monthly, and YTD outputs into staging paths.
- [ ] Validate expected dates, expected interval counts, duplicate timestamps,
      required columns, required-source completeness, and revenue identities.
- [ ] Do not upload a replacement monthly or YTD export when any required day
      failed.
- [ ] Promote validated outputs atomically.
- [ ] Preserve the previous valid export when a run fails.
- [ ] Publish a machine-readable dataset manifest containing version, creation
      time, source coverage, row count, date range, schema version, and quality
      result.

Acceptance criteria:

- A simulated source failure cannot replace a valid export with a partial one.
- A missing historical day is detected automatically on the next scheduled
  integrity scan.
- Every dashboard dataset can be traced to a manifest and pipeline run.

### 1.3 Harden source adapters

- [ ] Map E-View channels by stable channel ID or validated name rather than
      response order.
- [ ] Validate upstream schemas and fail with source-specific messages.
- [ ] Distinguish transient errors from permanent schema or authentication
      failures when retrying.
- [ ] Make daily market writes atomic, matching the safer SCADA write pattern.
- [ ] Add idempotency tests for generation, repair, rebuild, and upload.

### 1.4 Operational alerts

- [ ] Emit a clear run summary with changed, incomplete, failed, and published
      dates.
- [ ] Alert when publication is blocked, freshness exceeds its SLA, or gaps
      remain after repair.
- [ ] Document recovery and rollback procedures.

## Phase 2 — Backend performance and security

### 2.1 Cached data snapshots

- [ ] Introduce a `DataSnapshot` or repository service keyed by blob name and
      blob ETag/version.
- [ ] Download and parse a dataset once per version rather than once per route.
- [ ] Reuse parsed timestamps, base diagnostics, and completeness metadata.
- [ ] Define cache size, invalidation, startup, and failure behavior.
- [ ] Expose cache/dataset version in API responses for traceability.

### 2.2 Reduce request and payload volume

- [ ] Replace the initial fan-out with one dashboard bootstrap endpoint or a
      small number of purpose-specific bundles.
- [ ] Remove the extra pre-refresh monthly request.
- [ ] Add a server-side point budget and deterministic downsampling for charts.
- [ ] Default long periods to an appropriate chart resolution.
- [ ] Avoid sending full row tables when the frontend only needs series.
- [ ] Add compression and cache validators where supported.

Target:

- One dataset read/parse per blob version.
- Fast repeat interactions for date, assumption, and tab changes.
- Initial payloads remain usable on ordinary mobile and office connections.

### 2.3 Authentication and authorization

- [ ] Confirm whether Azure Easy Auth/Entra ID is enforced outside the
      application.
- [ ] If not, add Entra ID authentication before broader use.
- [ ] Define viewer, analyst/download, and operator permissions if different
      access levels are needed.
- [ ] Protect CSV downloads with the same authorization as dashboard data.

### 2.4 API and browser hardening

- [ ] Restrict CORS to approved origins or remove it for same-origin deployment.
- [ ] Validate `dataset` against the authorized dataset catalog.
- [ ] Add rate/resource limits for expensive endpoints.
- [ ] Add security headers and a content security policy.
- [ ] Self-host the pinned Plotly bundle and required fonts/assets.
- [ ] Avoid returning raw upstream exception details to end users.

## Phase 3 — Dashboard usability and responsive behavior

### 3.1 Plotly lifecycle and responsive layout

- [ ] Centralize Plotly configuration with responsive behavior and no vendor
      logo.
- [ ] Resize charts when a hidden tab becomes active.
- [ ] Give grid and chart children `min-width: 0`.
- [ ] Fix the non-wrapping page title and remaining horizontal page overflow.
- [ ] Fix the invalid `--danger` CSS variable declaration.
- [ ] Verify 390px, tablet, laptop, and large desktop layouts.

Acceptance criteria:

- Opening any tab at 390px produces no document-level horizontal scrolling.
- Charts resize after tab switches and viewport changes.
- Tables may scroll inside their own containers without widening the page.

### 3.2 Mobile control workflow

- [ ] Collapse filters behind a summary/action bar on narrow screens.
- [ ] Keep selected period and refresh state visible without forcing users
      through the full control form.
- [ ] Move chart resolution and zoom controls into the time-series section.
- [ ] Move anomaly row count into the anomalies section.
- [ ] Preserve filters in the URL or session state where appropriate.

### 3.3 Simplify the primary UI

- [ ] Replace raw blob paths with friendly dataset labels and dates.
- [ ] Group or hide technical monthly datasets from normal source selection.
- [ ] Move “Recognized columns” into advanced diagnostics.
- [ ] Put period-level anomaly rows behind event details or remove them from the
      default layout.
- [ ] Keep the event-level anomaly-to-chart inspection workflow.
- [ ] Replace repetitive narrative text with driver-based insight; remove
      narrative bullets that only restate KPI cards.
- [ ] Improve loading skeletons and distinguish total failure from optional
      section failure.

### 3.4 Accessibility and presentation QA

- [ ] Add automated accessibility checks.
- [ ] Verify keyboard navigation, focus states, table semantics, contrast, and
      non-color status cues.
- [ ] Add unit labels and definitions consistently to tooltips and downloads.
- [ ] Ensure partial and incomplete states remain clear in exports and print
      views.

## Phase 4 — Commercial and operational decision support

### 4.1 Source-health overview

- [ ] Add a compact source-health strip for market, nominations, metering,
      imbalance, and SCADA.
- [ ] Add a completeness/freshness detail view with a calendar or heatmap.
- [ ] Link affected metrics back to their missing-source explanation.

### 4.2 Revenue-driver decomposition

- [ ] Attribute performance to nomination volume error, EPEX price/capture,
      imbalance settlement, technical loss, curtailment/EMS loss, and
      underperformance.
- [ ] Show impact in EUR, EUR/MWh, MWh, and percentage where meaningful.
- [ ] Reconcile driver components to the reported total.
- [ ] Distinguish controllable, contractual, market, and data-quality effects.

### 4.3 Targets and comparisons

- [ ] Add budget/target data after its authoritative source is selected.
- [ ] Add prior-period and equivalent month-to-date comparisons.
- [ ] Include imbalance cost per delivered MWh and capture spread against a
      relevant benchmark.
- [ ] Consider normalized turbine measures such as MWh/MW when comparing
      periods.

### 4.4 Actionable anomaly model

- [ ] Replace fixed generic severity thresholds with domain-calibrated rules.
- [ ] Separate adverse events, opportunities, data-quality events, and SCADA
      warnings.
- [ ] Use stable baselines so every selected period does not automatically
      manufacture “anomalies” from its top/bottom quantiles.
- [ ] Add expected range, likely driver, evidence, and financial/energy impact.
- [ ] Decide whether acknowledgement, assignment, notes, and resolved status
      belong in this dashboard or in an external workflow tool.

### 4.5 Forward-looking analysis

- [ ] Decide whether forecasts, expected production, forward prices, or
      nomination recommendations are in scope.
- [ ] Add them only after historical data quality and metric reconciliation are
      reliable.

## Phase 5 — Code structure and maintainability

### 5.1 Package the pipeline

- [ ] Add a proper `pipeline` package and module entry points.
- [ ] Replace bare local imports with package imports.
- [ ] Split `pipeline_lib.py` into focused modules:
      `sources/`, `transforms/`, `quality/`, `storage/`, and `publishing/`.
- [ ] Keep orchestration scripts thin and testable.
- [ ] Move configuration into typed settings loaded at entry points.

### 5.2 Typed application contracts

- [ ] Add Pydantic request/response models for public API payloads.
- [ ] Use enums for chart groups, resampling rules, anomaly types, and dataset
      types.
- [ ] Version the dataset and API schemas.
- [ ] Centralize column metadata and required-source definitions.

### 5.3 Frontend organization

- [ ] Keep the current module-based frontend.
- [ ] Centralize chart configuration and resize behavior.
- [ ] Separate bootstrap data loading from section-specific interactions.
- [ ] Add a small testable state/query layer before considering any framework.

### 5.4 Repository cleanup

- [ ] Remove or move superseded executable-looking reference scripts into
      non-executable documentation/archive material.
- [ ] Fix stale script and environment-variable references in documentation.
- [ ] Keep `pyproject.toml` and `uv.lock` as dependency sources of truth and
      regenerate `requirements.txt` for Azure.
- [ ] Add formatting, linting, and type-checking configuration.

## Phase 6 — Tests, validation, and observability

### 6.1 Repair existing validation

- [ ] Update `scripts/validate_shared_calculations.py` to current anomaly keys
      and SCADA dtypes.
- [ ] Make the documented real-data validation command part of CI using a small
      sanitized fixture.

### 6.2 Calculation and domain tests

- [ ] Add tests for all-NaN and partially missing metrics.
- [ ] Add tests for invalid and empty date ranges.
- [ ] Add percentage-boundary tests including 0.5%, 1%, and 100%.
- [ ] Add Greenchoice contract examples for negative prices and floor behavior.
- [ ] Add strike-price and below-strike duration tests.
- [ ] Add weighted aggregation and reconciliation tests.
- [ ] Add Amsterdam DST spring-forward and fall-back dashboard tests, including
      unambiguous repeated local times.

### 6.3 API and browser tests

- [ ] Add FastAPI integration tests for every route, validation error, dataset
      authorization, CSV download, and incomplete-data payload.
- [ ] Add frontend unit tests for query construction, formatting, tabs, and
      incomplete-state rendering.
- [ ] Add a browser smoke test for initial load, period changes, tab switching,
      anomaly details, anomaly inspection, and mobile overflow.

### 6.4 CI quality gates

- [ ] Run unit, API, validation, lint, type, and frontend checks before deploy.
- [ ] Fail deployment when the real-data fixture validation fails.
- [ ] Keep deployment artifacts free of local data, secrets, caches, logs, and
      virtual environments.
- [ ] Add a production smoke check after deployment.

### 6.5 Runtime observability

- [ ] Add health/readiness endpoints.
- [ ] Record dataset version, ETag, cache status, endpoint latency, payload
      size, and error counts.
- [ ] Log pipeline run IDs and dataset manifest versions.
- [ ] Alert on stale data, blocked publication, repeated source failures, and
      abnormal incompleteness.

## Explicit keep/change/remove list

### Keep

- FastAPI serving both API and static frontend.
- Shared calculation logic in `app_core`.
- Buildless JavaScript modules.
- Monthly, selected-period, anomaly, and quality concepts.
- SCADA energy/loss analysis.
- Event-level anomaly details and inspect-in-charts workflow.
- CSV exports, after completeness metadata is added.

### Change

- Financial aggregation semantics.
- Percentage input/API semantics.
- Data-quality model and its placement in the primary workflow.
- Pipeline publication and recovery process.
- API request/caching strategy.
- Plotly lifecycle and mobile filter workflow.
- Commercial assumption storage and labelling.
- Anomaly severity and business interpretation.
- Technical dataset labels and control placement.

### Remove or move out of the primary workflow

- Raw blob-path presentation for ordinary users.
- Recognized-columns table as a main business view.
- Default display of period-level anomaly tables.
- Narrative bullets that only repeat KPI values.
- Superseded one-off Python scripts from executable source folders.

### Not planned

- A frontend framework rewrite solely for modernization.
- Additional decorative dashboards before correctness and completeness are
  solved.
- Forecasting or automated recommendations before historical metrics reconcile.

## Open decision log

| ID | Decision | Current state |
|---|---|---|
| D1 | Is Azure Easy Auth already mandatory in production? | Confirm before Phase 2 security work |
| D2 | Are Greenchoice and strike results official contract reporting, scenarios, or both? | Required for Phase 0.5 |
| D3 | What is the authoritative budget/target source? | Required for Phase 4.3 |
| D4 | Which users need dataset selection and raw diagnostic tables? | Required for Phase 3 simplification |
| D5 | Should anomaly acknowledgement live here or in another workflow system? | Required for Phase 4.4 |
| D6 | What completeness threshold blocks publication versus only warns? | Required for Phases 0 and 1 |
| D7 | Which source and metric freshness SLAs apply? | Required for source-health statuses and alerts |

## Recommended first implementation slice

Start with a small vertical slice that proves the trust model:

1. Implement null-safe aggregates and date/input validation.
2. Fix percentage semantics.
3. Add source completeness metadata for summary and monthly payloads.
4. Mark incomplete and partial periods in the monthly UI.
5. Add calculation, API, and browser tests for those behaviors.
6. Repair the standalone real-data validator and run it in CI.

Do not start caching or redesigning the frontend until this slice defines the
stable data and completeness contract they will consume.

## Definition of done for the roadmap

The roadmap is complete when:

- Every financial metric declares whether its required inputs are complete.
- No failed pipeline run can replace a valid export with a partial one.
- Dataset versions and quality status are traceable end to end.
- Normal dashboard interactions reuse cached data and meet agreed latency and
  payload targets.
- Authentication, dataset authorization, and downloads follow the agreed
  production access model.
- Mobile and desktop workflows pass browser and accessibility checks.
- Commercial assumptions are versioned and official results are distinguishable
  from scenarios.
- CI covers calculations, APIs, the real-data fixture, and core browser flows.

