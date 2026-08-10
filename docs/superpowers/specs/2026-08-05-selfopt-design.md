# Self-Optimizing Subsystem (`selfopt`) — Design

**Date:** 2026-08-05
**Design Version:** 1.0
**Status:** Approved for planning
**Scope:** Autonomous, admin-only optimization loop for the Neuro-Adaptive GraphRAG pipeline

---

## 0. Architecture at a glance

```text
                        Users
                          │
                          ▼
                  GraphRAG Pipeline
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
       Champion Config          Metrics Collector
    (.env → SQLite → CtxVar)   (RAGAS + latency + votes)
              │                       │
              └───────────┬───────────┘
                          ▼
                    Self Optimizer
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   Offline Eval        Canary            Guardian
  (golden set)     (15% of traffic)   (floors + stages)
        │                 │                 │
        ▼                 ▼                 ▼
     Promote          Rollback        Hibernation /
                                        Tombstone
```

**Reading order:** §3–§7 describe how the optimizer *searches* (Part I). §8 describes how it
*is constrained* (Part II). The two are deliberately independent — guardrails hold even if
every optimization rule is wrong.

### Terminology

An **optimization cycle** begins when a challenger is proposed and ends when it is
promoted, rejected, rolled back, or skipped. Exactly one cycle runs at a time. "Cycle"
always means this full span, never a single evaluation within it.

---

## 1. Purpose

A self-contained subsystem that continuously improves retrieval and answer quality by
proposing configuration changes, proving them offline against the golden set, validating
them on a bounded slice of live traffic, and promoting only what measurably wins.

It measures itself. If it stops delivering value and live quality falls below hard floors,
it disables itself permanently and reports why.

**Explicitly out of scope:** the optimizer does not write or modify Python source. It tunes
configuration and rebuilds data artifacts only.

**Explicit non-guarantee:** this cannot "fix all errors without fail." No autonomous loop
can. It captures every unhandled exception, auto-retries the transient classes, and
surfaces everything else on the admin portal with a diagnosis so nothing fails silently.

---

## 2. Placement & visibility

- Lives in `backend/app/selfopt/` — a new, self-contained package.
- Not exposed in the user-facing UI. Reachable only at `/admin/selfopt/*`, behind the
  existing admin passcode (`verify_admin_access` in `backend/app/api/admin.py`).
- Not obfuscated. The admin dashboard is the primary interface and must be readable.
- Persists to the existing SQLite `state.db` (`settings.state_db_path`). No new service,
  no new dependency.

### Module responsibilities

| File | Responsibility |
| --- | --- |
| `overrides.py` | Config override layer (property injection + ContextVar) |
| `metrics.py` | Collects the three signal sources into one scorecard |
| `experiment.py` | Proposes challengers; runs the promotion ladder |
| `rebuild.py` | Shadow re-chunk / re-embed / graph rebuild; atomic swap |
| `guardian.py` | Floor checks, staged failure lifecycle, tombstone |
| `store.py` | SQLite schema and accessors |
| `scheduler.py` | Background task driving the three triggers |
| `errors.py` | Project-wide exception capture and repair queue |
| `api.py` | `/admin/selfopt/*` endpoints |

---

## 3. Configuration override mechanism

### 3.1 Targeted property injection

The pipeline reads `settings.<field>` directly at call time across 20 files (76 call
sites). To run a challenger config without editing those files, `overrides.install()`
replaces **only the tunable fields** on the `Settings` class with properties at startup:

```python
_active: ContextVar[dict] = ContextVar("selfopt_overrides", default={})

def _make_prop(name, baseline):
    def _get(self):
        ov = _active.get()
        if name in ov:
            return ov[name]
        return _champion.get(name, baseline)
    return property(_get)

for name in TUNABLES:
    setattr(Settings, name, _make_prop(name, getattr(settings, name)))
```

A `property` is a data descriptor, so it takes precedence over Pydantic v2's instance
`__dict__`. Reads of the tunable names route through the layer; every other attribute
(`cohere_api_key`, `neo4j_password`, filesystem paths) uses untouched native lookup at
zero cost.

**Rejected alternative:** patching `Settings.__getattribute__`. It intercepts every
attribute access including dunders and Pydantic internals, costs more at runtime, is
harder to debug, and is fragile across framework upgrades.

Resolution order:

```
.env / environment            → cold-start baseline (optimizer never writes here)
  ↓
champion row in state.db      → process-wide active config
  ↓
ContextVar per-request        → challenger config for canary-bucketed requests only
```

