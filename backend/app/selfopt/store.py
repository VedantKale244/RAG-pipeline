"""SQLite persistence for the self-optimization subsystem.

Every selfopt module — overrides, scorecard, experiment engine, guardian,
scheduler, admin API — reads and writes its durable state through here. Lives in
its own file (``settings.state_db_path``) so the optimizer's bookkeeping never
touches the user-facing databases.

``init_db()`` is deliberately *not* called at import time; ``selfopt.init()``
calls it during app startup, so importing this module (in tests, or from the
admin API) never creates a database as a side effect.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from ..config import settings

# One shared connection: the scheduler is a single background task, so this is a
# single-writer workload. Reset by tests via _reset_conn().
_conn: sqlite3.Connection | None = None
_conn_lock = threading.Lock()

# Columns update_version() is allowed to write. Anything else is a caller bug.
_VERSION_FIELDS = {
    "parent_version",
    "parameters_json",
    "changes_json",
    "composite_score",
    "ragas_json",
    "latency_p95_ms",
    "feedback_rate",
    "status",
    "promoted_at",
    "rolled_back_at",
    "rollback_reason",
}


def get_db() -> sqlite3.Connection:
    """Return the shared state DB connection, opening it on first use."""
    global _conn
    with _conn_lock:
        if _conn is None:
            db_path = Path(settings.state_db_path)
            # .data/ does not exist in a fresh checkout.
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
            conn.row_factory = sqlite3.Row
            # WAL keeps the API readable while a cycle writes.
            conn.execute("PRAGMA journal_mode=WAL")
            _conn = conn
        return _conn


def _reset_conn() -> None:
    """Close and forget the cached connection. Used by tests between cases."""
    global _conn
    with _conn_lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def init_db() -> None:
    """Ensure the nine selfopt tables exist. Idempotent on any database this code
    could have produced.

    One exception, and it is not idempotent there: a database already holding two
    `status='champion'` rows makes the single-champion index below fail with
    `sqlite3.IntegrityError`, which aborts the whole call. The tables are all
    created first so none is left missing, but the index is NOT created and both
    champions survive — the system boots into the exact state the index exists to
    prevent, with the protection silently absent. Only pre-index code could have
    written such a database, and none ever ran; reconciling duplicates on upgrade
    is deferred rather than solved.
    """
    conn = get_db()
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS config_versions (
                id INTEGER PRIMARY KEY,
                version TEXT UNIQUE NOT NULL,
                parent_version TEXT,
                parameters_json TEXT NOT NULL,
                changes_json TEXT NOT NULL,
                composite_score REAL,
                ragas_json TEXT,
                latency_p95_ms REAL,
                feedback_rate REAL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                promoted_at REAL,
                rolled_back_at REAL,
                rollback_reason TEXT
            )
            """
        )
        # At most one champion, enforced by the database rather than by
        # convention. `_champion_row()`'s ORDER BY ... LIMIT 1 is a tiebreak, not
        # an invariant: with two champion rows it silently returns the newest and
        # raises nothing. A promotion that inserts the incoming champion without
        # retiring the outgoing one now fails loudly instead.
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_config_versions_one_champion
            ON config_versions (status) WHERE status = 'champion'
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS selfopt_metrics (
                id INTEGER PRIMARY KEY,
                version TEXT NOT NULL,
                ts REAL NOT NULL,
                metric TEXT NOT NULL,
                value REAL NOT NULL
            )
            """
        )
        # Every scoring read filters on exactly this triple.
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_selfopt_metrics_lookup
            ON selfopt_metrics (version, metric, ts)
            """
        )
        # metrics_since() with version=None cannot use the triple above.
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_selfopt_metrics_metric_ts
            ON selfopt_metrics (metric, ts)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS selfopt_tunable_stats (
                field TEXT PRIMARY KEY,
                wins REAL NOT NULL DEFAULT 0,
                attempts REAL NOT NULL DEFAULT 0,
                frozen_until REAL NOT NULL DEFAULT 0
            )
            """
        )
        # expires_at extends the spec's (id, holder, acquired_at): without a TTL
        # a crashed cycle would hold the lock forever.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS selfopt_lock (
                id INTEGER PRIMARY KEY,
                holder TEXT NOT NULL,
                acquired_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS selfopt_baseline (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                captured_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS selfopt_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS selfopt_tombstone (
                id INTEGER PRIMARY KEY,
                died_at REAL NOT NULL,
                reason TEXT NOT NULL,
                final_metrics_json TEXT NOT NULL,
                failure_history_json TEXT NOT NULL,
                restored_version TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS selfopt_archive (
                id INTEGER PRIMARY KEY,
                archived_at REAL NOT NULL,
                payload BLOB NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS repair_queue (
                id INTEGER PRIMARY KEY,
                fingerprint TEXT UNIQUE NOT NULL,
                endpoint TEXT,
                traceback TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 1,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'open'
            )
            """
        )
        # Append-only audit trail: every self-optimizer action lands here so the
        # admin dashboard can show *all* super-agent activity, even when the UI
        # was closed at the moment it happened.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY,
                at REAL NOT NULL,
                kind TEXT NOT NULL,
                version TEXT,
                detail TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_activity_at ON activity_log (at DESC)"
        )


