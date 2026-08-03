"""The public page at /.

Server-rendered rather than part of the React bundle, for the same reason the
auth screens are (see `pages.py`) plus one specific to this page: a marketing
page has to render for a crawler that executes no JavaScript. A 200KB bundle
that paints the copy on the client is a page Google sees as empty.

**The honesty rule for this file.** Every capability claim below is checked
against `intentdesk/market.py`, which records what was tried and what failed.
Capterra is 403-blocked on the current Apify plan, the Indeed job collector was
tested against the live API and does not work, and Reddit needs OAuth
credentials that do not exist yet. None of those may be described as working.
The status table in the signals section says so out loud, which is a stronger
sales position than a logo wall and has the advantage of being true.

Brand palette is imported from `pages.py` so the landing page, the sign-in page
and the signup page cannot drift apart.
"""

from html import escape

from intentdesk.api.pages import BRAND, _GOOGLE_MARK
from intentdesk.market import ACTIVE_COMPETITORS
from intentdesk.services.users import MIN_PASSWORD_LENGTH

TITLE = "Intent Desk — find event organisers ready to switch ticketing platform"
DESCRIPTION = (
    "Intent Desk watches nine event-ticketing platforms across India and "
    "surfaces the organisers showing switch signals — ranked, contactable, "
    "with a phone-first draft already written."
)
CANONICAL = "https://intent.swandigitals.com/"