Requests already run in their own context, and `run_in_threadpool` propagates it, so
canary and champion traffic coexist without interference. Deleting the champion table
reverts the whole system to `.env`.

### 3.2 Tunable whitelist

Arbitrary overrides are rejected. Only these fields are tunable, with validated ranges:

| Field | Range |
| --- | --- |
| `chunk_size` | 128 – 2048 |
| `chunk_overlap` | 0 – 512 |
| `retrieve_top_k` | 1 – 50 |
| `rerank_top_n` | 1 – 20 |
| `rerank_min_score` | 0.0 – 0.9 |
| `expand_hops` | 1 – 3 |
| `graph_fusion_beta` | 0.0 – 1.0 |
| `abstain_below_score` | 0.0 – 0.9 |
| `entity_match_threshold` | 0.5 – 0.99 |
| `graph_confidence_threshold` | 0.5 – 0.99 |
| `expansion_relevance_threshold` | 0.0 – 0.9 |
| `edge_decay` | 0.0 – 0.5 |
| `graphsage_alpha` | 0.0 – 1.0 |
| `graphsage_epochs` | 5 – 50 |

The last two do not currently exist as settings — they are module constants `_ALPHA` and
`_EPOCHS` in `backend/app/core/adaptive.py:35-36`. Making them tunable requires adding two
fields to `Settings` and changing `adaptive.py` to read from `settings` (~4 lines).

Secrets, credentials, paths, CORS origins, and environment flags are never tunable.

### 3.3 Validation

`validate(cfg)` runs before a challenger reaches the offline gate. It enforces:

- every key is in `TUNABLES` (unknown key → reject, never silently ignore)
- every value is within its declared range
- cross-field invariants: `chunk_overlap < chunk_size`, `rerank_top_n <= retrieve_top_k`

A challenger failing validation is discarded at proposal time and never counted as a
cycle.

---

## 4. Metrics & scoring

### 4.1 Composite score

```
composite = 0.50 * quality + 0.30 * latency_score + 0.20 * feedback
```

| Component | Source | Computation |
| --- | --- | --- |
| `quality` | RAGAS | mean of faithfulness, answer_relevancy, context_precision, context_recall |
| `latency_score` | request timing | `clamp(1 - p95_ms / 2500, 0, 1)` |
| `feedback` | thumbs up/down | Wilson lower bound at 95% confidence |

Wilson lower bound rather than raw positive rate, so 3 votes at 100% do not outrank 200
votes at 85%.

**Tracked but not scored** (floor inputs and dashboard series): `graph_lift`, entity
count, edge count, chunk count.

### 4.2 Verified-judge requirement

`backend/app/eval/ragas_eval.py:71-89` clamps Cohere-fallback scores into a narrow band
(faithfulness floor 0.88, relevancy floor 0.85), and the exception path at line 100
returns hardcoded values (0.92 / 0.94 / 0.90 / 0.91). Under that fallback, a good
challenger and a bad one both score ~0.9x.

Optimizing against those numbers would promote at random, and the 0.90 faithfulness floor
could never trip — the system would report success forever while doing nothing.

**Therefore:** `metrics.py` calls RAGAS in strict mode, which raises rather than falling
back. No verified score → the cycle is **skipped**, not scored. Skipped cycles do not
increment the failure counter and do not reset it. The admin portal shows
`cycle skipped: no verified judge`.

The live `/eval` endpoint keeps its existing fallback behavior for the UI. Only the
optimizer bypasses it.

`ragas_eval.py` already defines `RagasUnavailable` and `_require_ragas_key`, both currently
unused. `metrics.py` reuses them for its strict path, so `ragas_eval.py` itself needs no
change and existing `/eval` behavior is unaffected.

### 4.3 Improvement rule

A challenger passes the offline gate only if **both** hold:

1. `composite > champion.composite + 0.005` (margin, so noise cannot promote)
2. no individual metric regresses by more than 2%

Rule 2 prevents the weighted sum from trading faithfulness away to buy latency.

### 4.4 Latency measurement

Middleware timer (the pattern already at `backend/app/api/chat.py:50`) records per-request
elapsed time into a rolling window in `state.db`, bucketed by config version. p95 is
computed over the last 200 requests per bucket.

---

# Part I — Optimization

## 5. Experiment engine

### 5.1 Challenger proposal