# --- Key/value state ---

def get_state(key: str, default: str | None = None) -> str | None:
    """Read a state value (champion pointer, counters, lifecycle flags)."""
    with get_db() as conn:
        row = conn.execute("SELECT value FROM selfopt_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_state(key: str, value: str) -> None:
    """Write a state value, replacing any existing entry for the key."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO selfopt_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value)),
        )


def increment_state(key: str, by: int = 1) -> int:
    """Atomically increment a numeric state counter and return the new value.

    Single SQL statement — read-then-write would race on every request, since
    `hooks.record_query` increments this on the hot path for every chat hit.
    """
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO selfopt_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = CAST(value AS INT) + ?
            """,
            (key, str(by), by),
        )
        row = conn.execute("SELECT value FROM selfopt_state WHERE key = ?", (key,)).fetchone()
        return int(row["value"])


def get_baseline(key: str) -> str | None:
    """Read a pinned baseline value (e.g. the graph edge-count floor)."""
    with get_db() as conn:
        row = conn.execute("SELECT value FROM selfopt_baseline WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_baseline(key: str, value: str) -> None:
    """Pin a baseline value with its capture timestamp."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO selfopt_baseline (key, value, captured_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                captured_at = excluded.captured_at
            """,
            (key, str(value), time.time()),
        )


# --- Config versions ---

def _row_to_version(row: sqlite3.Row) -> dict:
    """Expand a config_versions row, parsing its JSON columns into objects."""
    out = dict(row)
    for col in ("parameters_json", "changes_json", "ragas_json"):
        raw = out.get(col)
        out[col] = json.loads(raw) if raw else {}
    return out


def _champion_row() -> sqlite3.Row | None:
    """The active champion row, or None if there is no champion.

    `config_versions.status` is the *sole* source of truth for which version is
    champion. There is deliberately no `champion_version` key in selfopt_state:
    a second copy of the pointer can survive a purge that removes the row it
    names, and the two then disagree with nothing to arbitrate.
    """
    with get_db() as conn:
        return conn.execute(
            """
            SELECT * FROM config_versions
            WHERE status = 'champion'
            ORDER BY promoted_at DESC, created_at DESC
            LIMIT 1
            """
        ).fetchone()


def get_champion() -> dict | None:
    """Return the active champion's parameters, or None if there is no champion.

    None is what makes the whole system fall back to `.env` values.
    """
    row = _champion_row()
    return json.loads(row["parameters_json"]) if row else None


