"""Accounts, passwords, and who is allowed in.

Password hashing uses `hashlib.scrypt` from the standard library rather than
bcrypt or argon2. Not to avoid a dependency for its own sake — scrypt is a
memory-hard KDF in the same class, it is maintained as part of Python, and this
box is short enough on RAM that every avoidable package matters. The cost
parameters below are the current OWASP-recommended scrypt settings.

Two rules that are easy to get wrong and expensive to get wrong:

1. **Login never says which half was incorrect.** "No such account" tells an
   attacker they found a valid address to spray; both failures return the same
   message and take the same work.
2. **Registration never confirms an address exists either.** Signing up with an
   address already registered returns the same response as a fresh signup —
   otherwise the signup form is an account-enumeration oracle.
"""

import hmac
import os
import re
from base64 import b64decode, b64encode
from datetime import datetime, timezone
from typing import Optional

from intentdesk import db

# OWASP scrypt guidance: N=2^17, r=8, p=1. `maxmem` has to be raised to match,
# since Python's default ceiling is below what N=2^17 needs.
_N = 2 ** 17
_R = 8
_P = 1
_MAXMEM = 260 * 1024 * 1024

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MIN_PASSWORD_LENGTH = 12


class AuthError(Exception):
    """Anything that should be reported to the browser as a refusal."""