_CSS = """
*,*::before,*::after{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font-family:'DM Sans','Inter',system-ui,-apple-system,sans-serif;
 color:%(text)s;background:#fff;-webkit-font-smoothing:antialiased;line-height:1.6}
img{max-width:100%%}
h1,h2,h3{line-height:1.2;margin:0 0 14px;letter-spacing:-.02em}
h1{font-size:clamp(30px,5.2vw,52px);font-weight:700}
h2{font-size:clamp(23px,3.2vw,34px);font-weight:700}
h3{font-size:17px;font-weight:600;margin-bottom:7px}
p{margin:0 0 14px}
a{color:%(orange_dark)s}
.wrap{max-width:1080px;margin:0 auto;padding:0 22px}
.eyebrow{font-size:11.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
 color:%(orange_dark)s;margin-bottom:12px}
.lede{font-size:clamp(16px,1.9vw,19px);color:%(muted)s;max-width:65ch}

/* ------------------------------------------------------------------ nav */
.nav{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.92);
 backdrop-filter:blur(10px);border-bottom:1px solid %(border)s}
.nav .wrap{display:flex;align-items:center;gap:26px;height:64px}
.brand{display:flex;align-items:center;gap:9px;font-weight:700;font-size:16px;
 text-decoration:none;color:%(text)s;flex:0 0 auto}
.dot{width:10px;height:10px;border-radius:50%%;
 background:linear-gradient(135deg,%(orange)s,%(pink)s)}
.brand span{font-weight:400;font-size:12px;color:%(light)s}
.nav nav{display:flex;gap:20px;margin-left:auto}
.nav nav a{font-size:13.5px;color:%(muted)s;text-decoration:none}
.nav nav a:hover{color:%(text)s}
.nav-cta{display:flex;gap:9px;align-items:center;flex:0 0 auto}

.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;
 padding:11px 19px;border-radius:9px;border:1px solid %(border)s;background:#fff;
 color:%(text)s;font:inherit;font-size:14px;font-weight:500;text-decoration:none;
 cursor:pointer;transition:transform .12s,box-shadow .15s,filter .15s}
.btn:hover{border-color:%(orange)s;color:%(orange_dark)s}
.btn:active{transform:translateY(1px)}
.btn-primary{background:linear-gradient(135deg,%(orange)s,%(pink)s);border-color:transparent;
 color:#fff;font-weight:600;box-shadow:0 6px 18px -8px %(orange)s}
.btn-primary:hover{filter:brightness(1.06);color:#fff}
.btn-sm{padding:8px 14px;font-size:13px}

/* ----------------------------------------------------------------- hero */
.hero{padding:76px 0 64px;background:
 radial-gradient(900px 380px at 12%% -8%%,%(orange_light)s,transparent 70%%),
 linear-gradient(180deg,#fff,%(surface)s)}
.hero h1{max-width:16ch}
.hero .lede{margin-bottom:26px}
.hero-cta{display:flex;gap:11px;flex-wrap:wrap;align-items:center}
.hero-note{margin:18px 0 0;font-size:13px;color:%(light)s}

/* --------------------------------------------------------------- layout */
section{padding:64px 0;border-top:1px solid %(border)s}
section.plain{border-top:0}
.grid{display:grid;gap:18px;margin-top:30px}
.g3{grid-template-columns:repeat(3,1fr)}
.g2{grid-template-columns:repeat(2,1fr)}
.card{padding:22px;border:1px solid %(border)s;border-radius:12px;background:#fff}
.card p{margin:0;font-size:14px;color:%(muted)s}
.card.tint{background:%(surface)s}

/* chips — the complaint taxonomy and the watchlist */
.chips{display:flex;flex-wrap:wrap;gap:9px;margin-top:26px}
.chip{padding:8px 14px;border-radius:99px;border:1px solid %(border)s;
 background:%(surface)s;font-size:13.5px;color:%(text)s}
.chip.brand{background:%(orange_light)s;border-color:%(orange)s;color:%(orange_dark)s}

/* steps */
.steps{counter-reset:s;display:grid;gap:16px;margin-top:30px}
.step{display:grid;grid-template-columns:38px 1fr;gap:15px;align-items:start;
 padding:18px 20px;border:1px solid %(border)s;border-radius:12px}
.step::before{counter-increment:s;content:counter(s);width:30px;height:30px;
 border-radius:50%%;display:grid;place-items:center;font-weight:700;font-size:14px;
 background:%(orange_light)s;color:%(orange_dark)s}
.step p{margin:0;font-size:14px;color:%(muted)s}

/* status table */
.tablewrap{overflow-x:auto;margin-top:28px;border:1px solid %(border)s;border-radius:12px}
table{border-collapse:collapse;width:100%%;min-width:560px;font-size:14px}
th,td{text-align:left;padding:13px 16px;border-bottom:1px solid %(border)s}
th{font-size:11.5px;text-transform:uppercase;letter-spacing:.07em;color:%(light)s;
 background:%(surface)s}
tr:last-child td{border-bottom:0}
.tag{display:inline-block;padding:2px 9px;border-radius:99px;font-size:11.5px;font-weight:600}
.tag-live{background:%(ok_bg)s;color:%(ok)s}
.tag-thin{background:#fffbeb;color:#a16207}
.tag-soon{background:%(surface_2)s;color:%(muted)s}
.tag-no{background:%(danger_bg)s;color:%(danger)s}
.note{margin-top:18px;padding:15px 18px;border-left:3px solid %(orange)s;
 background:%(orange_light)s;border-radius:0 9px 9px 0;font-size:14px}
.note p{margin:0;color:%(text)s}

/* features */
.feat{display:grid;grid-template-columns:repeat(2,1fr);gap:11px 26px;margin-top:26px;
 padding:0;list-style:none}
.feat li{padding-left:26px;position:relative;font-size:14.5px;color:%(muted)s}
.feat li::before{content:"";position:absolute;left:0;top:8px;width:13px;height:7px;
 border-left:2px solid %(orange)s;border-bottom:2px solid %(orange)s;transform:rotate(-45deg)}

/* guardrails */
.guard{background:%(charcoal)s;color:#e2e8f0;border-radius:16px;padding:38px 34px;margin-top:8px}
.guard h2{color:#fff}
.guard p{color:#cbd5e1;max-width:62ch}
.guard strong{color:#fff}

/* faq */
details{border:1px solid %(border)s;border-radius:11px;padding:16px 19px;margin-bottom:10px}
details[open]{background:%(surface)s}
summary{cursor:pointer;font-weight:600;font-size:15px;list-style:none}
summary::-webkit-details-marker{display:none}
summary::after{content:"+";float:right;color:%(orange_dark)s;font-weight:700}
details[open] summary::after{content:"\\2212"}
details p{margin:11px 0 0;font-size:14px;color:%(muted)s}

/* ---------------------------------------------------------- signup form */
.signup{background:linear-gradient(180deg,%(surface)s,#fff);border-top:1px solid %(border)s}
.signup-grid{display:grid;grid-template-columns:1fr 400px;gap:44px;align-items:start}
.form-card{padding:26px;border:1px solid %(border)s;border-radius:14px;background:#fff;
 box-shadow:0 1px 2px rgba(15,23,42,.05),0 18px 40px -26px rgba(15,23,42,.3)}
.field{margin-bottom:14px}
.field label{display:block;font-size:12.5px;font-weight:600;margin-bottom:6px}
.field input{width:100%%;padding:11px 13px;border:1px solid %(border)s;border-radius:9px;
 font:inherit;font-size:14.5px;background:%(surface)s;color:%(text)s}
.field input:focus{outline:2px solid %(orange)s;outline-offset:-1px;border-color:%(orange)s;
 background:#fff}
.form-card .btn{width:100%%}
.hint{font-size:12px;color:%(light)s;margin-top:7px}
.or{display:flex;align-items:center;gap:11px;margin:16px 0;color:%(light)s;font-size:12px}
.or::before,.or::after{content:"";flex:1;height:1px;background:%(border)s}
.btn-google{width:100%%;background:#fff}
.form-foot{margin:15px 0 0;font-size:13px;color:%(muted)s;text-align:center}

/* -------------------------------------------------------------- footer */
footer{border-top:1px solid %(border)s;padding:30px 0;font-size:13px;color:%(light)s}
footer .wrap{display:flex;gap:18px;flex-wrap:wrap;align-items:center}
footer a{color:%(muted)s;text-decoration:none}
footer a:hover{color:%(orange_dark)s}
footer .grow{flex:1}

/* ---------------------------------------------------------- responsive */
@media (max-width:900px){
  .signup-grid{grid-template-columns:1fr;gap:28px}
  .g3{grid-template-columns:1fr 1fr}
}
@media (max-width:720px){
  .nav nav{display:none}
  .nav .wrap{gap:12px}
  .g3,.g2,.feat{grid-template-columns:1fr}
  .hero{padding:52px 0 46px}
  section{padding:48px 0}
  .guard{padding:28px 22px}
}
@media (max-width:380px){
  .nav-cta .btn:not(.btn-primary){display:none}
}

/* Dark mode: the auth pages already honour it, and a page that flips to a
   white slab at midnight looks broken next to them. */
@media (prefers-color-scheme:dark){
  body{background:#0b1220;color:#e2e8f0}
  .nav{background:rgba(11,18,32,.92);border-color:#1e293b}
  .brand{color:#f1f5f9}
  .nav nav a{color:#94a3b8}
  .nav nav a:hover{color:#f1f5f9}
  .btn{background:#111c2e;border-color:#1e293b;color:#e2e8f0}
  .hero{background:radial-gradient(900px 380px at 12%% -8%%,#2a1a10,transparent 70%%),
   linear-gradient(180deg,#0b1220,#0e1626)}
  .lede,.card p,.step p,details p,.feat li{color:#94a3b8}
  section{border-color:#1e293b}
  .card,.step,details,.tablewrap,.form-card{background:#111c2e;border-color:#1e293b}
  .card.tint,.chip,th,details[open]{background:#0e1626;border-color:#1e293b}
  .chip{color:#e2e8f0}
  .chip.brand{background:#2a1a10;border-color:%(orange)s;color:#fdba74}
  th,td{border-color:#1e293b}
  .note{background:#2a1a10}
  .note p{color:#fed7aa}
  .signup{background:linear-gradient(180deg,#0e1626,#0b1220);border-color:#1e293b}
  .field input{background:#0e1626;border-color:#1e293b;color:#e2e8f0}
  .btn-google{background:#111c2e}
  footer{border-color:#1e293b}
}
""" % BRAND

