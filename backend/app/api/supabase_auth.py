"""Supabase & Google Authentication endpoint.

Handles Google OAuth session token exchange, retrieves or creates the user in the database,
and returns an application session token.
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.request
from fastapi import APIRouter, HTTPException, status

from ..config import settings
from ..core import user_db
from ..schemas import AuthResponse, SupabaseAuthRequest, UserProfile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/supabase-config")
async def get_supabase_config():
    """Return public Supabase configuration if requested by client."""
    return {
        "supabaseUrl": settings.get_supabase_url,
        "supabaseAnonKey": settings.get_supabase_anon_key,
    }


def _decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload to extract user metadata."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid JWT format")
        payload_b64 = parts[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        decoded_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(decoded_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to decode token payload: {exc}") from exc


@router.post("/supabase", response_model=AuthResponse)
async def supabase_google_auth(req: SupabaseAuthRequest):
    """Authenticate or register a user using Supabase or Google Auth token."""
    email = req.email
    full_name = req.full_name
    token = (req.access_token or req.id_token or "").strip()

    # 1. Try decoding JWT payload to get email & user metadata
    if not email and token:
        try:
            payload = _decode_jwt_payload(token)
            email = payload.get("email") or payload.get("user_metadata", {}).get("email")
            user_meta = payload.get("user_metadata", {})
            full_name = full_name or user_meta.get("full_name") or user_meta.get("name") or payload.get("name")
        except Exception:
            pass

    # 2. Try validating token against Supabase API if configured
    supabase_url = settings.get_supabase_url
    supabase_anon_key = settings.get_supabase_anon_key
    if not email and token and supabase_url and supabase_anon_key:
        try:
            url = f"{supabase_url.rstrip('/')}/auth/v1/user"
            request = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": supabase_anon_key,
                },
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    email = data.get("email")
                    user_meta = data.get("user_metadata", {})
                    full_name = full_name or user_meta.get("full_name") or user_meta.get("name")
        except Exception as err:
            logger.warning("Supabase API token verification failed: %s", err)

    if not email or "@" not in email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not resolve a valid email address for Google authentication",
        )

    full_name = full_name or email.split("@")[0]

    try:
        user = user_db.create_or_get_google_user(email=email, full_name=full_name)
        session_token = user_db.create_session(user["id"])
        return AuthResponse(token=session_token, user=UserProfile(**user))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
