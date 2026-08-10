"""Tests for guest session cleanup and strict user data isolation."""
import pytest
from app.core import user_db, vectorstore, graphrag

def test_resolve_user_id():
    # Null token yields anonymous guest token
    anon1 = user_db.resolve_user_id(None)
    assert anon1.startswith("guest_sess_anon_")

    # Specific guest token is preserved
    guest_tok = "guest_sess_abc123"
    resolved_guest = user_db.resolve_user_id(guest_tok)
    assert resolved_guest == guest_tok

    # Bearer header format is handled
    resolved_bearer = user_db.resolve_user_id("Bearer guest_sess_xyz789")
    assert resolved_bearer == "guest_sess_xyz789"

def test_guest_message_deletion():
    # Non-guest user ID should not trigger deletion
    deleted_user = user_db.delete_guest_messages("usr_test123")
    assert deleted_user == 0

    # Guest user ID runs cleanly
    deleted_guest = user_db.delete_guest_messages("guest_sess_test123")
    assert isinstance(deleted_guest, int)
