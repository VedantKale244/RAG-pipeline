"""SQLite user account storage & session management layer.

Uses PBKDF2 HMAC SHA-256 password hashing with a per-user random 16-byte salt
to ensure secure credential storage in backend/data/users.db.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path

# DB file location in workspace data directory
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_DB_PATH = _DATA_DIR / "users.db"


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Ensure user accounts, sessions, OTP verifications & chat history tables exist."""
    with _get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at REAL NOT NULL,
                is_email_verified INTEGER DEFAULT 0,
                auth_provider TEXT DEFAULT 'email'
            )
            """
        )
        # Migrations for existing DB schema
        try:
            conn.execute("ALTER TABLE users ADD COLUMN is_email_verified INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN auth_provider TEXT DEFAULT 'email'")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'free'")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN stripe_customer_id TEXT DEFAULT NULL")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT DEFAULT NULL")
        except sqlite3.OperationalError:
            pass

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS otp_verifications (
                email TEXT PRIMARY KEY,
                otp_code TEXT NOT NULL,
                expires_at REAL NOT NULL,
                attempts INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                query TEXT NOT NULL,
                answer TEXT NOT NULL,
                citations_json TEXT NOT NULL,
                edges_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_documents (
                user_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                document_id TEXT NOT NULL,
                uploaded_at REAL NOT NULL,
                PRIMARY KEY (user_id, filename)
            )
            """
        )
        conn.commit()


def record_user_document(user_id: str, filename: str, document_id: str) -> None:
    """Save or update an uploaded document record for a user."""
    if not user_id or not filename:
        return
    with _get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO user_documents (user_id, filename, document_id, uploaded_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, filename, document_id, time.time()),
        )
        conn.commit()


def get_user_documents(user_id: str) -> list[dict]:
    """Retrieve all uploaded documents for a user."""
    if not user_id:
        return []
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT filename, document_id, uploaded_at FROM user_documents WHERE user_id = ? ORDER BY uploaded_at DESC",
            (user_id,),
        ).fetchall()
        return [{"filename": r["filename"], "document_id": r["document_id"], "uploaded_at": r["uploaded_at"]} for r in rows]


def has_user_document(user_id: str, filename: str) -> bool:
    """Check if a user has already uploaded a file with the given filename."""
    if not user_id or not filename:
        return False
    with _get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM user_documents WHERE user_id = ? AND filename = ?",
            (user_id, filename),
        ).fetchone()
        return row is not None



# Initialize schema on module import
init_db()


def _hash_password(password: str, salt_bytes: bytes | None = None) -> tuple[str, str]:
    if salt_bytes is None:
        salt_bytes = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, 100_000)
    return key.hex(), salt_bytes.hex()


def create_user(full_name: str, email: str, password: str) -> dict:
    """Create a new user account. Raises ValueError if email is taken."""
    email_clean = email.strip().lower()
    name_clean = full_name.strip()

    if not name_clean:
        raise ValueError("Full name is required")
    if not email_clean or "@" not in email_clean:
        raise ValueError("Valid email address is required")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters long")

    user_id = f"usr_{secrets.token_hex(8)}"
    password_hash, salt_hex = _hash_password(password)
    now = time.time()

    with _get_db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO users (id, full_name, email, password_hash, salt, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, name_clean, email_clean, password_hash, salt_hex, now),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("An account with this email already exists")

    return {
        "id": user_id,
        "full_name": name_clean,
        "email": email_clean,
        "created_at": now,
        "plan": "free",
    }


def verify_user(email: str, password: str) -> dict | None:
    """Authenticate email & password. Returns user dict or None if invalid."""
    email_clean = email.strip().lower()

    with _get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email_clean,)).fetchone()
        if not row:
            return None

        salt_bytes = bytes.fromhex(row["salt"])
        computed_hash, _ = _hash_password(password, salt_bytes)

        if secrets.compare_digest(computed_hash, row["password_hash"]):
            return {
                "id": row["id"],
                "full_name": row["full_name"],
                "email": row["email"],
                "created_at": row["created_at"],
                "plan": row["plan"] or "free",
            }
    return None


def create_session(user_id: str) -> str:
    """Generate a new session token for a user."""
    token = f"sess_{secrets.token_urlsafe(32)}"
    now = time.time()

    with _get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user_id, now),
        )
        conn.commit()

    return token


