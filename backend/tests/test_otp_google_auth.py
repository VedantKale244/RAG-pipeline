"""Unit tests for OTP generation, OTP verification signup flow, and Google OAuth authentication."""
import uuid
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core import user_db

client = TestClient(app)


def test_send_and_verify_otp_flow():
    unique_id = uuid.uuid4().hex[:8]
    email = f"otp_user_{unique_id}@example.com"
    full_name = "OTP Test User"
    password = "SecurePassword123!"

    # 1. Send OTP
    send_res = client.post("/auth/send-otp", json={"email": email})
    assert send_res.status_code == 200
    data = send_res.json()
    assert data["status"] == "ok"
    assert "dev_otp" in data or data["sent"] is True

    otp_code = data.get("dev_otp")
    if not otp_code:
        # Fallback to DB lookup if dev_otp not returned directly
        with user_db._get_db() as conn:
            row = conn.execute("SELECT otp_code FROM otp_verifications WHERE email = ?", (email,)).fetchone()
            otp_code = row["otp_code"]

    assert len(otp_code) == 6

    # 2. Verify with wrong OTP -> 400
    bad_verify = client.post(
        "/auth/verify-otp-signup",
        json={
            "full_name": full_name,
            "email": email,
            "password": password,
            "otp": "000000" if otp_code != "000000" else "111111",
        },
    )
    assert bad_verify.status_code == 400
    assert "invalid" in bad_verify.json()["detail"].lower()

    # 3. Verify with correct OTP -> 201 Created & Logged in
    good_verify = client.post(
        "/auth/verify-otp-signup",
        json={
            "full_name": full_name,
            "email": email,
            "password": password,
            "otp": otp_code,
        },
    )
    assert good_verify.status_code == 201
    verify_data = good_verify.json()
    assert "token" in verify_data
    assert verify_data["token"].startswith("sess_")
    assert verify_data["user"]["email"] == email
    assert verify_data["user"]["full_name"] == full_name

    # 4. Verify OTP is single-use (subsequent use fails)
    reuse_verify = client.post(
        "/auth/verify-otp-signup",
        json={
            "full_name": full_name,
            "email": f"new_{email}",
            "password": password,
            "otp": otp_code,
        },
    )
    assert reuse_verify.status_code == 400


def test_google_auth_flow():
    unique_id = uuid.uuid4().hex[:8]
    email = f"google_user_{unique_id}@gmail.com"
    full_name = "Google Verified"

    # 1. First Google Auth -> Account Auto-created
    res = client.post("/auth/google", json={"email": email, "full_name": full_name})
    assert res.status_code == 200
    data = res.json()
    assert "token" in data
    assert data["token"].startswith("sess_")
    assert data["user"]["email"] == email
    assert data["user"]["full_name"] == full_name

    token = data["token"]

    # 2. Lookup Session Profile
    me_res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == email

    # 3. Second Google Auth -> Existing Account Retrieved
    res2 = client.post("/auth/google", json={"email": email, "full_name": full_name})
    assert res2.status_code == 200
    assert res2.json()["user"]["email"] == email
