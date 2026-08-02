"""Server-rendered sign-in and sign-up pages.

Deliberately not part of the React bundle. Two reasons: a person who cannot sign
in should never be looking at a blank page because a 200KB bundle failed, and
the auth screens are the one part of the product that must work before any
JavaScript has proven it can run.

Brand palette taken from the Swan Digitals marketing site
(`veridia-app/tailwind.config.ts`): swan-orange #f97316, swan-pink #ec4899,
charcoal #1e293b, surface #f8fafc, DM Sans.
"""

from html import escape

BRAND = {
    "orange": "#f97316",
    "orange_dark": "#ea580c",
    "orange_light": "#fff7ed",
    "pink": "#ec4899",
    "charcoal": "#1e293b",
    "surface": "#f8fafc",
    "surface_2": "#f1f5f9",
    "border": "#e2e8f0",
    "text": "#0f172a",
    "muted": "#64748b",
    "light": "#94a3b8",
    "danger": "#b91c1c",
    "danger_bg": "#fef2f2",
    "ok": "#15803d",
    "ok_bg": "#f0fdf4",
}

_CSS = """
*,*::before,*::after{box-sizing:border-box}
body{margin:0;font-family:'DM Sans','Inter',system-ui,-apple-system,sans-serif;
 color:%(text)s;background:%(surface)s;-webkit-font-smoothing:antialiased;
 min-height:100vh;display:grid;place-items:center;padding:24px}

/* The brand gradient, used once. A second use would make it decoration. */
.wrap{width:100%%;max-width:410px}
.card{background:#fff;border:1px solid %(border)s;border-radius:16px;padding:34px 30px;
 box-shadow:0 1px 3px rgba(0,0,0,.06),0 12px 40px rgba(0,0,0,.06)}

.mark{display:flex;align-items:center;gap:10px;margin-bottom:26px}
.dot{width:30px;height:30px;border-radius:9px;flex:0 0 auto;
 background:linear-gradient(135deg,%(orange)s,%(pink)s)}
.mark b{font-size:16px;letter-spacing:-.01em}
.mark span{color:%(light)s;font-size:12px;font-weight:500}

h1{margin:0 0 6px;font-size:23px;line-height:1.25;letter-spacing:-.02em}
.sub{margin:0 0 24px;color:%(muted)s;font-size:14px;line-height:1.55}

label{display:block;font-size:12px;font-weight:600;letter-spacing:.02em;
 text-transform:uppercase;color:%(muted)s;margin:0 0 6px}
input{width:100%%;padding:11px 13px;font:inherit;font-size:14px;color:%(text)s;
 background:%(surface)s;border:1px solid %(border)s;border-radius:9px;
 transition:border-color .15s,box-shadow .15s}
input:focus{outline:none;border-color:%(orange)s;background:#fff;
 box-shadow:0 0 0 3px rgba(249,115,22,.14)}
.field{margin-bottom:15px}
.hint{margin-top:6px;font-size:12px;color:%(light)s}

.btn{width:100%%;padding:12px 16px;font:inherit;font-size:14px;font-weight:600;
 border-radius:9px;border:1px solid transparent;cursor:pointer;
 display:flex;align-items:center;justify-content:center;gap:9px;
 transition:transform .12s,box-shadow .15s,background .15s}
.btn:active{transform:translateY(1px)}
.btn-primary{color:#fff;background:linear-gradient(135deg,%(orange)s,%(orange_dark)s);
 box-shadow:0 4px 24px rgba(249,115,22,.22)}
.btn-primary:hover{box-shadow:0 6px 30px rgba(249,115,22,.32)}
.btn-google{background:#fff;border-color:%(border)s;color:%(charcoal)s}
.btn-google:hover{border-color:%(light)s;background:%(surface)s}

.or{display:flex;align-items:center;gap:12px;margin:20px 0;
 color:%(light)s;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.or::before,.or::after{content:"";height:1px;background:%(border)s;flex:1}

.note{margin-top:20px;padding-top:18px;border-top:1px solid %(border)s;
 font-size:13px;color:%(muted)s;text-align:center;line-height:1.6}
.note a{color:%(orange_dark)s;font-weight:600;text-decoration:none}
.note a:hover{text-decoration:underline}

.msg{padding:11px 13px;border-radius:9px;font-size:13px;line-height:1.5;
 margin-bottom:18px;border:1px solid transparent}
.msg-error{background:%(danger_bg)s;color:%(danger)s;border-color:#fecaca}
.msg-ok{background:%(ok_bg)s;color:%(ok)s;border-color:#bbf7d0}

.access{margin-top:14px;font-size:12px;color:%(light)s;text-align:center}
.foot{margin-top:18px;text-align:center;font-size:12px;color:%(light)s}
.foot a{color:%(muted)s;text-decoration:none}

@media (prefers-color-scheme:dark){
 body{background:#0b1220;color:#e2e8f0}
 .card{background:#111a2b;border-color:#1e293b;box-shadow:none}
 h1{color:#f1f5f9}
 input{background:#0b1220;border-color:#1e293b;color:#e2e8f0}
 input:focus{background:#0b1220}
 .btn-google{background:#0b1220;border-color:#1e293b;color:#e2e8f0}
 .btn-google:hover{background:#131f33}
 .or::before,.or::after,.note{border-color:#1e293b;background-color:transparent}
 .or::before,.or::after{background:#1e293b}
 .msg-error{background:#2a1416;border-color:#7f1d1d}
 .msg-ok{background:#0f2417;border-color:#166534}
}
""" % BRAND

