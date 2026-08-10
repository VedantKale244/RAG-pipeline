"""Unit tests for user account signup, login, session validation & logout."""
import uuid
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_user_signup_login_flow():
    unique_id = uuid.uuid4().hex[:8]
    email = f"testuser_{unique_id}@example.com"
    password = "SecurePassword123!"
    full_name = "Jane Doe"

    # 1. Sign Up
    res = client.post(
        "/auth/signup",
        json={"full_name": full_name, "email": email, "password": password},
    )
    assert res.status_code == 201
    data = res.json()
    assert "token" in data
    assert data["token"].startswith("sess_")
    assert data["user"]["email"] == email
    assert data["user"]["full_name"] == full_name

    token = data["token"]

    # 2. Lookup Session Profile (GET /auth/me)
    me_res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == email
    assert me_res.json()["full_name"] == full_name

    # 3. Duplicate Signup Rejection
    dup_res = client.post(
        "/auth/signup",
        json={"full_name": full_name, "email": email, "password": password},
    )
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["detail"].lower()

    # 4. Login with Wrong Password
    bad_login = client.post(
        "/auth/login",
        json={"email": email, "password": "WrongPassword!"},
    )
    assert bad_login.status_code == 401

    # 5. Login with Correct Password
    good_login = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert good_login.status_code == 200
    new_token = good_login.json()["token"]
    assert new_token.startswith("sess_")

    # 6. Logout
    logout_res = client.post("/auth/logout", headers={"Authorization": f"Bearer {new_token}"})
    assert logout_res.status_code == 200

    # 7. Access /auth/me after Logout -> 401
    post_logout = client.get("/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert post_logout.status_code == 401