def get_session_user(token: str) -> dict | None:
    """Lookup active session token and return user profile."""
    if not token or not token.startswith("sess_"):
        return None

    with _get_db() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.full_name, u.email, u.created_at, u.plan
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()

        if row:
            return {
                "id": row["id"],
                "full_name": row["full_name"],
                "email": row["email"],
                "created_at": row["created_at"],
                "plan": row["plan"] or "free",
            }
    return None


def delete_session(token: str) -> bool:
    """Invalidate a session token."""
    with _get_db() as conn:
        cursor = conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        return cursor.rowcount > 0


def get_user_plan(user_id: str) -> str | None:
    """Return the plan recorded on a user account (None if unknown)."""
    if not user_id or user_id.startswith("guest"):
        return None
    with _get_db() as conn:
        row = conn.execute("SELECT plan FROM users WHERE id = ?", (user_id,)).fetchone()
        return (row["plan"] or "free") if row else None


def set_user_plan(user_id: str, plan: str) -> bool:
    """Record a plan on a user account (webook / admin path). Returns False when the account is unknown."""
    allowed = {"free", "pro", "pro_yearly", "enterprise"}
    if plan not in allowed:
        raise ValueError(f"Unknown plan: {plan}")
    with _get_db() as conn:
        cur = conn.execute(
            "UPDATE users SET plan = ? WHERE id = ?", (plan, user_id)
        )
        conn.commit()
        return cur.rowcount > 0


