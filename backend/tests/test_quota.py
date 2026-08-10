"""Unit tests for the usage quota & plan-gating engine (app.core.quota)."""
from __future__ import annotations

import pytest

from app.core.quota import (
    FREE_DAILY_UPLOADS,
    FREE_QUESTIONS_PER_DOC_PER_DAY,
    TRIAL_QUESTIONS,
    QuotaExceeded,
    can_upload_day,
    check_docs_quota,
    doc_question_remaining,
    get_plan,
    guest_trial_remaining,
    is_unlimited,
    record_docs_questions,
    record_upload,
    take_guest_question,
    uploads_used_today,
    usage_snapshot,
)


@pytest.fixture
def guest_id() -> str:
    return "guest_quota_test_1"


@pytest.fixture
def free_id() -> str:
    from app.core import user_db
    _id = "usr_quota_test_1"
    return _id


@pytest.fixture(autouse=True)
def clean_quota(free_id, guest_id):
    import sqlite3
    from app.core.quota import _DB_PATH
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("DELETE FROM quota_uploads WHERE user_id IN (?, ?)", (free_id, guest_id))
    conn.execute("DELETE FROM quota_doc_questions WHERE user_id IN (?, ?)", (free_id, guest_id))
    conn.execute("DELETE FROM quota_guest_questions WHERE user_id IN (?, ?)", (free_id, guest_id))
    conn.commit()
    conn.close()
    yield
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("DELETE FROM quota_uploads WHERE user_id IN (?, ?)", (free_id, guest_id))
    conn.execute("DELETE FROM quota_doc_questions WHERE user_id IN (?, ?)", (free_id, guest_id))
    conn.execute("DELETE FROM quota_guest_questions WHERE user_id IN (?, ?)", (free_id, guest_id))
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _free_plan(free_id, monkeypatch):
    from app.core import user_db
    monkeypatch.setattr(user_db, "get_user_plan", lambda uid: None if uid.startswith("guest") else "free")
    yield


class TestGuestTrial:
    def test_guest_is_trial(self, guest_id):
        assert get_plan(guest_id) == "trial"
        assert not is_unlimited(guest_id)

    def test_fresh_guest_full_budget(self, guest_id):
        assert guest_trial_remaining(guest_id) == TRIAL_QUESTIONS

    def test_consume_and_exhaust(self, guest_id):
        for _ in range(TRIAL_QUESTIONS):
            take_guest_question(guest_id)
        assert guest_trial_remaining(guest_id) == 0
        with pytest.raises(QuotaExceeded):
            take_guest_question(guest_id)

    def test_guests_never_blocked_on_uploads(self, guest_id):
        assert can_upload_day(guest_id) is True


class TestFreePlanUploads:
    def test_free_account_starts_under_cap(self, free_id):
        assert can_upload_day(free_id) is True

    def test_cap_hit_after_daily_limit(self, free_id):
        for i in range(FREE_DAILY_UPLOADS):
            record_upload(free_id, f"doc-{i}")
        assert uploads_used_today(free_id) == FREE_DAILY_UPLOADS
        assert can_upload_day(free_id) is False

    def test_re_upload_same_doc_free(self, free_id):
        record_upload(free_id, "same-doc")
        record_upload(free_id, "same-doc")
        assert uploads_used_today(free_id) == 1


class TestPerDocQuestionQuota:
    def test_per_doc_counting(self, free_id):
        record_docs_questions(free_id, ["doc-a", "doc-b"])
        assert doc_question_remaining(free_id, "doc-a") == FREE_QUESTIONS_PER_DOC_PER_DAY - 1
        assert doc_question_remaining(free_id, "doc-b") == FREE_QUESTIONS_PER_DOC_PER_DAY - 1
        assert doc_question_remaining(free_id, "untouched") == FREE_QUESTIONS_PER_DOC_PER_DAY

    def test_check_raises_at_cap(self, free_id):
        for _ in range(FREE_QUESTIONS_PER_DOC_PER_DAY):
            record_docs_questions(free_id, ["doc-a"])
        with pytest.raises(QuotaExceeded):
            check_docs_quota(free_id, ["doc-a"])

    def test_check_passes_under_cap(self, free_id):
        record_docs_questions(free_id, ["doc-a"] * (FREE_QUESTIONS_PER_DOC_PER_DAY - 1))
        check_docs_quota(free_id, ["doc-a"])  # no raise

    def test_empty_doc_list_passes(self, free_id):
        check_docs_quota(free_id, [])

    def test_guest_perdoc_never_enforced(self, guest_id):
        check_docs_quota(guest_id, ["never-touched"])


class TestUnlimited:
    def test_pro_unlimited(self, free_id, monkeypatch):
        from app.core import user_db
        monkeypatch.setattr(user_db, "get_user_plan", lambda _: "pro")
        assert is_unlimited(free_id) is True
        assert can_upload_day(free_id) is True
        record_docs_questions(free_id, ["doc-pro"])
        assert doc_question_remaining(free_id, "doc-pro") == -1


class TestUsageSnapshot:
    def test_guest_snapshot(self, guest_id):
        snap = usage_snapshot(guest_id)
        assert snap["plan"] == "trial"
        assert snap["trial"]["questions_remaining"] == TRIAL_QUESTIONS
        assert snap["daily"]["uploads_used_today"] == 0

    def test_free_snapshot(self, free_id):
        snap = usage_snapshot(free_id)
        assert snap["plan"] == "free"
        assert snap["unlimited"] is False
        assert snap["daily"]["questions_per_doc_limit"] == FREE_QUESTIONS_PER_DOC_PER_DAY