_JSONLD = """{
  "@context":"https://schema.org",
  "@type":"SoftwareApplication",
  "name":"Intent Desk",
  "applicationCategory":"BusinessApplication",
  "operatingSystem":"Web",
  "description":"%s",
  "url":"%s",
  "publisher":{"@type":"Organization","name":"Swan Digitals",
   "url":"https://swandigitals.com"}
}""" % (DESCRIPTION, CANONICAL)


def _shell(body: str) -> str:
    """Deliberately not `pages._shell`.

    That one emits `noindex,nofollow` — correct for a sign-in screen, and the
    single tag most capable of quietly making this whole page pointless.
    """
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(TITLE)}</title>"
        f"<meta name='description' content='{escape(DESCRIPTION)}'>"
        f"<link rel='canonical' href='{CANONICAL}'>"
        "<meta property='og:type' content='website'>"
        f"<meta property='og:title' content='{escape(TITLE)}'>"
        f"<meta property='og:description' content='{escape(DESCRIPTION)}'>"
        f"<meta property='og:url' content='{CANONICAL}'>"
        "<meta property='og:site_name' content='Intent Desk'>"
        "<meta name='twitter:card' content='summary_large_image'>"
        f"<meta name='twitter:title' content='{escape(TITLE)}'>"
        f"<meta name='twitter:description' content='{escape(DESCRIPTION)}'>"
        "<meta name='theme-color' content='#f97316'>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
        "<link href='https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap' rel='stylesheet'>"
        f"<script type='application/ld+json'>{_JSONLD}</script>"
        f"<style>{_CSS}</style></head><body>{body}</body></html>"
    )