def get_last_champion() -> dict | None:
    """Most recent retired champion, for champion rollback on stage 5.

    "last-known-good" is the newest `status='retired'` row by `promoted_at` — the
    previous champion that held the crown before the current one took it. Promotions
    retire the outgoing champion at the moment the incoming one is promoted, so this
    is the direct predecessor in the lineage.
    """
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM config_versions
            WHERE status = 'retired' AND promoted_at IS NOT NULL
            ORDER BY promoted_at DESC, created_at DESC
            LIMIT 1
            """
        ).fetchone()
        return _row_to_version(row) if row else None


def get_champion_version() -> str | None:
    """Return the active champion's version id, or None if there is no champion.

    Resolves through the same row as `get_champion()`, so the parameters and the
    id they belong to can never disagree.
    """
    row = _champion_row()
    return row["version"] if row else None


def get_version(version: str) -> dict | None:
    """Fetch one config version with its JSON columns parsed into dicts."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM config_versions WHERE version = ?", (version,)
        ).fetchone()
        return _row_to_version(row) if row else None


def get_all_versions() -> list[dict]:
    """All config versions, newest first — the admin history/lineage view."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM config_versions ORDER BY created_at DESC"
        ).fetchall()
        return [_row_to_version(r) for r in rows]


def insert_version(version: str, parent: str | None, params: dict, changes: dict) -> None:
    """Record a newly proposed config version.

    Raises `sqlite3.IntegrityError` if `version` already exists — the column is
    UNIQUE NOT NULL, so a duplicate id is a caller bug, not a recoverable state.
    """
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO config_versions
                (version, parent_version, parameters_json, changes_json, status, created_at)
            VALUES (?, ?, ?, ?, 'proposed', ?)
            """,
            (version, parent, json.dumps(params or {}), json.dumps(changes or {}), time.time()),
        )


def update_version(version: str, **fields) -> None:
    """Update whitelisted columns on a config version. Dict values are JSON-encoded.

    Raises `sqlite3.IntegrityError` on `status="champion"` while another champion
    exists: a partial unique index allows only one. Promotion is therefore
    retire-outgoing *then* promote-incoming, and both writes belong in one
    transaction — committing the retire alone leaves zero champions, which falls
    the whole system back to `.env` with no error anywhere.
    """
    unknown = set(fields) - _VERSION_FIELDS
    if unknown:
        raise ValueError(f"unknown config_versions columns: {sorted(unknown)}")
    if not fields:
        return

    assignments = ", ".join(f"{col} = ?" for col in fields)
    values = [
        json.dumps(v) if isinstance(v, (dict, list)) else v
        for v in fields.values()
    ]
    with get_db() as conn:
        conn.execute(
            f"UPDATE config_versions SET {assignments} WHERE version = ?",
            (*values, version),
        )


def promote(version: str, composite: float) -> None:
    """Retire the outgoing champion and promote `version` atomically.

    A partial unique index allows only one `status='champion'`, so a bare
    update would raise `sqlite3.IntegrityError`. Retiring first and committing
    separately leaves zero champions, which silently drops the whole system
    back to `.env`. Both writes belong in one transaction.
    """
    with get_db() as conn:
        conn.execute(
            "UPDATE config_versions SET status='retired' WHERE status='champion'"
        )
        conn.execute(
            "UPDATE config_versions SET status='champion', promoted_at=?, composite_score=? "
            "WHERE version=?",
            (time.time(), composite, version),
        )
    record_activity(
        KIND_PROMOTE,
        f"promoted to champion (composite {float(composite):.3f})",
        version,
    )


def clear_tombstone() -> None:
    """Delete the death certificate. The only way out of TOMBSTONED."""
    with get_db() as conn:
        conn.execute("DELETE FROM selfopt_tombstone")


# --- Metrics ---

