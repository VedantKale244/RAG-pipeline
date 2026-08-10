"""Authentication API router: Sign Up, Sign In, Profile, Logout."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from ..config import settings
from ..core import user_db
from ..schemas import (
    AuthResponse,
    GoogleAuthRequest,
    LoginRequest,
    SendOtpRequest,
    SignUpRequest,
    UserProfile,
    VerifyOtpSignUpRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _extract_token(authorization: str | None, x_session_token: str | None) -> str | None:
    if x_session_token and x_session_token.startswith("sess_"):
        return x_session_token
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:].strip()
    return None


@router.post("/send-otp")
async def send_otp(req: SendOtpRequest):
    """Generate and dispatch a 6-digit OTP verification code to user email."""
    try:
        res = user_db.generate_and_store_otp(req.email)
        msg = "Verification OTP code sent to your email address." if res["sent"] else f"Dev OTP code generated for {res['email']}."
        show_dev_otp = res.get("dev_otp") if settings.is_dev else None
        return {
            "status": "ok",
            "message": msg,
            "sent": res["sent"],
            "dev_otp": show_dev_otp,
        }
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/verify-otp-signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def verify_otp_signup(req: VerifyOtpSignUpRequest):
    """Verify 6-digit OTP code and complete user registration."""
    try:
        user_db.verify_otp(req.email, req.otp)
        user = user_db.create_user(
            full_name=req.full_name,
            email=req.email,
            password=req.password,
        )
        token = user_db.create_session(user["id"])
        return AuthResponse(token=token, user=UserProfile(**user))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/google", response_model=AuthResponse)
async def google_auth(req: GoogleAuthRequest):
    """Authenticate or register user via Google OAuth."""
    try:
        user = user_db.create_or_get_google_user(email=req.email, full_name=req.full_name)
        token = user_db.create_session(user["id"])
        return AuthResponse(token=token, user=UserProfile(**user))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(req: SignUpRequest):
    try:
        user = user_db.create_user(
            full_name=req.full_name,
            email=req.email,
            password=req.password,
        )
        token = user_db.create_session(user["id"])
        return AuthResponse(token=token, user=UserProfile(**user))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest):
    user = user_db.verify_user(email=req.email, password=req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email address or password",
        )
    token = user_db.create_session(user["id"])
    return AuthResponse(token=token, user=UserProfile(**user))


@router.get("/me", response_model=UserProfile)
async def me(
    authorization: str | None = Header(default=None),
    x_session_token: str | None = Header(default=None),
):
    token = _extract_token(authorization, x_session_token)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication session token",
        )
    user = user_db.get_session_user(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token invalid or expired",
        )
    return UserProfile(**user)


@router.post("/logout")
async def logout(
    authorization: str | None = Header(default=None),
    x_session_token: str | None = Header(default=None),
):
    token = _extract_token(authorization, x_session_token)
    if token:
        user_db.delete_session(token)
    return {"status": "ok", "message": "Successfully logged out"}


@router.post("/guest/cleanup")
async def guest_cleanup(
    authorization: str | None = Header(default=None),
    x_session_token: str | None = Header(default=None),
):
    """Purge temporary vector embeddings and graph nodes for a guest session."""
    raw_token = x_session_token or (authorization.replace("Bearer ", "").strip() if authorization else "")
    if not raw_token or not raw_token.startswith("guest"):
        return {"status": "skipped", "reason": "Not a guest token"}

    user_id = raw_token
    from ..core import vectorstore, graphrag
    from starlette.concurrency import run_in_threadpool

    vec_del = await run_in_threadpool(vectorstore.delete_by_user, user_id)
    graph_stats = await run_in_threadpool(graphrag.delete_by_user, user_id)
    user_db.delete_guest_messages(user_id)

    return {
        "status": "cleaned",
        "user_id": user_id,
        "vectors_deleted": vec_del,
        "graph_stats": graph_stats,
    }