# The watchlist, straight from market.py, so the page cannot claim to track a
# platform the product does not actually watch.
#
# ACTIVE_COMPETITORS, not every registered brand: Phase C added an expansion set
# that is deliberately switched off, and listing those here would be the page
# claiming coverage the scan does not have.
def _competitor_chips() -> str:
    return "".join(
        f"<span class='chip'>{escape(name)}</span>" for name in ACTIVE_COMPETITORS
    )


# market.COMPLAINT_CATEGORIES, in the organiser's own words rather than as enum
# keys. Kept in this order because fees and payouts are what actually move an
# organiser off a platform.
_COMPLAINTS = [
    "High per-ticket and service fees",
    "Payouts held long after the event",
    "Refunds and chargebacks handled badly",
    "Scanning and check-in failures at the door",
    "Nobody answering on event day",
    "Ticket pages that cannot carry their brand",
    "No CRM, marketing or accounting integration",
    "Thin attendee reporting",
    "Outages at on-sale",
]

# Status values must match what market.py records. See the module docstring.
_SOURCES = [
    ("Vendor news", "Fee rises, outages, breaches and shutdowns at a platform",
     "tag-live", "Live"),
    ("Technology detection", "Which ticketing platform a company runs today",
     "tag-live", "Live"),
    ("B2B review sites", "Organiser complaints, with rating and reviewer role",
     "tag-thin", "Live, thin in India"),
    ("Organiser forums", "Unprompted complaints in organiser communities",
     "tag-soon", "Coming"),
    ("Job postings", "A named platform in an operating role",
     "tag-no", "Tested, not usable"),
]

_FAQ = [
    ("Does it send emails or make calls for me?",
     "No. Intent Desk finds and drafts; you read every draft and make every "
     "call. Nothing leaves the system on its own."),
    ("Do I need a list to start?",
     "Yes — a CSV of organisers with name, domain and city. Being straight "
     "about it: the discovery collectors do not yet build a database from "
     "nothing, so you bring the starting list and Intent Desk works out which "
     "of them are ready to move."),
    ("Which platforms does it track?",
     "The nine above out of the box, and the watchlist is yours to edit — add "
     "or remove any platform you actually compete with."),
    ("Is it built for India?",
     "Yes. Indian platforms, Indian cities, phone-first outreach because that "
     "is what gets answered, and a monthly spend cap in the currency your "
     "scanners actually bill in."),
    ("What does it cost to run?",
     "It runs against a monthly scanning cap you set, and stops when it is "
     "reached. There is no published price yet — this is early, and quoting "
     "one before it exists would be a number made up for a web page."),
]