def record_metric(version: str, metric: str, value: float) -> None:
    """Append one metric sample for a config version."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO selfopt_metrics (version, ts, metric, value) VALUES (?, ?, ?, ?)",
            (version, time.time(), metric, float(value)),
        )


def recent_metrics(version: str, metric: str, limit: int = 200) -> list[float]:
    """Most recent samples for a version/metric pair, newest first."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT value FROM selfopt_metrics
            WHERE version = ? AND metric = ?
            ORDER BY ts DESC, id DESC
            LIMIT ?
            """,
            (version, metric, limit),
        ).fetchall()
        return [r["value"] for r in rows]


def metrics_since(metric: str, since_ts: float, version: str | None = None) -> list[float]:
    """Samples for a metric newer than `since_ts`, newest first.

    Used for the rolling baseline, which is a time window rather than a count.
    """
    sql = "SELECT value FROM selfopt_metrics WHERE metric = ? AND ts >= ?"
    params: list = [metric, since_ts]
    if version is not None:
        sql += " AND version = ?"
        params.append(version)
    sql += " ORDER BY ts DESC, id DESC"

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [r["value"] for r in rows]


def count_metrics(version: str, metric: str) -> int:
    """Number of samples recorded for a version/metric pair."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM selfopt_metrics WHERE version = ? AND metric = ?",
            (version, metric),
        ).fetchone()
        return int(row["n"])


# --- Tunable stats (Beta counters for the experiment engine) ---

def get_tunable_stat(field: str) -> dict | None:
    """Win/attempt counters and freeze deadline for one tunable field."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM selfopt_tunable_stats WHERE field = ?", (field,)
        ).fetchone()
        return dict(row) if row else None


def get_all_tunable_stats() -> list[dict]:
    """Counters for every tunable seen so far."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM selfopt_tunable_stats ORDER BY field").fetchall()
        return [dict(r) for r in rows]


def update_tunable_stat(field: str, **fields) -> None:
    """Upsert counters for a tunable. Absent columns keep their current value."""
    allowed = {"wins", "attempts", "frozen_until"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"unknown selfopt_tunable_stats columns: {sorted(unknown)}")
    if not fields:
        return

    updates = ", ".join(f"{col} = excluded.{col}" for col in fields)
    cols = ["field", *fields]
    placeholders = ", ".join("?" for _ in cols)
    with get_db() as conn:
        conn.execute(
            f"""
            INSERT INTO selfopt_tunable_stats ({", ".join(cols)})
            VALUES ({placeholders})
            ON CONFLICT(field) DO UPDATE SET {updates}
            """,
            (field, *fields.values()),
        )


# --- Experiment lock ---

def acquire_lock(holder: str, ttl_s: float = 3600.0) -> bool:
    """Claim the single-experiment lock. False if someone else holds it unexpired.

    INSERT OR IGNORE opens the write transaction before the read, so two racing
    callers cannot both observe an empty row and both claim it.
    """
    conn = get_db()
    with conn:
        # Inside the transaction: acquiring it can block behind another holder
        # for up to the connection timeout, and a TTL measured from a pre-wait
        # clock would expire early.
        now = time.time()
        expires_at = now + ttl_s
        conn.execute(
            """
            INSERT OR IGNORE INTO selfopt_lock (id, holder, acquired_at, expires_at)
            VALUES (1, ?, ?, ?)
            """,
            (holder, now, expires_at),
        )
        row = conn.execute(
            "SELECT holder, expires_at FROM selfopt_lock WHERE id = 1"
        ).fetchone()
        # Ours to refresh, or the previous holder's TTL ran out (crashed cycle).
        if row["holder"] != holder and now < row["expires_at"]:
            return False
        conn.execute(
            "UPDATE selfopt_lock SET holder = ?, acquired_at = ?, expires_at = ? WHERE id = 1",
            (holder, now, expires_at),
        )
        return True


def release_lock(holder: str) -> None:
    """Release the experiment lock. A non-holder's release is a no-op."""
    with get_db() as conn:
        conn.execute("DELETE FROM selfopt_lock WHERE id = 1 AND holder = ?", (holder,))


