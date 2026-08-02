"""Accounts, passwords and access rules.

The properties tested here are the ones whose absence is invisible until it is
exploited: a login form that reveals which addresses exist, a password check
that accepts a Google-only account, an access rule that only applies at
registration.
"""

import asyncio

import pytest

from intentdesk.api import pages
from intentdesk.services import preferences, users


class FakeDB:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.executed = []

    async def fetch(self, sql, *args):
        return self.rows.get("fetch", [])

    async def fetchrow(self, sql, *args):
        value = self.rows.get("fetchrow")
        return value(sql, args) if callable(value) else value

    async def fetchval(self, sql, *args):
        return self.rows.get("fetchval")

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "INSERT 0 1"


@pytest.fixture
def stub(monkeypatch):
    def install(prefs=None, **rows):
        from intentdesk import db

        fake = FakeDB(rows)
        for name in ("fetch", "fetchrow", "fetchval", "execute"):
            monkeypatch.setattr(db, name, getattr(fake, name))
        merged = {**preferences.DEFAULTS, **(prefs or {})}

        async def all_prefs():
            return merged

        monkeypatch.setattr(preferences, "all_prefs", all_prefs)
        return fake

    return install


# ------------------------------------------------------------------ passwords


def test_password_round_trips():
    stored = users.hash_password("correct horse battery staple")
    assert users.verify_password("correct horse battery staple", stored)
    assert not users.verify_password("Correct horse battery staple", stored)


def test_hash_is_salted():
    """Two identical passwords must not produce identical hashes, or one leaked
    table reveals every shared password at a glance."""
    a = users.hash_password("same password here")
    b = users.hash_password("same password here")
    assert a != b


def test_stored_hash_contains_no_plaintext():
    stored = users.hash_password("hunter2hunter2hunter2")
    assert "hunter2" not in stored
    assert stored.startswith("scrypt$")


def test_google_only_account_rejects_any_password():
    """password_hash is NULL for Google accounts. Returning False rather than
    raising keeps the failure indistinguishable from a wrong password."""
    assert users.verify_password("anything", None) is False
    assert users.verify_password("anything", "") is False


def test_malformed_hash_is_refused_not_crashed():
    for junk in ("plaintext", "scrypt$broken", "scrypt$a$b$c$d$e", "$$$$$"):
        assert users.verify_password("x", junk) is False


@pytest.mark.parametrize("bad", ["", "short", "elevenchars"])
def test_short_passwords_rejected(bad):
    assert users.password_problem(bad) is not None


def test_long_passphrase_accepted_without_symbol_rules():
    """NIST dropped composition rules because they push people to P@ssw0rd1."""
    assert users.password_problem("a quiet blue tuesday") is None


# --------------------------------------------------------------- access rules


def test_open_mode_admits_any_address(stub):
    stub(prefs={"access_mode": "open"})
    asyncio.run(users.check_allowed("anyone@gmail.com"))


def test_domain_mode_admits_the_domain(stub):
    stub(prefs={"access_mode": "domain", "allowed_email_domains": "swandigitals.com"})
    asyncio.run(users.check_allowed("priya@swandigitals.com"))


def test_domain_mode_refuses_others(stub):
    stub(prefs={"access_mode": "domain", "allowed_email_domains": "swandigitals.com"})
    with pytest.raises(users.AuthError, match="not permitted"):
        asyncio.run(users.check_allowed("someone@gmail.com"))


def test_lookalike_domain_is_refused(stub):
    """notswandigitals.com must not pass a suffix check on swandigitals.com."""
    stub(prefs={"access_mode": "domain", "allowed_email_domains": "swandigitals.com"})
    with pytest.raises(users.AuthError):
        asyncio.run(users.check_allowed("x@notswandigitals.com"))


def test_allowlist_mode_admits_an_existing_outside_account(stub):
    stub(
        prefs={"access_mode": "allowlist", "allowed_email_domains": "swandigitals.com"},
        fetchrow=lambda sql, args: {"?column?": 1},
    )
    asyncio.run(users.check_allowed("contractor@gmail.com"))


def test_allowlist_mode_refuses_an_unknown_outsider(stub):
    stub(
        prefs={"access_mode": "allowlist", "allowed_email_domains": "swandigitals.com"},
        fetchrow=None,
    )
    with pytest.raises(users.AuthError):
        asyncio.run(users.check_allowed("stranger@gmail.com"))


@pytest.mark.parametrize("bad", ["", "notanemail", "no@domain", "two@@at.com", "a b@c.com"])
def test_malformed_addresses_refused(stub, bad):
    stub(prefs={"access_mode": "open"})
    with pytest.raises(users.AuthError):
        asyncio.run(users.check_allowed(bad))


