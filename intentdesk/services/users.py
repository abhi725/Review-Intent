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

import hashlib
import hmac
import os
import re
import secrets
from base64 import b64decode, b64encode
from datetime import datetime, timedelta, timezone
from typing import Optional

from intentdesk import db
from intentdesk.config import settings

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


class UnverifiedError(AuthError):
    """Right password, unconfirmed address. Separate from AuthError so the login
    route can offer a resend button instead of a flat refusal."""

    def __init__(self, email: str):
        super().__init__(f"Confirm your email first — we sent a link to {email}.")
        self.email = email


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

    # The first account is both admin and pre-verified, for the same reason:
    # a fresh deploy must not be able to lock itself out of its own settings.
    # If mail is misconfigured, an unverifiable first admin bricks the install.
    await db.execute(
        """
        INSERT INTO users (email, name, password_hash, is_admin, email_verified_at)
        VALUES ($1, $2, $3,
                NOT EXISTS (SELECT 1 FROM users),
                CASE WHEN NOT EXISTS (SELECT 1 FROM users) THEN now() END)
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

    # Only reachable once the password was correct, so naming the state here
    # tells an attacker nothing they did not already have. Refusing to explain
    # it, on the other hand, leaves a legitimate user with no way to find out
    # why a password they know is right does not work.
    if user["email_verified_at"] is None:
        raise UnverifiedError(email)

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
        # Google has proved the address. Someone who registered with a password,
        # never confirmed, and then signed in with Google on the same address
        # has demonstrated exactly what our own email was asking for.
        if existing["email_verified_at"] is None:
            await mark_verified(existing["id"])
            existing = await get_by_email(email)
        await _touch(existing["id"])
        return _session_user(existing)

    row = await db.fetchrow(
        """
        INSERT INTO users (email, name, google_sub, is_admin, email_verified_at)
        VALUES ($1, $2, $3, NOT EXISTS (SELECT 1 FROM users), now())
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
               email_verified_at, job_title, phone,
               (password_hash IS NOT NULL)    AS has_password,
               (google_sub IS NOT NULL)       AS has_google,
               (avatar IS NOT NULL)           AS has_avatar
        FROM users ORDER BY created_at
        """
    )


# -------------------------------------------------------------------- tokens
# One table, two purposes. Verification proves an address is yours; reset lets
# you take the account back. Both are "a secret in an inbox, good once".
VERIFY_TTL = timedelta(hours=24)
# Deliberately shorter. A live verification link is an inconvenience if it
# leaks; a live reset link is an account takeover.
RESET_TTL = timedelta(hours=1)

RESEND_LIMIT = 3
RESEND_WINDOW = timedelta(hours=1)


def _hash_token(token: str) -> str:
    """sha256, not scrypt. These are 256 bits of `secrets` output, not a human
    password — there is no dictionary to slow an attacker down against, and a
    memory-hard hash on every link click would just be a DoS surface."""
    return hashlib.sha256(token.encode()).hexdigest()


async def create_token(user_id: int, purpose: str, issued_by: Optional[str] = None) -> str:
    """Mint a single-use link token and return it in the clear, once.

    Issuing invalidates every unused token of the same purpose for that user, so
    an older link forwarded out of a mailbox is already dead.
    """
    if purpose not in ("verify", "reset"):
        raise ValueError(f"unknown token purpose {purpose!r}")

    token = secrets.token_urlsafe(32)
    ttl = VERIFY_TTL if purpose == "verify" else RESET_TTL

    async with db.transaction() as conn:
        await conn.execute(
            "UPDATE auth_tokens SET used_at = now() "
            "WHERE user_id = $1 AND purpose = $2 AND used_at IS NULL",
            user_id, purpose,
        )
        await conn.execute(
            "INSERT INTO auth_tokens (user_id, purpose, token_hash, expires_at, issued_by) "
            "VALUES ($1, $2, $3, $4, $5)",
            user_id, purpose, _hash_token(token),
            datetime.now(timezone.utc) + ttl, issued_by,
        )
    return token


async def consume_token(token: str, purpose: str) -> dict:
    """Redeem a token, returning the account it belongs to.

    Unknown, expired, already-used and belongs-to-a-disabled-account all raise
    the same message. Distinguishing them tells whoever is holding a stale link
    more about our accounts than they need to know.
    """
    dead = AuthError("This link is no longer valid. Request a new one.")
    if not token:
        raise dead

    async with db.transaction() as conn:
        row = await conn.fetchrow(
            """
            SELECT t.id, t.user_id, t.expires_at, t.used_at, u.email, u.disabled
            FROM auth_tokens t JOIN users u ON u.id = t.user_id
            WHERE t.token_hash = $1 AND t.purpose = $2
            FOR UPDATE OF t
            """,
            _hash_token(token), purpose,
        )
        if not row or row["used_at"] or row["disabled"]:
            raise dead
        if row["expires_at"] <= datetime.now(timezone.utc):
            raise dead

        # Stamped inside the same transaction as the lookup, so two clicks on
        # the same link cannot both succeed.
        await conn.execute("UPDATE auth_tokens SET used_at = now() WHERE id = $1", row["id"])

    return {"user_id": row["user_id"], "email": row["email"]}


async def recent_token_count(user_id: int, purpose: str) -> int:
    row = await db.fetchrow(
        "SELECT count(*) AS n FROM auth_tokens "
        "WHERE user_id = $1 AND purpose = $2 AND created_at >= $3",
        user_id, purpose, datetime.now(timezone.utc) - RESEND_WINDOW,
    )
    return int(row["n"]) if row else 0


def link_for(purpose: str, token: str) -> str:
    path = "/verify" if purpose == "verify" else "/reset"
    return f"{settings.public_base_url.rstrip('/')}{path}?token={token}"


# ------------------------------------------------------------- verification
async def mark_verified(user_id: int) -> None:
    await db.execute(
        "UPDATE users SET email_verified_at = COALESCE(email_verified_at, now()) WHERE id = $1",
        user_id,
    )


async def send_verification(email: str, force: bool = False) -> bool:
    """Email a confirmation link. Silent no-op for an unknown or already-verified
    address — the caller shows the same message either way, so a signup form
    cannot be used to test which addresses are registered.

    `force=False` applies the per-hour resend cap. The admin path passes True.
    """
    from intentdesk.services import email as mailer

    user = await get_by_email(email)
    if not user or user["disabled"] or user["email_verified_at"] is not None:
        return False
    if not force and await recent_token_count(user["id"], "verify") >= RESEND_LIMIT:
        return False

    token = await create_token(user["id"], "verify")
    subject, html = mailer.verify_email(link_for("verify", token))
    return await mailer.send(
        to=user["email"], name=user["name"] or "", subject=subject, html=html,
        template_id=settings.mautic_tpl_verify,
        fields={"action_url": link_for("verify", token)},
    )


async def send_reset(email: str) -> bool:
    """Email a reset link. Same silence rule as send_verification."""
    from intentdesk.services import email as mailer

    user = await get_by_email(email)
    if not user or user["disabled"]:
        return False
    if await recent_token_count(user["id"], "reset") >= RESEND_LIMIT:
        return False

    token = await create_token(user["id"], "reset")
    subject, html = mailer.reset_email(link_for("reset", token))
    return await mailer.send(
        to=user["email"], name=user["name"] or "", subject=subject, html=html,
        template_id=settings.mautic_tpl_reset,
        fields={"action_url": link_for("reset", token)},
    )


async def send_existing_account_notice(email: str) -> bool:
    """Tell an address that it already has an account, and how to get into it.

    The signup form shows "check your email" whether or not the address was
    taken, because a form that distinguishes them can be used to test which
    addresses are registered. That silence used to end the story: a duplicate
    signup sent nothing at all, so the one person entitled to an answer — the
    owner of the address — waited for a link that did not exist.

    Carries a reset token so the mail is actionable, which also covers the case
    that produces most duplicate signups: a Google-only account whose owner is
    trying to give themselves a password. Same rate cap as `/forgot`, and the
    same token, so this opens no door that `/forgot` did not already open.
    """
    from intentdesk.services import email as mailer

    user = await get_by_email(email)
    if not user or user["disabled"]:
        return False
    if await recent_token_count(user["id"], "reset") >= RESEND_LIMIT:
        return False

    token = await create_token(user["id"], "reset")
    subject, html = mailer.existing_account_email(
        link_for("reset", token),
        has_password=user["password_hash"] is not None,
        has_google=user["google_sub"] is not None,
    )
    return await mailer.send(
        to=user["email"], name=user["name"] or "", subject=subject, html=html,
        template_id=settings.mautic_tpl_reset,
        fields={"action_url": link_for("reset", token)},
    )


async def admin_reset_link(email: str, issued_by: str) -> dict:
    """A reset URL handed to an admin to deliver by hand.

    The path that works when mail does not — which, given how quietly SMTP and
    API credentials rot, is worth keeping even once email is healthy.
    """
    user = await get_by_email(email)
    if not user:
        raise AuthError("No account with that address.")
    token = await create_token(user["id"], "reset", issued_by=issued_by)
    return {
        "email": user["email"],
        "url": link_for("reset", token),
        "expires_at": datetime.now(timezone.utc) + RESET_TTL,
    }


# ------------------------------------------------------------------ profile
async def set_password(user_id: int, new_password: str) -> None:
    problem = password_problem(new_password)
    if problem:
        raise AuthError(problem)
    await db.execute(
        "UPDATE users SET password_hash = $2 WHERE id = $1",
        user_id, hash_password(new_password),
    )


async def change_own_password(email: str, current: str, new_password: str) -> None:
    """A signed-in password change. Requires the current password.

    A reset link is for someone locked out; this is for someone already inside.
    Without the current-password check, a borrowed session — an unlocked laptop,
    a stolen cookie — becomes permanent ownership of the account.
    """
    user = await get_by_email(email)
    if not user:
        raise AuthError("Wrong email or password.")
    if user["password_hash"] and not verify_password(current, user["password_hash"]):
        raise AuthError("That is not your current password.")
    await set_password(user["id"], new_password)


async def get_profile(email: str) -> Optional[dict]:
    return await db.fetchrow(
        """
        SELECT id, email, name, is_admin, job_title, phone,
               email_verified_at, created_at, last_login_at,
               (avatar IS NOT NULL) AS has_avatar,
               avatar_updated_at,
               (password_hash IS NOT NULL) AS has_password,
               (google_sub IS NOT NULL)    AS has_google
        FROM users WHERE lower(email) = $1
        """,
        (email or "").strip().lower(),
    )


async def update_profile(
    email: str,
    name: Optional[str] = None,
    job_title: Optional[str] = None,
    phone: Optional[str] = None,
) -> Optional[dict]:
    """COALESCE so an omitted field keeps its value — a PATCH that sends only
    `phone` must not blank out someone's name."""
    await db.execute(
        """
        UPDATE users SET name = COALESCE($2, name),
                         job_title = COALESCE($3, job_title),
                         phone = COALESCE($4, phone)
        WHERE lower(email) = $1
        """,
        (email or "").strip().lower(),
        (name or "").strip() or None,
        job_title.strip() if job_title is not None else None,
        phone.strip() if phone is not None else None,
    )
    return await get_profile(email)


async def set_avatar(email: str, png: bytes) -> None:
    await db.execute(
        "UPDATE users SET avatar = $2, avatar_mime = 'image/png', "
        "avatar_updated_at = now() WHERE lower(email) = $1",
        (email or "").strip().lower(), png,
    )


async def clear_avatar(email: str) -> None:
    await db.execute(
        "UPDATE users SET avatar = NULL, avatar_mime = NULL, "
        "avatar_updated_at = now() WHERE lower(email) = $1",
        (email or "").strip().lower(),
    )


async def get_avatar(email: str) -> Optional[dict]:
    return await db.fetchrow(
        "SELECT avatar, avatar_mime, avatar_updated_at FROM users "
        "WHERE lower(email) = $1 AND avatar IS NOT NULL",
        (email or "").strip().lower(),
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