# --- Tombstone, archive & purge (self-destruct sequence) ---

def get_tombstone() -> dict | None:
    """The death certificate, if the subsystem has self-destructed.

    `selfopt.init()` reads this first and stays dead if it exists.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM selfopt_tombstone ORDER BY died_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        out["final_metrics_json"] = json.loads(out["final_metrics_json"] or "{}")
        out["failure_history_json"] = json.loads(out["failure_history_json"] or "[]")
        return out


def insert_tombstone(
    reason: str,
    final_metrics: dict,
    failure_history: list,
    restored_version: str | None,
) -> None:
    """Write the death certificate. Survives purge_experiments()."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO selfopt_tombstone
                (died_at, reason, final_metrics_json, failure_history_json, restored_version)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                reason,
                json.dumps(final_metrics or {}),
                json.dumps(failure_history or []),
                restored_version,
            ),
        )


def insert_archive(payload: bytes) -> None:
    """Store a gzipped history blob. Forensics are preserved, not deleted."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO selfopt_archive (archived_at, payload) VALUES (?, ?)",
            (time.time(), payload),
        )


def purge_experiments() -> None:
    """Drop active experiment state after archiving. Champions survive as restore targets.

    `selfopt_state` is left intact on purpose: it holds lifecycle flags and
    counters the guardian still needs after a self-destruct, and it no longer
    carries a champion pointer that could outlive the row it names — the
    champion is resolved from `config_versions.status` alone.
    """
    with get_db() as conn:
        conn.execute("DELETE FROM config_versions WHERE status NOT IN ('champion', 'retired')")
        conn.execute("DELETE FROM selfopt_metrics")
        conn.execute("DELETE FROM selfopt_tunable_stats")
        conn.execute("DELETE FROM selfopt_lock")


# --- Repair queue ---

def record_repair(fingerprint: str, endpoint: str | None, traceback: str) -> None:
    """Log an unhandled exception, bumping the count for a repeat fingerprint."""
    now = time.time()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO repair_queue
                (fingerprint, endpoint, traceback, count, first_seen, last_seen, status)
            VALUES (?, ?, ?, 1, ?, ?, 'open')
            ON CONFLICT(fingerprint) DO UPDATE SET
                count = count + 1,
                last_seen = excluded.last_seen,
                traceback = excluded.traceback
            """,
            (fingerprint, endpoint, traceback, now, now),
        )
    record_activity(
        KIND_REPAIR,
        f"captured unhandled {fingerprint} at {endpoint or 'unknown'}",
    )


def list_repairs(status: str | None = None, limit: int = 100) -> list[dict]:
    """Repair queue entries, most recently seen first."""
    sql = "SELECT * FROM repair_queue"
    params: list = []
    if status is not None:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY last_seen DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


# --- Activity audit trail -----------------------------------------------------

# Activity kinds, kept stable so the dashboard can render a badge per kind.
KIND_CYCLE = "cycle"
KIND_PROMOTE = "promote"
KIND_ROLLBACK = "rollback"
KIND_GUARDIAN = "guardian"
KIND_REBUILD = "rebuild"
KIND_REPAIR = "repair"
KIND_ADMIN = "admin"
KIND_TRIGGER = "trigger"
KIND_SYSTEM = "system"


def record_activity(kind: str, detail: str, version: str | None = None) -> None:
    """Append one immutable row to the audit trail. Never raises: telemetry must
    not be able to take down a production action it is describing."""
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO activity_log (at, kind, version, detail) VALUES (?, ?, ?, ?)",
                (time.time(), kind, version, detail),
            )
    except Exception:
        pass


def list_activities(limit: int = 200, kind: str | None = None) -> list[dict]:
    """Newest-first activity feed for the admin dashboard."""
    sql = "SELECT * FROM activity_log"
    params: list = []
    if kind is not None:
        sql += " WHERE kind = ?"
        params.append(kind)
    sql += " ORDER BY at DESC, id DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
