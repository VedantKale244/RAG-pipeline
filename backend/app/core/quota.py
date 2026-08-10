"""Usage quotas & plan gating.

Free access is metered:

* **Trial (guest sessions)** — ``TRIAL_QUESTIONS`` total questions, then the user
  is asked to sign in or upgrade. There is no time window.
* **Free signed-in plan** — ``FREE_DAILY_UPLOADS`` distinct documents per day and
  ``FREE_QUESTIONS_PER_DOC_PER_DAY`` questions per document per day. Per-document
  attribution means a question that draws on several PDFs consumes one of each
  document's daily allowance.
* **Paid plans** (``pro`` / ``enterprise``) — unlimited ingestion & questions.

Counters live in SQLite (``data/quota.db``, WAL) so they survive restarts. The
plan itself is stored on the ``users`` row (see :mod:`app.core.user_db`).
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_DB_PATH = _DATA_DIR / "quota.db"

TRIAL_QUESTIONS = 3
FREE_DAILY_UPLOADS = 3
FREE_QUESTIONS_PER_DOC_PER_DAY = 5

UNLIMITED_PLANS = {"pro", "pro_yearly", "enterprise"}


class QuotaExceeded(Exception):
    """Raised when a request would push the account past its current plan."""

    def __init__(self, message: str, code: int = 429):
        super().__init__(message)
        self.message = message
        self.code = code


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init() -> None:
    with _get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quota_uploads (
                user_id TEXT NOT NULL,
                day TEXT NOT NULL,
                document_id TEXT NOT NULL,
                PRIMARY KEY (user_id, day, document_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quota_doc_questions (
                user_id TEXT NOT NULL,
                day TEXT NOT NULL,
                document_id TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, day, document_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quota_guest_questions (
                user_id TEXT PRIMARY KEY,
                count INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.commit()


_init()


# ---------------------------------------------------------------------------
# Plan helpers
# ---------------------------------------------------------------------------

def is_trial(user_id: str) -> bool:
    """A session is a trial when it isn't backed by a signed-in user account."""
    return bool(user_id.startswith("guest"))


def get_plan(user_id: str) -> str:
    """Resolve the account plan for a user id. Guests always report 'trial'."""
    if not user_id or user_id.startswith("guest"):
        return "trial"
    from . import user_db

    plan = user_db.get_user_plan(user_id)
    return plan or "free"


def is_unlimited(user_id: str) -> bool:
    return get_plan(user_id) in UNLIMITED_PLANS


# ---------------------------------------------------------------------------
# Upload accounting
# ---------------------------------------------------------------------------

def uploads_used_today(user_id: str, day: str | None = None) -> int:
    day = day or _today()
    with _get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(DISTINCT document_id) AS n FROM quota_uploads WHERE user_id = ? AND day = ?",
            (user_id, day),
        ).fetchone()
        return int(row["n"]) if row else 0


def can_upload_day(user_id: str) -> bool:
    """A distinct-documents-per-day cap for *signed-in free* users only."""
    if get_plan(user_id) in UNLIMITED_PLANS or user_id.startswith("guest"):
        return True
    return uploads_used_today(user_id) < FREE_DAILY_UPLOADS


def record_upload(user_id: str, document_id: str, day: str | None = None) -> None:
    if not document_id:
        return
    day = day or _today()
    with _get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO quota_uploads (user_id, day, document_id) VALUES (?, ?, ?)",
            (user_id, day, document_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Question gates
# ---------------------------------------------------------------------------

def _doc_question_counts(user_id: str, day: str | None = None) -> dict[str, int]:
    day = day or _today()
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT document_id, count FROM quota_doc_questions WHERE user_id = ? AND day = ?",
            (user_id, day),
        ).fetchall()
        return {r["document_id"]: int(r["count"]) for r in rows}


def doc_question_remaining(user_id: str, document_id: str) -> int:
    if not document_id:
        return FREE_QUESTIONS_PER_DOC_PER_DAY
    if get_plan(user_id) in UNLIMITED_PLANS:
        return -1  # unlimited
    used = _doc_question_counts(user_id).get(document_id, 0)
    return max(0, FREE_QUESTIONS_PER_DOC_PER_DAY - used)


def guest_trial_remaining(user_id: str) -> int:
    with _get_db() as conn:
        row = conn.execute(
            "SELECT count FROM quota_guest_questions WHERE user_id = ?", (user_id,)
        ).fetchone()
        used = int(row["count"]) if row else 0
    return max(0, TRIAL_QUESTIONS - used)


def take_guest_question(user_id: str) -> int:
    """Allow one trial question, recording it held for a guest. Returns remaining."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT count FROM quota_guest_questions WHERE user_id = ?", (user_id,)
        ).fetchone()
        used = int(row["count"]) if row else 0
        remaining = TRIAL_QUESTIONS - used
        if remaining <= 0:
            raise QuotaExceeded(
                "You've used all your free trial questions. Sign in for a free "
                "account with daily limits or upgrade to Pro for unlimited access."
            )
        conn.execute(
            "INSERT INTO quota_guest_questions (user_id, count, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET count = excluded.count, updated_at = ?",
            (user_id, used + 1, time.time(), time.time()),
        )
        conn.commit()


def check_docs_quota(user_id: str, document_ids: list[str]) -> None:
    """Free plan: raise QuotaExceeded if any touched document hit its daily cap."""
    if not document_ids:
        return
    if get_plan(user_id) in UNLIMITED_PLANS:
        return
    counts = _doc_question_counts(user_id)
    for doc_id in set(document_ids):
        if not doc_id:
            continue
        if counts.get(doc_id, 0) >= FREE_QUESTIONS_PER_DOC_PER_DAY:
            raise QuotaExceeded(
                f"Daily question limit reached for one of the documents this question "
                f"uses (5 questions per document per day). Upgrade to Pro for unlimited questions."
            )


def record_docs_questions(user_id: str, document_ids: list[str]) -> None:
    """Increment each document's daily question count (only for free-plan users)."""
    if not document_ids:
        return
    if get_plan(user_id) in UNLIMITED_PLANS:
        return
    day = _today()
    with _get_db() as conn:
        for doc_id in set(document_ids):
            if not doc_id:
                continue
            conn.execute(
                "INSERT INTO quota_doc_questions (user_id, day, document_id, count) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(user_id, day, document_id) DO UPDATE SET count = count + 1",
                (user_id, day, doc_id),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# usage snapshot for the UI
# ---------------------------------------------------------------------------

def usage_snapshot(user_id: str) -> dict:
    """Return the caller's plan + today's counters for the UI HUD."""
    plan = get_plan(user_id)
    is_guest = user_id.startswith("guest")
    out: dict = {
        "plan": plan,
        "completed_plan": "trial" if is_guest else plan,
        "is_guest": is_guest,
        "unlimited": plan in UNLIMITED_PLANS,
        "trial": {
            "questions_limit": TRIAL_QUESTIONS if is_guest else 0,
            "questions_remaining": guest_trial_remaining(user_id) if is_guest else 0,
        },
        "daily": {
            "uploads_limit": 0 if (is_guest or plan in UNLIMITED_PLANS) else FREE_DAILY_UPLOADS,
            "uploads_used_today": uploads_used_today(user_id) if not is_guest else 0,
            "questions_per_doc_limit": FREE_QUESTIONS_PER_DOC_PER_DAY if plan == "free" else 0,
        },
    }
    return out