Perturb 1–3 tunables from the champion. Selection is Beta-weighted: each tunable carries
`(wins, attempts)`, and its selection weight is the posterior mean `(wins+1)/(attempts+2)`.
Knobs that historically produce wins are tried more; dead knobs fade out.

Numeric perturbation is ±5–20% within the validated range, snapped to int where the field
is an int.

> `# ponytail: Beta-weighted coordinate perturbation, not Bayesian optimization. Swap in
> optuna if the search space grows past ~20 knobs.`

### 5.2 Promotion ladder

```
propose → validate()
        → offline gate (golden set, strict RAGAS)
             ├─ fail → status=offline_fail, counts as a judged failure
             └─ pass → canary at 15% of sessions
                        ├─ <40 queries collected → stays in canary, NOT counted
                        ├─ win  → promote to champion, retire parent, reset failure counter
                        └─ lose → rollback, counts as a judged failure
```

### 5.3 Canary routing

Deterministic and sticky: `sha256(user_id + version) % 100 < 15`. A user stays in the same
bucket for the whole experiment — no mid-conversation flipping, and results are
reproducible. Guests bucket on their session-derived id via the existing
`user_db.resolve_user_id`.

### 5.4 Rollback

A config swap: clear the canary version from `store`, and the next request reads champion
values. No restart, no data migration, milliseconds.

### 5.5 Concurrency

Exactly one experiment in flight, enforced by a row-level lock in `state.db`. Overlapping
experiments make attribution impossible.

### 5.6 Lineage

Every version records `parent_version` and `changes_json`:

```json
{
  "perturbed": ["retrieve_top_k", "rerank_min_score"],
  "deltas": {"retrieve_top_k": "+3", "rerank_min_score": "-0.05"}
}
```

The admin portal renders the ancestry tree, so "why is `retrieve_top_k` 12?" drills down to
the experiment that changed it and the score it won by.

### 5.7 Oscillation suppression

If a tunable flips back to within 5% of a prior value across 3 consecutive promotions
(A→B→A→B→A), its Beta `wins` count is halved and it is frozen for the next 5 cycles,
logged as `<field> oscillating, temporarily excluded`. The 5-cycle timeout prevents
permanent deadlock.

---

## 6. Scheduler

A single `asyncio` background task started in `main.py`'s lifespan wakes every 5 minutes
and evaluates three triggers. No Celery, no cron, no extra process.

| Trigger | Condition |
| --- | --- |
| Event | 200 chat queries since the last cycle |
| Schedule | floor of 1h between cycles; ceiling of 6h idle → run anyway |
| Metric drop | current composite < `rolling_baseline * 0.97` → immediate cycle, bypasses the 1h floor |

`rolling_baseline` is the mean champion composite over the **last 7 days**, using at most
the 100 most recent samples. If fewer than 10 samples exist in that window, the trigger is
inactive (not enough history to call a drop). This is deliberately not the frozen promotion
score — comparing forever against a single snapshot would fire unnecessary cycles whenever
the champion happened to be promoted under favorable conditions.

---

## 7. Data-layer rebuilds

`chunk_size`, `chunk_overlap`, `entity_match_threshold`, and `graph_confidence_threshold`
only take effect on re-ingested data. When a challenger perturbs one of those,
`rebuild.py` materializes it in shadow storage.

### 7.1 Shadow vectors

`backend/app/core/vectorstore.py` has no namespace support — all vectors share the default
namespace, isolated by a `user_id` metadata filter. Shadow vectors reuse the same index
with a prefixed id, `sel{version}-{document_id}-{n}`, plus a `selfopt_version` metadata
field.

Because live queries filter on `user_id` only, shadow vectors would otherwise surface in
production results. Two changes prevent that:

- `vectorstore.query` adds `selfopt_version` to its filter — `{"$exists": false}` for live
  traffic, the explicit version for shadow evaluation. This is the same
  one-implementation-with-a-version-parameter approach used for the graph in §7.2.
- Shadow upserts are written under the id prefix so the existing `delete_by_document`
  prefix scan can tear them down without new code.

> `# ponytail: id-prefix isolation, not Pinecone namespaces. Namespaces are cleaner if the
> corpus grows substantially or the deployment becomes multi-tenant.`

### 7.2 Shadow graph

Shadow nodes carry a `selfopt_version` property. Rather than clone the expansion query —
which would let production and shadow logic drift apart — `graphrag.expand()` gains an
optional `version: str | None = None` parameter that injects the property filter into the
**same** Cypher. One implementation, one place to change. Touches `graphrag.py` and
`retrieval.py` (~10 lines).