_GOOGLE_MARK = (
    '<svg width="17" height="17" viewBox="0 0 48 48" aria-hidden="true">'
    '<path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.6 30.2.5 24 .5 14.6.5 6.5 5.9 2.6 13.7l7.8 6.1C12.3 13.9 17.6 9.5 24 9.5z"/>'
    '<path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-2.8-.4-4H24v8h12.9c-.3 2.1-1.7 5.3-4.9 7.4l7.6 5.9c4.5-4.2 6.9-10.3 6.9-17.3z"/>'
    '<path fill="#FBBC05" d="M10.4 28.4a14.7 14.7 0 0 1 0-9.4l-7.8-6.1a24 24 0 0 0 0 21.6l7.8-6.1z"/>'
    '<path fill="#34A853" d="M24 47.5c6.5 0 11.9-2.1 15.9-5.8l-7.6-5.9c-2 1.4-4.8 2.4-8.3 2.4-6.4 0-11.7-4.4-13.6-10.3l-7.8 6.1C6.5 42.1 14.6 47.5 24 47.5z"/>'
    "</svg>"
)


def _shell(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='robots' content='noindex,nofollow'>"
        f"<title>{escape(title)} · Intent Desk</title>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
        "<link href='https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap' rel='stylesheet'>"
        f"<style>{_CSS}</style></head><body>{body}</body></html>"
    )


def _mark() -> str:
    return (
        "<div class='mark'><div class='dot'></div>"
        "<b>Intent Desk</b><span>Swan Digitals</span></div>"
    )


def _message(error: str = "", notice: str = "") -> str:
    if error:
        return f"<div class='msg msg-error'>{escape(error)}</div>"
    if notice:
        return f"<div class='msg msg-ok'>{escape(notice)}</div>"
    return ""


def _access_line(mode: str, domains: list[str]) -> str:
    if mode == "open":
        return "Anyone can sign in — no invite and no company domain needed."
    listed = ", ".join("@" + d for d in domains) or "an approved domain"
    if mode == "allowlist":
        return f"{listed}, plus individually approved addresses."
    return f"{listed} addresses only."


def login_page(
    mode: str, domains: list[str], error: str = "", notice: str = "", email: str = ""
) -> str:
    body = f"""
    <div class='wrap'><div class='card'>
      {_mark()}
      <h1>Sign in</h1>
      <p class='sub'>Work the lead queue, review drafts, and run scans.
      Any email address works.</p>
      {_message(error, notice)}

      <a class='btn btn-google' href='/auth/login'>{_GOOGLE_MARK} Continue with Google</a>

      <div class='or'>or</div>

      <form method='post' action='/auth/password'>
        <div class='field'>
          <label for='email'>Email</label>
          <input id='email' name='email' type='email' autocomplete='username'
                 required value='{escape(email)}' placeholder='you@example.com'>
        </div>
        <div class='field'>
          <label for='password'>Password</label>
          <input id='password' name='password' type='password'
                 autocomplete='current-password' required placeholder='••••••••••••'>
        </div>
        <button class='btn btn-primary' type='submit'>Sign in</button>
      </form>

      <div class='note'>No account yet? <a href='/signup'>Create one</a></div>
      <div class='access'>{escape(_access_line(mode, domains))}</div>
    </div>
    <div class='foot'><a href='https://swandigitals.com'>swandigitals.com</a></div>
    </div>
    """
    return _shell("Sign in", body)


def signup_page(
    mode: str, domains: list[str], error: str = "", notice: str = "",
    email: str = "", name: str = "",
) -> str:
    from intentdesk.services.users import MIN_PASSWORD_LENGTH

    body = f"""
    <div class='wrap'><div class='card'>
      {_mark()}
      <h1>Create your account</h1>
      <p class='sub'>Open to anyone — any email address, no invite needed.
      Google needs no password at all, so it is the shorter path.</p>
      {_message(error, notice)}

      <a class='btn btn-google' href='/auth/login'>{_GOOGLE_MARK} Continue with Google</a>

      <div class='or'>or use a password</div>

      <form method='post' action='/auth/register'>
        <div class='field'>
          <label for='name'>Name</label>
          <input id='name' name='name' type='text' autocomplete='name'
                 value='{escape(name)}' placeholder='Priya Nair'>
        </div>
        <div class='field'>
          <label for='email'>Email</label>
          <input id='email' name='email' type='email' autocomplete='username'
                 required value='{escape(email)}' placeholder='you@example.com'>
        </div>
        <div class='field'>
          <label for='password'>Password</label>
          <input id='password' name='password' type='password'
                 autocomplete='new-password' required minlength='{MIN_PASSWORD_LENGTH}'
                 placeholder='••••••••••••'>
          <div class='hint'>At least {MIN_PASSWORD_LENGTH} characters. Length beats
          symbols — a short phrase you will remember is stronger than P@ssw0rd1.</div>
        </div>
        <button class='btn btn-primary' type='submit'>Create account</button>
      </form>

      <div class='note'>Already have one? <a href='/login'>Sign in</a></div>
      <div class='access'>{escape(_access_line(mode, domains))}</div>
    </div>
    <div class='foot'><a href='https://swandigitals.com'>swandigitals.com</a></div>
    </div>
    """
    return _shell("Create your account", body)