# ------------------------------------------------------------- enumeration


def test_wrong_password_and_missing_account_give_the_same_message(stub):
    stub(prefs={"access_mode": "open"}, fetchrow=None)
    with pytest.raises(users.AuthError) as missing:
        asyncio.run(users.authenticate("nobody@example.com", "some password here"))

    stored = users.hash_password("the real password")
    stub(
        prefs={"access_mode": "open"},
        fetchrow=lambda sql, args: {
            "id": 1, "email": "real@example.com", "name": "Real",
            "password_hash": stored, "disabled": False, "is_admin": False,
        },
    )
    with pytest.raises(users.AuthError) as wrong:
        asyncio.run(users.authenticate("real@example.com", "not the password"))

    assert str(missing.value) == str(wrong.value) == "Wrong email or password."


def test_registering_a_taken_address_does_not_say_so(stub):
    stub(
        prefs={"access_mode": "open"},
        fetchrow=lambda sql, args: {
            "id": 1, "email": "taken@example.com", "name": "T",
            "password_hash": "x", "disabled": False, "is_admin": False,
        },
    )
    result = asyncio.run(users.register("taken@example.com", "a quiet blue tuesday"))
    assert result == {"email": "taken@example.com", "created": False}


def test_disabled_account_cannot_sign_in(stub):
    stored = users.hash_password("a quiet blue tuesday")
    stub(
        prefs={"access_mode": "open"},
        fetchrow=lambda sql, args: {
            "id": 1, "email": "gone@example.com", "name": "G",
            "password_hash": stored, "disabled": True, "is_admin": False,
        },
    )
    with pytest.raises(users.AuthError):
        asyncio.run(users.authenticate("gone@example.com", "a quiet blue tuesday"))


def test_session_user_never_carries_the_hash():
    out = users._session_user({
        "email": "a@b.com", "name": "A", "is_admin": True, "password_hash": "scrypt$secret",
    })
    assert "password_hash" not in out
    assert out == {"email": "a@b.com", "name": "A", "is_admin": True}


# ------------------------------------------------------------ settings guard


def test_switching_to_domain_mode_and_clearing_domains_together_is_refused(stub):
    """The lockout that costs a psql session to undo: both changes in one PATCH,
    so neither is invalid on its own."""
    stub()
    with pytest.raises(ValueError, match="at least one entry"):
        asyncio.run(preferences.update(
            {"access_mode": "domain", "allowed_email_domains": "  "}
        ))


def test_domain_mode_is_refused_when_the_stored_list_is_already_empty(stub):
    """Same lockout by a slower route: the list was emptied earlier, and only
    the mode is being changed now. The guard reads the stored value, not just
    what is in this request."""
    stub(fetchrow={"value": ""})
    with pytest.raises(ValueError, match="at least one entry"):
        asyncio.run(preferences.update({"access_mode": "domain"}))


def test_domain_mode_is_allowed_when_domains_exist(stub):
    stub(fetchrow={"value": "swandigitals.com"})
    asyncio.run(preferences.update({"access_mode": "domain"}))


def test_unknown_access_mode_is_refused(stub):
    stub()
    with pytest.raises(ValueError, match="access_mode must be"):
        asyncio.run(preferences.update({"access_mode": "everyone-please"}))


# ------------------------------------------------------------------- pages


def test_pages_escape_user_supplied_values():
    """error and email come straight off the query string."""
    html = pages.login_page("open", [], error="<script>alert(1)</script>",
                            email='"><script>x</script>')
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_login_page_states_the_access_rule():
    assert "Anyone can sign in" in pages.login_page("open", [])
    assert "@example.com addresses only." in pages.login_page("domain", ["example.com"])


def test_no_company_domain_is_baked_into_the_default_config():
    """The default must not name a domain. One sitting in config reads as a
    restriction and waits to become one the moment access_mode changes."""
    from intentdesk.config import Settings

    assert Settings.model_fields["allowed_email_domain"].default == ""
    assert Settings.model_fields["access_mode"].default == "open"


def test_open_mode_pages_never_name_a_required_domain():
    for html in (pages.login_page("open", []), pages.signup_page("open", [])):
        assert "addresses only" not in html
        assert "you@example.com" in html  # a generic placeholder, not a company


def test_pages_are_not_indexable():
    """A sign-in page in search results is noise at best."""
    assert "noindex" in pages.login_page("open", [])
    assert "noindex" in pages.signup_page("open", [])