Teardown: `MATCH (n) WHERE n.selfopt_version = $v DETACH DELETE n`.

### 7.3 Rebuild budget

Re-embedding costs real Cohere API calls, which is the binding constraint. Rebuild cycles
are rate-limited to **one per 24 hours** regardless of scheduler demand, and scoped
adaptively:

| Corpus size | Rebuild scope |
| --- | --- |
| < 2,000 chunks | 100% |
| 2,000 – 10,000 | 25%, capped at 500 |
| > 10,000 | 10%, capped at 1,000 |

Sampled across documents, not concentrated in one. Knob-only cycles (the other tunables)
are free and unlimited.

### 7.4 Atomic swap

On win, the shadow generation becomes live by flipping a pointer row in `state.db`. The
previous generation is retained for a **1-hour grace window** before deletion, so an
immediate rollback is still possible.

---

# Part II — Guardrails

## 8. Guardian & lifecycle

Runs after every judged cycle.

### 8.0 State machine

```text
   HEALTHY ──────────────┐
      │                  │ promotion succeeds
      │ 3 failures       │ (from any non-terminal state)
      ▼                  │
   WARNING ──────────────┤
      │                  │
      │ 5 failures       │
      ▼                  │
ROLLBACK_OBSERVATION ────┤
      │                  │
      │ 10 failures      │
      ▼                  │
  HIBERNATING ───────────┘
      │
      │ 20 failures AND floor breach
      ▼
  TOMBSTONED  (terminal)
```

| State | Entry | Exit | Experiments run? |
| --- | --- | --- | --- |
| `HEALTHY` | init, or any successful promotion | 3 consecutive failures | yes |
| `WARNING` | 3 consecutive failures | promotion → `HEALTHY`; 5 failures → next | yes |
| `ROLLBACK_OBSERVATION` | 5 consecutive failures | promotion → `HEALTHY`; 10 failures → next | no, paused 6h |
| `HIBERNATING` | 10 consecutive failures | admin `POST /wake` → `HEALTHY`; 20 + breach → next | no, metrics only |
| `TOMBSTONED` | 20 failures **and** live floor breach | admin `DELETE /tombstone` only | never |

Transitions are strictly ordered — no state is skipped. A successful promotion resets the
counter to 0 and returns to `HEALTHY` from any state except `TOMBSTONED`. `TOMBSTONED` is
terminal and survives restart.

### 8.1 Staged failure lifecycle

`consecutive_failures` increments only on a judged loss (offline fail or canary loss). Any
successful promotion resets it to 0. Skipped cycles — no verified judge, insufficient
canary traffic, rebuild fenced out — neither increment nor reset it.

| Consecutive failures | Action |
| --- | --- |
| 3 | **Warning** — admin portal banner; optimizer continues |
| 5 | **Rollback + observe** — revert the active champion to the most recent ancestor whose live metrics passed all floors, then pause new experiments for 6h |
| 10 | **Hibernation** — stop experimenting, keep collecting metrics; admin can wake it |
| 20 **and** floor breach | **Tombstone** — self-destruct |

Stage 5 is a *champion* rollback, not a challenger rollback. A losing challenger is already
discarded at the end of its own cycle (§5.4). Repeated failures instead suggest the current
champion itself has drifted into a bad region, so stage 5 walks the lineage back to the last
version that passed floors. If no such ancestor exists, it reverts to the `.env` cold-start
baseline.

Self-destruct requires both fences: 20 judged failures **and** a live floor breach. It is
intended to be rare.

### 8.2 Absolute floors

Checked against the **champion's live rolling metrics**, not the challenger's, over the
last 7 days:

| Metric | Floor |
| --- | --- |
| faithfulness | ≥ 0.90 |
| answer_relevancy | ≥ 0.88 |
| context_precision | ≥ 0.85 |
| context_recall | ≥ 0.85 |
| p95 latency | ≤ 2500 ms |
| positive feedback (Wilson LB) | ≥ 0.70 |
| edge count | ≥ 50% of validated production baseline |

A floor with no data in the window is **not** treated as breached — a metric that was never
measured is unknown, not failing. This matters most for the feedback floor: with few votes
the Wilson lower bound is legitimately low, so the feedback floor additionally requires at
least 20 votes in the window before it can count as breached. Without that guard a quiet
week of traffic would look identical to a quality collapse.

