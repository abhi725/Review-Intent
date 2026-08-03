"""Outbound transactional mail: Mautic first, Resend if Mautic will not.

Mautic is the intended channel — the templates are editable by someone who is
not a programmer, and every send lands on the contact's timeline. Resend is the
floor underneath it.

That fallback is not defensive over-engineering. The same arrangement in
`/opt/swanai/voice_server.py` has been quietly serving every email through
Resend because Mautic's API started returning 401 and nothing surfaced it: mail
kept arriving, so the breakage was invisible. Two lessons are built in here —
the fallback exists, and when it fires it is logged at WARNING with the reason,
so "Mautic is down" is a thing you can find in the logs rather than a thing you
discover months later.

Nothing in this module raises. A signup must not fail because mail is down; the
caller gets `False` and decides what to tell the user.
"""

import logging
from typing import Optional

import httpx

from intentdesk.config import settings

log = logging.getLogger(__name__)

TIMEOUT = 10.0


def configured() -> bool:
    """Whether any channel could send. False means links must be handed over
    out of band — which is what the admin-issued reset link is for."""
    return bool((settings.mautic_url and settings.mautic_user) or settings.resend_api_key)


# ---------------------------------------------------------------- Mautic
async def upsert_contact(email: str, name: str, fields: Optional[dict] = None) -> Optional[int]:
    """Create or update a Mautic contact, returning its id.

    Search-then-patch rather than a blind create: Mautic will happily hold two
    contacts with the same address, and a duplicate splits a person's timeline
    in half.
    """
    if not settings.mautic_url or not settings.mautic_user:
        return None

    payload = {"email": email, "firstname": name or email.split("@")[0]}
    payload.update(fields or {})
    auth = (settings.mautic_user, settings.mautic_pass)

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            found = await client.get(
                f"{settings.mautic_url}/api/contacts",
                params={"search": f"email:{email}", "limit": 1},
                auth=auth,
            )
            if found.status_code == 401:
                log.warning("mautic auth rejected (401) — check api_enable_basic_auth")
                return None

            contacts = found.json().get("contacts") or {}
            if contacts:
                cid = int(next(iter(contacts)))
                await client.patch(
                    f"{settings.mautic_url}/api/contacts/{cid}/edit", json=payload, auth=auth
                )
                return cid

            created = await client.post(
                f"{settings.mautic_url}/api/contacts/new", json=payload, auth=auth
            )
            cid = (created.json().get("contact") or {}).get("id")
            return int(cid) if cid else None
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        log.warning("mautic contact upsert failed for %s: %s", email, exc)
        return None


async def send_template(contact_id: int, template_id: int) -> bool:
    if not (settings.mautic_url and contact_id and template_id):
        return False
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT + 5) as client:
            r = await client.post(
                f"{settings.mautic_url}/api/emails/{template_id}/contact/{contact_id}/send",
                auth=(settings.mautic_user, settings.mautic_pass),
            )
        if r.status_code in (200, 201):
            return True
        log.warning(
            "mautic send failed: status=%s contact=%s tpl=%s body=%s",
            r.status_code, contact_id, template_id, r.text[:200],
        )
        return False
    except httpx.HTTPError as exc:
        log.warning("mautic send error: contact=%s tpl=%s %s", contact_id, template_id, exc)
        return False


# ---------------------------------------------------------------- Resend
async def send_resend(to: str, subject: str, html: str) -> bool:
    if not settings.resend_api_key:
        log.error("no mail channel available — cannot send %r to %s", subject, to)
        return False
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT + 5) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={"from": settings.email_from, "to": [to], "subject": subject, "html": html},
            )
        if r.status_code in (200, 201):
            return True
        log.error("resend failed: status=%s body=%s", r.status_code, r.text[:200])
        return False
    except httpx.HTTPError as exc:
        log.error("resend error sending to %s: %s", to, exc)
        return False


# ---------------------------------------------------------------- public
async def send(
    to: str,
    name: str,
    subject: str,
    html: str,
    template_id: int = 0,
    fields: Optional[dict] = None,
) -> bool:
    """Send one message. Mautic when it is configured and working, Resend when
    it is not. `html` is both the Resend body and the record of what the Mautic
    template is supposed to say — keep the two in step.
    """
    if template_id:
        cid = await upsert_contact(to, name, fields)
        if cid and await send_template(cid, template_id):
            return True
        log.warning("falling back to resend for %s (mautic tpl %s)", to, template_id)

    return await send_resend(to, subject, html)


# ---------------------------------------------------------------- messages
# Plain HTML on purpose. These are the fallback bodies, and a fallback that
# depends on a CSS pipeline is a fallback that breaks in Outlook. The Mautic
# templates are where design lives.
def _wrap(heading: str, body: str, url: str, cta: str, footer: str) -> str:
    return f"""\
<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:520px;
            margin:0 auto;padding:32px 24px;color:#1a1a1a">
  <div style="font-weight:700;font-size:18px;margin-bottom:24px">Intent Desk</div>
  <h1 style="font-size:20px;margin:0 0 12px">{heading}</h1>
  <p style="margin:0 0 24px;line-height:1.55;color:#444">{body}</p>
  <a href="{url}" style="display:inline-block;background:#1a1a1a;color:#fff;
     text-decoration:none;padding:12px 20px;border-radius:8px;font-weight:600">{cta}</a>
  <p style="margin:24px 0 0;font-size:13px;line-height:1.5;color:#777">{footer}</p>
  <p style="margin:12px 0 0;font-size:12px;color:#999;word-break:break-all">{url}</p>
</div>"""


def verify_email(url: str) -> tuple[str, str]:
    return (
        "Confirm your Intent Desk email",
        _wrap(
            "Confirm your email",
            "Click below to finish setting up your Intent Desk account. "
            "You will not be able to sign in until you do.",
            url,
            "Confirm email",
            "This link works once and expires in 24 hours. "
            "If you did not create an account, ignore this email.",
        ),
    )


def existing_account_email(url: str, has_password: bool, has_google: bool) -> tuple[str, str]:
    """Sent when someone signs up with an address that already has an account.

    The signup form cannot say "that address is taken" without becoming a way to
    test which addresses are registered. So the answer goes to the address
    instead, where only its owner sees it. Without this, a duplicate signup is a
    dead end: the form says "check your email" and nothing is ever sent.
    """
    if has_google and not has_password:
        body = (
            "You already have an Intent Desk account on this address, created "
            "with Google. Sign in with the Google button and it will let you "
            "straight in — there is no password to enter. If you would rather "
            "use a password, set one below."
        )
    else:
        body = (
            "You already have an Intent Desk account on this address, so we did "
            "not create a second one. Sign in with your existing password, or "
            "choose a new one below if you have forgotten it."
        )
    return (
        "You already have an Intent Desk account",
        _wrap(
            "You already have an account",
            body,
            url,
            "Set a password",
            "This link works once and expires in 1 hour. If you did not try to "
            "sign up, ignore this email — your account is unchanged.",
        ),
    )


def reset_email(url: str) -> tuple[str, str]:
    return (
        "Reset your Intent Desk password",
        _wrap(
            "Reset your password",
            "Someone asked to reset the password on this account. "
            "Choose a new one using the link below.",
            url,
            "Set a new password",
            "This link works once and expires in 1 hour. If you did not ask for "
            "it, no action is needed — your current password still works.",
        ),
    )