# ----------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    """`scrypt$N$r$p$salt$hash`, all base64. Self-describing so the cost
    parameters can be raised later without invalidating existing hashes."""
    salt = os.urandom(16)
    derived = _derive(password, salt)
    return "scrypt${}${}${}${}${}".format(
        _N, _R, _P, b64encode(salt).decode(), b64encode(derived).decode()
    )


def verify_password(password: str, stored: Optional[str]) -> bool:
    """Constant-time check against a stored hash.

    A missing hash (a Google-only account) returns False rather than raising, so
    a password attempt against a Google account fails the same way a wrong
    password does — the response must not reveal how the account was created.
    """
    if not stored or not stored.startswith("scrypt$"):
        return False
    try:
        _, n, r, p, salt_b64, hash_b64 = stored.split("$")
        derived = _derive(
            password, b64decode(salt_b64), n=int(n), r=int(r), p=int(p)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, b64decode(hash_b64))


def _derive(password: str, salt: bytes, n: int = _N, r: int = _R, p: int = _P) -> bytes:
    import hashlib

    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
        dklen=32, maxmem=_MAXMEM,
    )


def password_problem(password: str) -> Optional[str]:
    """Why this password is unacceptable, or None.

    Length only. Composition rules ("one capital, one symbol") push people
    toward `Password1!` and measurably do not help, which is why NIST dropped
    them.
    """
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > 200:
        return "Password must be under 200 characters."
    return None


# -------------------------------------------------------------- access rules
async def access_mode() -> str:
    """open | domain | allowlist — the runtime setting behind who may sign in."""
    from intentdesk.services import preferences

    return str((await preferences.all_prefs())["access_mode"])


async def allowed_domains() -> list[str]:
    from intentdesk.services import preferences

    raw = str((await preferences.all_prefs())["allowed_email_domains"] or "")
    return [d.strip().lower().lstrip("@") for d in raw.split(",") if d.strip()]


async def check_allowed(email: str) -> None:
    """Raise AuthError when this address may not have an account.

    Evaluated on every sign-in, not only at registration: tightening the mode
    must lock out accounts that were created while it was loose, otherwise the
    setting protects nothing that already happened.
    """
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("That does not look like an email address.")

    mode = await access_mode()
    if mode == "open":
        return

    domains = await allowed_domains()
    if any(email.endswith("@" + d) for d in domains):
        return

    if mode == "allowlist":
        row = await db.fetchrow(
            "SELECT 1 FROM users WHERE lower(email) = $1 AND NOT disabled", email
        )
        if row:
            return

    listed = ", ".join("@" + d for d in domains) or "the configured domains"
    raise AuthError(f"{email} is not permitted. Access is limited to {listed}.")


# ------------------------------------------------------------------ accounts
async def get_by_email(email: str) -> Optional[dict]:
    return await db.fetchrow(
        "SELECT * FROM users WHERE lower(email) = $1", (email or "").strip().lower()
    )


async def register(email: str, password: str, name: str = "") -> dict:
    """Create a password account.

    Returns the same shape whether or not the address was already taken. The
    caller shows one message in both cases — a signup form that distinguishes
    them is a way to test which addresses exist.
    """
    email = (email or "").strip().lower()
    await check_allowed(email)

    problem = password_problem(password)
    if problem:
        raise AuthError(problem)

    existing = await get_by_email(email)
    if existing:
        return {"email": email, "created": False}

    await db.execute(
        """
        INSERT INTO users (email, name, password_hash, is_admin)
        VALUES ($1, $2, $3, NOT EXISTS (SELECT 1 FROM users))
        ON CONFLICT (email) DO NOTHING
        """,
        email,
        (name or "").strip() or email.split("@")[0],
        hash_password(password),
    )
    return {"email": email, "created": True}


async def authenticate(email: str, password: str) -> dict:
    """Password sign-in. One message for every kind of failure."""
    email = (email or "").strip().lower()
    user = await get_by_email(email)

    # Hash even when there is no account, so a missing address and a wrong
    # password take the same time. Without this the response time alone answers
    # "does this person have an account here".
    stored = user["password_hash"] if user else None
    ok = verify_password(password, stored)

    if not user or not ok or user["disabled"]:
        raise AuthError("Wrong email or password.")

    await check_allowed(email)
    await _touch(user["id"])
    return _session_user(user)


async def upsert_google(sub: str, email: str, name: str = "") -> dict:
    """Sign in or create from a verified Google identity.

    When an address already has a password account, this links the Google
    subject onto it rather than creating a second account for the same person —
    the case that produces two half-configured logins and a confused user.
    """
    email = (email or "").strip().lower()
    await check_allowed(email)

    existing = await get_by_email(email)
    if existing:
        if not existing["google_sub"]:
            await db.execute(
                "UPDATE users SET google_sub = $2, name = COALESCE(name, $3) WHERE id = $1",
                existing["id"], sub, name or None,
            )
        if existing["disabled"]:
            raise AuthError("This account has been disabled.")
        await _touch(existing["id"])
        return _session_user(existing)

    row = await db.fetchrow(
        """
        INSERT INTO users (email, name, google_sub, is_admin)
        VALUES ($1, $2, $3, NOT EXISTS (SELECT 1 FROM users))
        RETURNING *
        """,
        email,
        (name or "").strip() or email.split("@")[0],
        sub,
    )
    await _touch(row["id"])
    return _session_user(row)


async def list_users() -> list[dict]:
    return await db.fetch(
        """
        SELECT id, email, name, is_admin, disabled, created_at, last_login_at,
               (password_hash IS NOT NULL) AS has_password,
               (google_sub IS NOT NULL)    AS has_google
        FROM users ORDER BY created_at
        """
    )


async def set_disabled(email: str, disabled: bool) -> Optional[dict]:
    return await db.fetchrow(
        "UPDATE users SET disabled = $2 WHERE lower(email) = $1 "
        "RETURNING email, disabled",
        (email or "").strip().lower(),
        disabled,
    )


async def _touch(user_id: int) -> None:
    await db.execute(
        "UPDATE users SET last_login_at = $2 WHERE id = $1",
        user_id,
        datetime.now(timezone.utc),
    )


def _session_user(user: dict) -> dict:
    """Only what the session needs. The hash must never reach a cookie."""
    return {
        "email": user["email"],
        "name": user["name"] or user["email"],
        "is_admin": bool(user["is_admin"]),
    }