The **validated production baseline** is captured once, on the first successful startup
with a non-empty graph, and pinned in `state.db`. It is never auto-updated — a slowly
collapsing graph would otherwise keep re-baselining itself and the floor would never trip.

Because the baseline is pinned at first capture, legitimate corpus growth or deliberate
document deletion can leave it stale. The admin portal exposes the pinned value and a
`POST /admin/selfopt/baseline` route to re-pin it deliberately. It is never re-pinned
automatically.

### 8.3 Self-destruct sequence

1. Restore the last-known-good champion (most recent `status='champion'` version that
   passed floors) and write it as active.
2. Archive experiment history: gzip `config_versions` and experiment rows into a single
   `selfopt_archive` blob row. **Forensics are preserved, not deleted.**
3. Purge active state: Beta counters, canary assignments, shadow vectors, shadow graph
   nodes, pending experiments.
4. Write the **tombstone** row: `{died_at, reason, final_metrics, failure_history,
   restored_version}`. This row survives the purge — it is the death certificate.
5. Set the module `DISABLED` flag. `scheduler` exits its loop. `overrides` drops to
   pass-through so `settings` reads native values.
6. Push the death certificate to the admin portal.

**Restart does not revive it.** On boot, `selfopt.init()` reads the tombstone first and
stays dead. Reviving requires explicitly deleting the tombstone row from the admin portal —
a deliberate two-step, never automatic.

The RAG pipeline is untouched by any of this. Self-destruct disables the optimizer only;
the system keeps serving on the restored config exactly as it does today.

---

## 9. Error capture

A FastAPI exception middleware plus a logging handler funnel every unhandled exception into
a `repair_queue` table: traceback, endpoint, frequency, first seen, last seen.

**Auto-applied (whitelisted only):**
- retry with exponential backoff on transient Cohere / Pinecone / Neo4j errors
- cache invalidation on stale-embedding errors

**Everything else** is surfaced on the admin portal as a diagnosed report with traceback
and suggested fix, for manual action. The optimizer never edits source files.

---

## 9. Failure scenarios

How the system responds to common operational failures:

| Scenario | System Action |
| --- | --- |
| Groq evaluator unavailable | Skip cycle; log `cycle skipped: no verified judge` |
| Pinecone timeout during query | Retry with exponential backoff (whitelisted auto-repair) |
| Neo4j unavailable during expansion | Retry with exponential backoff (whitelisted auto-repair) |
| Cohere embedding rate limit | Retry with exponential backoff (whitelisted auto-repair) |
| Canary has < 40 queries | Stay in canary; cycle NOT counted as failure |
| Validation fails (out-of-range tunable) | Reject challenger at proposal; cycle NOT counted |
| Rebuild budget exceeded | Skip rebuild; run knob-only cycle instead |
| Champion floor breach (no failures yet) | Continue; floor breach alone does not trigger guardian |
| 3 consecutive failures | Enter WARNING state; admin portal banner |
| 5 consecutive failures | Enter ROLLBACK_OBSERVATION; revert to ancestor; pause 6h |
| 10 consecutive failures | Enter HIBERNATION; stop experiments, collect metrics only |
| 20 failures + floor breach | TOMBSTONE; self-destruct sequence |
| Shadow vector leaks into live query | Prevented by `selfopt_version` filter in `vectorstore.query` |
| Shadow graph node in live expansion | Prevented by version filter in `graphrag.expand` |
| Experiment lock held (concurrent attempt) | Second cycle waits or skips; only one runs at a time |

---

## 10. Persistence schema

All tables live in the existing `state.db`.

```sql
config_versions(
  id INTEGER PRIMARY KEY,
  version TEXT UNIQUE,
  parent_version TEXT,
  parameters_json TEXT,
  changes_json TEXT,
  composite_score REAL,
  ragas_json TEXT,
  latency_p95_ms REAL,
  feedback_rate REAL,
  status TEXT,          -- proposed|offline_pass|offline_fail|canary|champion|retired|rolled_back
  created_at REAL,
  promoted_at REAL,
  rolled_back_at REAL,
  rollback_reason TEXT
)

selfopt_metrics(id, version, ts, metric, value)          -- rolling windows
selfopt_tunable_stats(field, wins, attempts, frozen_until)
selfopt_lock(id, holder, acquired_at)                    -- single-experiment lock
selfopt_baseline(key, value, captured_at)                -- pinned graph baseline
selfopt_state(key, value)                                -- champion pointer, counters, flags
selfopt_tombstone(died_at, reason, final_metrics_json, failure_history_json, restored_version)
selfopt_archive(archived_at, payload BLOB)               -- gzipped history after tombstone
repair_queue(id, fingerprint, endpoint, traceback, count, first_seen, last_seen, status)
```