def landing_page() -> str:
    complaints = "".join(f"<span class='chip brand'>{escape(c)}</span>" for c in _COMPLAINTS)

    rows = "".join(
        f"<tr><td><b>{escape(n)}</b></td><td>{escape(d)}</td>"
        f"<td><span class='tag {cls}'>{escape(label)}</span></td></tr>"
        for n, d, cls, label in _SOURCES
    )

    faq = "".join(
        f"<details><summary>{escape(q)}</summary><p>{escape(a)}</p></details>"
        for q, a in _FAQ
    )

    body = f"""
<header class='nav'>
  <div class='wrap'>
    <a class='brand' href='/'><span class='dot'></span>Intent Desk
      <span>by Swan Digitals</span></a>
    <nav>
      <a href='#problem'>The problem</a>
      <a href='#who'>Who it's for</a>
      <a href='#signals'>What it watches</a>
      <a href='#how'>How it works</a>
      <a href='#faq'>FAQ</a>
    </nav>
    <div class='nav-cta'>
      <a class='btn btn-sm' href='/login'>Sign in</a>
      <a class='btn btn-sm btn-primary' href='#get-started'>Get started</a>
    </div>
  </div>
</header>

<section class='hero plain'>
  <div class='wrap'>
    <div class='eyebrow'>Competitive intent for event ticketing</div>
    <h1>Know which event organisers are ready to leave their ticketing platform.</h1>
    <p class='lede'>Intent Desk watches nine ticketing platforms across India and
    surfaces the organisers showing switch signals — ranked by how ready they
    are, with a phone number and a call script already written.</p>
    <div class='hero-cta'>
      <a class='btn btn-primary' href='#get-started'>Get started</a>
      <a class='btn' href='/login'>Sign in</a>
    </div>
    <p class='hero-note'>Built for India. Phone-first, because that is what gets answered.</p>
  </div>
</section>

<section id='problem'>
  <div class='wrap'>
    <div class='eyebrow'>The problem</div>
    <h2>Your competitor's unhappy customers never raise their hand.</h2>
    <p class='lede'>They complain in public, to each other, months before they
    ever talk to a salesperson. By the time they are shopping, you are one of
    five quotes.</p>
    <div class='grid g3'>
      <div class='card'><h3>Lists go stale</h3><p>A scraped list of event
      companies tells you who exists. It does not tell you who is unhappy, and
      it is wrong within a quarter.</p></div>
      <div class='card'><h3>Timing is invisible</h3><p>The month after a fee
      hike, a held payout or a check-in failure at the door is when an organiser
      will take your call. You cannot see that month.</p></div>
      <div class='card'><h3>Tenders are price fights</h3><p>Once it reaches
      procurement you are competing on discount. Intent shows up in public long
      before a tender does.</p></div>
    </div>
  </div>
</section>

<section id='who'>
  <div class='wrap'>
    <div class='eyebrow'>Who it's for</div>
    <h2>Built for one buyer, not for everybody.</h2>
    <div class='grid g3'>
      <div class='card'><h3>Ticketing platforms winning switchers</h3>
      <p>You compete with Eventbrite, BookMyShow, Townscript, Explara, Paytm
      Insider or MeraEvents, and you want their unhappy accounts — not a cold
      list of every event company in the country.</p></div>
      <div class='card'><h3>Founder-led sales</h3>
      <p>No SDR team, no list budget, no time. You need the twenty right calls
      this month, not two thousand wrong ones.</p></div>
      <div class='card'><h3>Regional and vertical players</h3>
      <p>You own a city or a category — weddings, conferences, festivals,
      campus. Filter by city, size band and the platform they run today.</p></div>
    </div>
    <div class='note'><p><b>Not for you if</b> you sell to ticket buyers rather
    than to organisers, or your market is outside event ticketing. The signal
    sources here are chosen for one buyer and would be noise for anyone
    else.</p></div>
    <div class='chips'>{_competitor_chips()}</div>
  </div>
</section>

<section id='signals'>
  <div class='wrap'>
    <div class='eyebrow'>What creates a switch signal</div>
    <h2>Nine things that make an organiser start looking.</h2>
    <p class='lede'>These are the complaints the system is tuned to recognise —
    not sentiment in general, but the specific failures that end a contract.</p>
    <div class='chips'>{complaints}</div>

    <h2 style='margin-top:52px'>Where the signals come from</h2>
    <div class='tablewrap'>
      <table>
        <thead><tr><th>Source</th><th>What it tells you</th><th>Status</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <div class='note'><p>We list what works, including what does not. Every
    source is health-checked inside the app — a broken scraper and a quiet week
    look identical from the outside, so Intent Desk tells you which one you are
    looking at.</p></div>
  </div>
</section>

<section id='how'>
  <div class='wrap'>
    <div class='eyebrow'>How it works</div>
    <h2>From a watchlist to a call you can actually make.</h2>
    <div class='steps'>
      <div class='step'><div><h3>Choose who to watch</h3><p>Add the platforms
      you compete with. The watchlist is data, not configuration — change it
      whenever your market does.</p></div></div>
      <div class='step'><div><h3>Signals get matched to real companies</h3>
      <p>Not a mention count. A named organiser with a domain and a city, or it
      is flagged unmatched rather than quietly guessed at.</p></div></div>
      <div class='step'><div><h3>Everything is scored and ranked</h3>
      <p>A confirmed install or a negative review weighs most, a job posting or
      forum complaint slightly less, vendor news least — and every signal loses
      half its weight after six months. You get hot, warm and cool, not an
      undifferentiated list.</p></div></div>
      <div class='step'><div><h3>A phone-first draft, waiting for approval</h3>
      <p>Written against your value proposition and the specific complaint that
      surfaced the lead. You edit it, you approve it, you make the call.</p></div></div>
    </div>

    <ul class='feat'>
      <li>Ranked queue with hot / warm / cool</li>
      <li>Contact name, title and phone number</li>
      <li>An editable draft on every lead</li>
      <li>CSV and Excel export</li>
      <li>Suppression list for companies you have ruled out</li>
      <li>Weekly digest of what changed</li>
      <li>Alerts when a collector goes quiet</li>
      <li>A monthly spend cap the scanners respect</li>
    </ul>
  </div>
</section>

<section>
  <div class='wrap'>
    <div class='guard'>
      <h2>Nothing sends itself.</h2>
      <p>Intent Desk finds and drafts. It <strong>never contacts anyone</strong> —
      you read every draft and make every call. Companies you reject go on a
      suppression list and stop appearing. Scanning stops at the monthly cap you
      set. Your queue exports to CSV or Excel whenever you want it, and it is
      your data to take.</p>
    </div>
  </div>
</section>

<section id='faq'>
  <div class='wrap'>
    <div class='eyebrow'>FAQ</div>
    <h2>The questions worth answering honestly.</h2>
    <div style='margin-top:28px'>{faq}</div>
  </div>
</section>

<section id='get-started' class='signup'>
  <div class='wrap'>
    <div class='signup-grid'>
      <div>
        <div class='eyebrow'>Get started</div>
        <h2>Start with the platforms you already compete with.</h2>
        <p class='lede'>Create an account, add your watchlist, import the
        organisers you already know about, and let the scoring tell you which
        twenty to call first.</p>
        <p class='lede' style='font-size:14px'>No credit card, because there is
        nothing to charge for yet.</p>
      </div>

      <div class='form-card'>
        <form method='post' action='/auth/register'>
          <div class='field'>
            <label for='name'>Name</label>
            <input id='name' name='name' type='text' autocomplete='name'
                   placeholder='Priya Nair'>
          </div>
          <div class='field'>
            <label for='email'>Work email</label>
            <input id='email' name='email' type='email' autocomplete='username'
                   required placeholder='you@company.com'>
          </div>
          <div class='field'>
            <label for='password'>Password</label>
            <input id='password' name='password' type='password'
                   autocomplete='new-password' required
                   minlength='{MIN_PASSWORD_LENGTH}' placeholder='••••••••••••'>
            <div class='hint'>At least {MIN_PASSWORD_LENGTH} characters. Length
            beats symbols.</div>
          </div>
          <button class='btn btn-primary' type='submit'>Create account</button>
        </form>

        <div class='or'>or</div>
        <a class='btn btn-google' href='/auth/login'>{_GOOGLE_MARK} Continue with Google</a>
        <p class='form-foot'>Already have an account? <a href='/login'>Sign in</a></p>
      </div>
    </div>
  </div>
</section>

<footer>
  <div class='wrap'>
    <span>Intent Desk — a Swan Digitals product</span>
    <span class='grow'></span>
    <a href='https://swandigitals.com'>swandigitals.com</a>
    <a href='/login'>Sign in</a>
    <a href='#get-started'>Create account</a>
  </div>
</footer>
"""
    return _shell(body)