def set_stripe_account_links(
    user_id: str, customer_id: str, subscription_id: str | None = None
) -> bool:
    """Persist the Stripe customer + subscription ids a user checked out with."""
    with _get_db() as conn:
        cur = conn.execute(
            """
            UPDATE users SET stripe_customer_id = COALESCE(?, stripe_customer_id),
                             stripe_subscription_id = COALESCE(?, stripe_subscription_id)
            WHERE id = ?
            """,
            (customer_id, subscription_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


def user_by_stripe_customer(customer_id: str) -> dict | None:
    """Look up a user by Stripe customer id (a webhook arrives)."""
    if not customer_id:
        return None
    with _get_db() as conn:
        row = conn.execute(
            "SELECT id, plan FROM users WHERE stripe_customer_id = ?", (customer_id,)
        ).fetchone()
        return {"id": row["id"], "plan": row["plan"] or "free"} if row else None


def clear_stripe_subscription(user_id: str, subscription_id: str | None = None) -> bool:
    """Unlink a Stripe subscription from a user (also used on failed payments)."""
    if subscription_id:
        with _get_db() as conn:
            cur = conn.execute(
                """
                UPDATE users
                SET stripe_subscription_id = CASE
                    WHEN stripe_subscription_id = ? THEN NULL
                    ELSE stripe_subscription_id END
                WHERE id = ?
                """,
                (subscription_id, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
    with _get_db() as conn:
        cur = conn.execute(
            "UPDATE users SET stripe_subscription_id = NULL WHERE id = ?", (user_id,)
        )
        conn.commit()
        return cur.rowcount > 0


# Email domains exclusively used by the automated test suite (mocked addresses).
_TEST_EMAIL_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "example.test",
    "test.com",
    "test.dev",
    "test",
    "localhost",
    "localhost.localdomain",
    "fake.com",
}

# Local-part prefixes the tests use to generate accounts (e.g. usera_x, google_user_y).
_TEST_EMAIL_PREFIXES = (
    "testuser_",
    "usera_",
    "userb_",
    "otp_user_",
    "google_user_",
    "hacker_target_",
    "hacker_user_",
    "len_test_",
    "billing_",
    "quota_",
    "dummy_",
    "mock_",
    "fake_",
    "sample_",
    "tester_",
    "dev_",
)


def _is_test_account(email: str | None) -> bool:
    """True for temp/mock accounts created by the automated test suite."""
    if not email:
        return True
    clean = email.strip().lower()
    local, sep, domain = clean.partition("@")
    if not sep:
        return True
    if domain in _TEST_EMAIL_DOMAINS:
        return True
    return local.startswith(_TEST_EMAIL_PREFIXES)


def _test_sql_expr() -> str:
    """SQLite expression matching test/mock accounts (mirrors _is_test_account)."""
    parts = ["LOWER(email) NOT LIKE '%@%'"]
    for d in _TEST_EMAIL_DOMAINS:
        parts.append(f"LOWER(email) LIKE '%@{d}'")
    for p in _TEST_EMAIL_PREFIXES:
        parts.append(f"LOWER(email) LIKE '{p}%@%'")
    return " OR ".join(parts)


def list_users(limit: int = 500, offset: int = 0, include_tests: bool = False) -> list[dict]:
    """Admin listing of real accounts with activity + plan info (newest first).

    Test/mock accounts created by the automated tests are filtered out by default
    so the admin portal only reflects genuine users.
    """
    with _get_db() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.full_name, u.email, COALESCE(u.plan, 'free') AS plan,
                   u.is_email_verified, u.auth_provider, u.created_at,
                   u.stripe_customer_id, u.stripe_subscription_id,
                   (SELECT COUNT(*) FROM chat_conversations c WHERE c.user_id = u.id) AS conversation_count,
                   (SELECT COUNT(*) FROM chat_messages m WHERE m.user_id = u.id) AS message_count,
                   COALESCE((SELECT MAX(m.created_at) FROM chat_messages m WHERE m.user_id = u.id), u.created_at) AS last_active
            FROM users u
            {where}ORDER BY u.created_at DESC
            LIMIT ? OFFSET ?
            """.format(
                where="" if include_tests else "WHERE NOT (" + _test_sql_expr() + ") "
            ),
            (limit, offset),
        ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "full_name": r["full_name"],
                "email": r["email"],
                "plan": r["plan"],
                "is_email_verified": bool(r["is_email_verified"]),
                "auth_provider": r["auth_provider"],
                "created_at": r["created_at"],
                "conversation_count": r["conversation_count"],
                "message_count": r["message_count"],
                "last_active": r["last_active"],
                "stripe_subscription_id": r["stripe_subscription_id"],
            }
        )
    return out


def user_stats(include_tests: bool = False) -> dict:
    """Rolled-up metrics for real accounts (mock/test users excluded by default)."""
    if include_tests:
        rows = list_users(limit=1000000, offset=0, include_tests=True)
        test_clause = ""
    else:
        rows = list_users(limit=1000000, offset=0, include_tests=False)
        test_clause = " AND NOT (" + _test_sql_expr() + ")"
    total = len(rows)
    by_plan: dict[str, int] = {}
    for u in rows:
        by_plan[u["plan"] or "free"] = by_plan.get(u["plan"] or "free", 0) + 1
    verified = sum(1 for u in rows if u["is_email_verified"])
    total_conv = sum(u["conversation_count"] for u in rows)
    total_messages = sum(u["message_count"] for u in rows)

    with _get_db() as conn:
        sessions = conn.execute(f"SELECT COUNT(*) FROM sessions s WHERE EXISTS (SELECT 1 FROM users u WHERE u.id = s.user_id {test_clause})").fetchone()[0]
    return {
        "total_users": int(total),
        "verified_users": int(verified),
        "by_plan": by_plan,
        "total_conversations": int(total_conv),
        "total_messages": int(total_messages),
        "active_sessions": int(sessions),
    }


def resolve_user_id(session_token: str | None) -> str:
    """Resolve a session token or authorization header value to a user_id.

    - Authenticated users: returns permanent user ID (e.g. 'usr_12345678')
    - Guest tokens: returns specific guest token (e.g. 'guest_sess_...')
    - Missing/invalid tokens: returns a unique anonymous guest ID ('guest_sess_anon_...')
      so it never matches shared legacy guest data.
    """
    if not session_token:
        return f"guest_sess_anon_{secrets.token_hex(6)}"

    token = session_token.replace("Bearer ", "").strip()
    if not token:
        return f"guest_sess_anon_{secrets.token_hex(6)}"

    usr = get_session_user(token)
    if usr:
        return usr["id"]

    if token.startswith("guest"):
        return token

    return f"guest_sess_anon_{secrets.token_hex(6)}"


def delete_guest_messages(user_id: str) -> int:
    """Delete all conversations and chat messages for a guest user ID."""
    if not user_id or not user_id.startswith("guest"):
        return 0
    with _get_db() as conn:
        cursor = conn.execute("DELETE FROM chat_conversations WHERE user_id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount



# --- Chat History & Persistence Methods ---

def create_conversation(user_id: str, title: str, conv_id: str | None = None) -> str:
    """Create a new chat conversation thread for a user."""
    conv_id = conv_id or f"conv_{secrets.token_hex(8)}"
    now = time.time()
    clean_title = title.strip()[:100] or "New Conversation"

    with _get_db() as conn:
        conn.execute(
            """
            INSERT INTO chat_conversations (id, user_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conv_id, user_id, clean_title, now, now),
        )
        conn.commit()
    return conv_id


def save_chat_message(
    user_id: str,
    query: str,
    answer: str,
    citations: list,
    edges: list,
    conversation_id: str | None = None,
) -> dict:
    """Save a query & answer pair to a user's conversation thread."""
    import json
    now = time.time()

    with _get_db() as conn:
        if not conversation_id:
            # Generate thread title from query
            title = query.strip()[:40] + ("..." if len(query.strip()) > 40 else "")
            conversation_id = create_conversation(user_id, title)
        else:
            # Touch updated_at
            conn.execute(
                "UPDATE chat_conversations SET updated_at = ? WHERE id = ? AND user_id = ?",
                (now, conversation_id, user_id),
            )

        msg_id = f"msg_{secrets.token_hex(8)}"
        citations_json = json.dumps(citations or [])
        edges_json = json.dumps(edges or [])

        conn.execute(
            """
            INSERT INTO chat_messages (id, conversation_id, user_id, query, answer, citations_json, edges_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (msg_id, conversation_id, user_id, query, answer, citations_json, edges_json, now),
        )
        conn.commit()

    return {
        "msg_id": msg_id,
        "conversation_id": conversation_id,
        "created_at": now,
    }


def list_user_conversations(user_id: str, limit: int = 50) -> list[dict]:
    """Retrieve all chat threads for a user, sorted by most recent."""
    with _get_db() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at, COUNT(m.id) as message_count
            FROM chat_conversations c
            LEFT JOIN chat_messages m ON c.id = m.conversation_id
            WHERE c.user_id = ?
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()

        return [
            {
                "id": r["id"],
                "title": r["title"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "message_count": r["message_count"],
            }
            for r in rows
        ]


def get_conversation_details(conversation_id: str, user_id: str) -> dict | None:
    """Get full thread messages and citations for a conversation."""
    import json
    with _get_db() as conn:
        conv = conn.execute(
            "SELECT * FROM chat_conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()

        if not conv:
            return None

        msgs = conn.execute(
            """
            SELECT id, query, answer, citations_json, edges_json, created_at
            FROM chat_messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        ).fetchall()

        messages = [
            {
                "id": m["id"],
                "query": m["query"],
                "answer": m["answer"],
                "citations": json.loads(m["citations_json"] or "[]"),
                "edges": json.loads(m["edges_json"] or "[]"),
                "created_at": m["created_at"],
            }
            for m in msgs
        ]

        return {
            "id": conv["id"],
            "title": conv["title"],
            "created_at": conv["created_at"],
            "updated_at": conv["updated_at"],
            "messages": messages,
        }


def delete_user_conversation(conversation_id: str, user_id: str) -> bool:
    """Delete a conversation thread."""
    with _get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM chat_conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


# --- OTP & Google Auth Security Methods ---

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_otp_email(email: str, otp_code: str) -> bool:
    """Send OTP verification code to user's email via SMTP. Fallback to server log in dev."""
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASSWORD", "")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user or "noreply@graphrag.internal")

    if not smtp_host or not smtp_user:
        import logging
        logging.getLogger("app").info(f"[DEV SECURITY OTP] Code for {email}: {otp_code}")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Your Security Verification Code: {otp_code} - Neuro-Adaptive GraphRAG"
        msg["From"] = smtp_from
        msg["To"] = email

        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 10px; background-color: #ffffff;">
          <div style="text-align: center; margin-bottom: 20px;">
            <h2 style="color: #163526; margin: 0;">Neuro-Adaptive GraphRAG</h2>
            <p style="color: #6b7280; font-size: 13px; margin-top: 5px;">Secure Email Account Verification</p>
          </div>
          <p style="color: #374151; font-size: 14px;">Your 6-digit one-time verification password (OTP) is:</p>
          <div style="background-color: #f3f4f6; padding: 16px; text-align: center; border-radius: 8px; margin: 20px 0; border: 1px solid #e5e7eb;">
            <span style="font-size: 34px; font-weight: 800; letter-spacing: 8px; color: #163526;">{otp_code}</span>
          </div>
          <p style="color: #6b7280; font-size: 12px; line-height: 1.5;">This OTP code is valid for <strong>10 minutes</strong>. For your security, do not share this code with anyone.</p>
        </div>
        """
        msg.attach(MIMEText(html_content, "html"))

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        return True
    except Exception as exc:
        import logging
        logging.getLogger("app").error(f"Failed to send OTP email to {email}: {exc}")
        return False


def generate_and_store_otp(email: str) -> dict:
    """Generate a secure 6-digit numeric OTP and store in SQLite with 10-minute expiry."""
    email_clean = email.strip().lower()
    if not email_clean or "@" not in email_clean:
        raise ValueError("Valid email address is required")

    otp_code = f"{secrets.randbelow(900000) + 100000}"
    now = time.time()
    expires_at = now + 600  # 10 minutes

    with _get_db() as conn:
        conn.execute(
            """
            INSERT INTO otp_verifications (email, otp_code, expires_at, attempts, created_at)
            VALUES (?, ?, ?, 0, ?)
            ON CONFLICT(email) DO UPDATE SET
                otp_code = excluded.otp_code,
                expires_at = excluded.expires_at,
                attempts = 0,
                created_at = excluded.created_at
            """,
            (email_clean, otp_code, expires_at, now),
        )
        conn.commit()

    sent = send_otp_email(email_clean, otp_code)

    return {
        "email": email_clean,
        "sent": sent,
        "dev_otp": otp_code if not sent else None,
        "expires_in_seconds": 600,
    }


def verify_otp(email: str, code: str) -> bool:
    """Validate 6-digit OTP code against email, enforcing expiry & max attempts."""
    email_clean = email.strip().lower()
    code_clean = code.strip()

    if not code_clean or len(code_clean) != 6:
        raise ValueError("OTP code must be a 6-digit number")

    now = time.time()
    with _get_db() as conn:
        row = conn.execute("SELECT * FROM otp_verifications WHERE email = ?", (email_clean,)).fetchone()
        if not row:
            raise ValueError("No OTP request found for this email. Please request a code.")

        if now > row["expires_at"]:
            conn.execute("DELETE FROM otp_verifications WHERE email = ?", (email_clean,))
            conn.commit()
            raise ValueError("OTP code has expired. Please request a new code.")

        if row["attempts"] >= 5:
            conn.execute("DELETE FROM otp_verifications WHERE email = ?", (email_clean,))
            conn.commit()
            raise ValueError("Too many failed verification attempts. Please request a new code.")

        if secrets.compare_digest(row["otp_code"], code_clean):
            conn.execute("DELETE FROM otp_verifications WHERE email = ?", (email_clean,))
            conn.commit()
            return True
        else:
            conn.execute(
                "UPDATE otp_verifications SET attempts = attempts + 1 WHERE email = ?",
                (email_clean,),
            )
            conn.commit()
            raise ValueError("Invalid OTP code. Please check your code and try again.")


def create_or_get_google_user(email: str, full_name: str) -> dict:
    """Create or retrieve a user account via Google OAuth authentication."""
    email_clean = email.strip().lower()
    name_clean = full_name.strip() or "Google User"

    if not email_clean or "@" not in email_clean:
        raise ValueError("Valid email address is required")

    with _get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email_clean,)).fetchone()
        if row:
            return {
                "id": row["id"],
                "full_name": row["full_name"],
                "email": row["email"],
                "created_at": row["created_at"],
                "plan": row["plan"] or "free",
            }

        user_id = f"usr_{secrets.token_hex(8)}"
        random_pass = secrets.token_urlsafe(16)
        password_hash, salt_hex = _hash_password(random_pass)
        now = time.time()

        conn.execute(
            """
            INSERT INTO users (id, full_name, email, password_hash, salt, created_at, is_email_verified, auth_provider)
            VALUES (?, ?, ?, ?, ?, ?, 1, 'google')
            """,
            (user_id, name_clean, email_clean, password_hash, salt_hex, now),
        )
        conn.commit()

        return {
            "id": user_id,
            "full_name": name_clean,
            "email": email_clean,
            "created_at": now,
            "plan": "free",
        }