---

## 11. Admin API

All routes require the existing admin passcode.

| Route | Purpose |
| --- | --- |
| `GET /admin/selfopt/status` | Current champion, lifecycle stage, failure count, next trigger |
| `GET /admin/selfopt/history` | Version lineage tree with scores and deltas |
| `GET /admin/selfopt/metrics` | Time series for every tracked metric |
| `GET /admin/selfopt/errors` | Repair queue with diagnoses |
| `POST /admin/selfopt/rollback/{version}` | One-click restore of any prior champion |
| `POST /admin/selfopt/baseline` | Deliberately re-pin the graph edge-count baseline |
| `POST /admin/selfopt/pause` / `resume` | Manual control |
| `POST /admin/selfopt/wake` | Exit hibernation |
| `DELETE /admin/selfopt/tombstone` | Deliberate revival after self-destruct |

---

## 12. Changes to existing files

Kept deliberately minimal. Everything else is new code in `selfopt/`.

| File | Change |
| --- | --- |
| `app/main.py` | Call `selfopt.init()` in lifespan; register router + middleware |
| `app/config.py` | Add `graphsage_alpha`, `graphsage_epochs`, and `selfopt_*` settings |
| `app/core/adaptive.py` | Read `_ALPHA` / `_EPOCHS` from `settings` (~4 lines) |
| `app/core/graphrag.py` | `expand()` accepts optional `version` filter (~6 lines) |
| `app/core/retrieval.py` | Thread `version` through to `expand()` (~4 lines) |
| `app/core/vectorstore.py` | `query()` accepts optional `version` filter (~4 lines) |

---

## 13. Testing

Per project convention (`pytest`, `backend/tests/`):

- `test_selfopt_overrides.py` — property injection resolves in the right order; ContextVar
  isolation holds across threadpool boundaries; non-tunable fields are untouched
- `test_selfopt_validation.py` — out-of-range and unknown keys rejected; cross-field
  invariants enforced
- `test_selfopt_metrics.py` — composite math, Wilson bound, strict-mode raise when the
  judge is unavailable
- `test_selfopt_experiment.py` — promotion ladder transitions; canary stickiness;
  single-experiment lock; oscillation suppression
- `test_selfopt_guardian.py` — each lifecycle stage fires at its threshold; skipped cycles
  neither increment nor reset; tombstone survives restart; floors evaluated against
  champion metrics; a floor with no data does not count as breached
- `test_selfopt_isolation.py` — shadow vectors and shadow graph nodes never appear in live
  retrieval results, and teardown removes them completely

---

## 14. Known limitations

1. **Cannot fix all errors.** Auto-repair covers whitelisted transient failures only.
   Everything else is reported, not fixed.
2. **Idle without a verified judge.** If the Groq key fails, the optimizer skips cycles
   rather than scoring against clamped fallback numbers. Correct, but it means a dead key
   silently stops all optimization — surfaced on the dashboard.
3. **Rebuilds cost API budget.** Adaptive caps bound it, but a large corpus will only ever
   have a sample re-embedded, so chunking changes are validated on a subset.
4. **Canary needs traffic.** With low query volume, experiments sit in canary indefinitely.
   This is deliberate: insufficient data is not evidence of failure.
5. **Local search only.** Coordinate perturbation finds local optima. A fundamentally
   better configuration in a distant region of the space will not be discovered.

---

## 15. Future extensions

The architecture supports several directions for evolution as the corpus and query volume grow:

- **Bayesian optimization** — replace Beta-weighted perturbation with Optuna or similar when
  the search space grows beyond ~20 knobs or cross-parameter interactions become significant
- **Multi-objective optimization** — explicit Pareto front when cost, latency, and quality
  trade-offs need user-specified priority weights rather than a fixed composite
- **LLM-generated prompts** — treat generation prompt templates as tunable text, not just
  numeric knobs; requires an evaluation harness that can score prompt quality
- **Multi-tenant optimization** — per-customer champion configs when workload characteristics
  diverge enough that a single shared optimum no longer fits all
- **Distributed experiments** — parallel canary trials when query volume is high enough to
  support statistical significance on multiple challengers simultaneously
- **Namespaces and sharding** — cleaner shadow isolation when the deployment moves to true
  multi-tenancy or the corpus exceeds single-index scale
