"""The two public write-up pages at /work/*.

Server-rendered for the same reason the landing and auth pages are: this is a
document, it has to render for a reader who never runs JavaScript, and it must not
depend on the dashboard bundle. It is also read once, carefully, by someone
deciding something — so it is built for long-form reading rather than for
interaction.

**Design notes, so the next person does not undo them by accident.**

*The three surfaces are the spine.* Search, Answer and Generative each carry one
persistent hue and one letter, used as a tag wherever work belongs to a surface.
That is information: a reader can scan the page for "which of these is a GEO
play". It is not decoration, and it should not be extended to things that are not
surfaces.

*Every claim is chipped `measured` or `reasoned`.* The audit mixes things read off
the live site with things inferred from experience, and a reader who checks will
find the difference anyway. Marking it is cheaper than being caught, and it is the
most useful signal on the page.

*No webfonts.* Three system stacks — serif for display, sans for body, mono for
data. A linked font that fails leaves the page in a silent fallback, and this page
has one job on first load.

*Both themes come from tokens.* `:root` defines them, the dark media query
redefines only tokens, and `:root[data-theme=...]` overrides both directions.
Components never reference a colour inside a media query.

`noindex` on purpose: it is a submission, shared by link, not a page that should
turn up in a search for the company.
"""

import re

from html import escape

# Kept as reference rather than interpolated into the CSS. The CSS below declares
# these as custom properties, which is the actual token system; duplicating them
# through %-formatting was how the auth pages ended up escaping every literal %.
PALETTE = {
    "ink": "#14181a",
    "paper": "#f3f4f2",
    "search": "#14635c",
    "answer": "#9c6a15",
    "generative": "#8c3a50",
    "muted": "#6b7472",
}

_CSS = """
:root{
  color-scheme:light dark;
  --paper:#f3f4f2; --raise:#ffffff; --ink:#14181a; --body:#2c3336;
  --muted:#6b7472; --line:#dcdfda; --line-soft:#e8eae5;
  --search:#14635c; --answer:#8a5d12; --generative:#8c3a50;
  --search-bg:#e6efed; --answer-bg:#f5eddd; --generative-bg:#f6e8ec;
  --ok:#2f6b3c; --warn:#8a5d12; --stop:#8c2f2f;
  --measure:72ch;
  --gut:26px;
}
@media (prefers-color-scheme:dark){
  :root{
    --paper:#101416; --raise:#171c1f; --ink:#eef1ee; --body:#c8cfcc;
    --muted:#8b9693; --line:#2a3134; --line-soft:#222829;
    --search:#5fb8ad; --answer:#d8a44e; --generative:#e08a9f;
    --search-bg:#152a29; --answer-bg:#2b2317; --generative-bg:#2b1a1f;
    --ok:#6fbf82; --warn:#d8a44e; --stop:#e08a8a;
  }
}
:root[data-theme=light]{
  --paper:#f3f4f2; --raise:#ffffff; --ink:#14181a; --body:#2c3336;
  --muted:#6b7472; --line:#dcdfda; --line-soft:#e8eae5;
  --search:#14635c; --answer:#8a5d12; --generative:#8c3a50;
  --search-bg:#e6efed; --answer-bg:#f5eddd; --generative-bg:#f6e8ec;
  --ok:#2f6b3c; --warn:#8a5d12; --stop:#8c2f2f;
}
:root[data-theme=dark]{
  --paper:#101416; --raise:#171c1f; --ink:#eef1ee; --body:#c8cfcc;
  --muted:#8b9693; --line:#2a3134; --line-soft:#222829;
  --search:#5fb8ad; --answer:#d8a44e; --generative:#e08a9f;
  --search-bg:#152a29; --answer-bg:#2b2317; --generative-bg:#2b1a1f;
  --ok:#6fbf82; --warn:#d8a44e; --stop:#e08a8a;
}

*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;background:var(--paper);color:var(--body);
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  font-size:16.5px;line-height:1.68;-webkit-font-smoothing:antialiased;
}
::selection{background:var(--search-bg);color:var(--ink)}

/* ---------------------------------------------------------------- masthead */
.top{
  border-bottom:1px solid var(--line);background:var(--raise);
  position:sticky;top:0;z-index:20;
}
.top-in{
  max-width:1180px;margin:0 auto;padding:13px 26px;
  display:flex;align-items:baseline;gap:20px;flex-wrap:wrap;
}
.who{font-weight:650;color:var(--ink);letter-spacing:-.01em;font-size:15px}
.who span{color:var(--muted);font-weight:400}
.top nav{display:flex;gap:4px;margin-left:auto;flex-wrap:wrap}
.top nav a{
  font-size:13.5px;text-decoration:none;color:var(--muted);
  padding:5px 11px;border-radius:6px;
}
.top nav a:hover{color:var(--ink);background:var(--paper)}
.top nav a[aria-current=page]{color:var(--ink);font-weight:600;background:var(--paper)}

/* ------------------------------------------------------------------ layout */
.page{max-width:1280px;margin:0 auto;padding:0 var(--gut) 90px;
  display:grid;grid-template-columns:minmax(0,1fr);gap:0}
@media (min-width:1040px){
  /* The content column is wider than the reading measure on purpose. Prose is
     capped at `--measure` below; tables, the formula and the card grids take the
     whole column. Capping the *column* at the measure instead is what left a
     laptop with ~500px of empty screen while six-column tables scrolled inside a
     594px box — the wide content is what needs the width, not the paragraphs. */
  .page{grid-template-columns:210px minmax(0,900px);gap:48px;
    padding-top:8px;justify-content:center}
  .rail{display:block}
}
.rail{display:none;position:sticky;top:74px;align-self:start;
  padding-top:38px;font-size:13.5px;max-height:calc(100vh - 90px);overflow-y:auto}
.rail b{display:block;font-size:11px;letter-spacing:.09em;text-transform:uppercase;
  color:var(--muted);margin:0 0 10px}
.rail a{display:block;text-decoration:none;color:var(--muted);
  padding:4px 0 4px 11px;border-left:2px solid var(--line-soft);line-height:1.4}
.rail a:hover{color:var(--ink);border-left-color:var(--search)}

/* `main` fills its column; running text is what gets the measure, block by block.
   One rule, listing every text-level element, rather than a `.prose` wrapper class
   — the alternative is remembering to wrap, and the failure when you forget is a
   paragraph 900px wide, which is exactly the thing the measure exists to prevent. */
main{min-width:0}
/* Descendant selectors via :is(), not child selectors. The content sits inside
   `details > .secbody` now, and a `main > p` rule silently stops matching the
   moment anything is nested — the measure would vanish with nothing to show it. */
main :is(p,ul,ol,h1,h3,h4,.lede,.qual,.eyebrow,.note){max-width:var(--measure)}
/* Wide blocks deliberately take the full column: tables, the scoring formula,
   the stat rows and the layered lists all carry structure that benefits from
   width, and all of them were scrolling or wrapping badly inside the measure. */
main :is(.scroll,.formula,.grid2,.layers,.card,.stat,.next){max-width:none}

/* -------------------------------------------------------------- typography */
h1,h2,h3,h4{
  font-family:Georgia,"Iowan Old Style","Times New Roman",serif;
  color:var(--ink);text-wrap:balance;font-weight:600;
}
h1{font-size:clamp(30px,4.6vw,42px);line-height:1.13;letter-spacing:-.02em;
  margin:38px 0 12px}
h2{font-size:clamp(23px,2.7vw,28px);line-height:1.22;letter-spacing:-.015em;
  margin:56px 0 6px;padding-top:26px;border-top:1px solid var(--line)}
h3{font-size:18.5px;line-height:1.3;margin:34px 0 8px}
h4{font-size:15.5px;margin:24px 0 6px;font-family:inherit;font-weight:680}
p{margin:0 0 15px}
a{color:var(--search);text-decoration-thickness:1px;text-underline-offset:2px}
strong{color:var(--ink);font-weight:640}
em{color:var(--ink)}
ul,ol{margin:0 0 16px;padding-left:22px}
li{margin:0 0 7px}
li::marker{color:var(--muted)}
hr{border:0;border-top:1px solid var(--line);margin:34px 0}

.eyebrow{font-size:11.5px;letter-spacing:.11em;text-transform:uppercase;
  color:var(--muted);font-weight:650;margin:0}
.lede{font-size:19px;line-height:1.55;color:var(--ink);margin:0 0 22px}
.qual{font-size:14.5px;color:var(--muted);margin:0 0 20px}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:.875em}
code{background:var(--raise);border:1px solid var(--line-soft);
  border-radius:4px;padding:1px 5px}

/* ------------------------------------------------- surface + claim tagging */
.s{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.06em;
  text-transform:uppercase;padding:2px 7px;border-radius:4px;
  vertical-align:.1em;white-space:nowrap}
.s-search{color:var(--search);background:var(--search-bg)}
.s-answer{color:var(--answer);background:var(--answer-bg)}
.s-gen{color:var(--generative);background:var(--generative-bg)}

.chip{display:inline-block;font-size:10.5px;font-weight:650;letter-spacing:.05em;
  text-transform:uppercase;padding:1px 7px;border-radius:99px;
  border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.chip.measured{color:var(--ok);border-color:currentColor}
.chip.reasoned{color:var(--muted)}

/* ------------------------------------------------------------------ tables */
/* Scrollable tables carry their own edge shadow, which appears only while there
   is more to scroll to. A table that silently overflows on a phone is a table the
   reader never knows it is missing half of — the affordance is the fix, not a
   smaller font. `background-attachment: local` pins the covers to the content and
   `scroll` pins the shadows to the frame; that difference is what makes them
   self-hiding. */
.scroll{overflow-x:auto;margin:0 0 20px;border:1px solid var(--line);
  border-radius:9px;background-color:var(--raise);
  background-image:
    linear-gradient(to right,var(--raise) 30%,rgba(0,0,0,0)),
    linear-gradient(to left,var(--raise) 30%,rgba(0,0,0,0)),
    radial-gradient(farthest-side at 0 50%,rgba(0,0,0,.13),rgba(0,0,0,0)),
    radial-gradient(farthest-side at 100% 50%,rgba(0,0,0,.13),rgba(0,0,0,0));
  background-position:left center,right center,left center,right center;
  background-repeat:no-repeat;
  background-size:34px 100%,34px 100%,13px 100%,13px 100%;
  background-attachment:local,local,scroll,scroll;
  overscroll-behavior-x:contain}
/* No blanket min-width. Cells wrap instead, so a two-column table fits a phone
   with no scrolling at all and only genuinely wide ones scroll. */
table{border-collapse:collapse;width:100%;font-size:14.5px}
th,td{text-align:left;padding:10px 13px;border-bottom:1px solid var(--line-soft);
  vertical-align:top;hyphens:auto}
th{font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--muted);font-weight:650;
  background:var(--paper)}
@media (min-width:700px){th{white-space:nowrap}}
tr:last-child td{border-bottom:0}
td.num,th.num{font-family:ui-monospace,Menlo,monospace;
  font-variant-numeric:tabular-nums}

/* ------------------------------------------------------------------ blocks */
.card{background:var(--raise);border:1px solid var(--line);border-radius:10px;
  padding:20px 22px;margin:0 0 20px}
.card h4{margin-top:0}
.card > :last-child{margin-bottom:0}

.formula{background:var(--raise);border:1px solid var(--line);border-radius:10px;
  padding:20px 22px;margin:0 0 8px;overflow-x:auto;
  font-family:ui-monospace,Menlo,monospace;font-size:13.5px;line-height:1.75;
  color:var(--ink);white-space:pre}

.note{border-left:3px solid var(--line);padding:2px 0 2px 16px;margin:0 0 20px;
  color:var(--muted);font-size:15px}
.note.stop{border-left-color:var(--stop)}
.note.ok{border-left-color:var(--ok)}
.note strong{color:var(--ink)}

.grid2{display:grid;gap:14px;margin:0 0 20px}
@media (min-width:640px){.grid2{grid-template-columns:1fr 1fr}}

.stat{display:flex;flex-direction:column;gap:2px;background:var(--raise);
  border:1px solid var(--line);border-radius:9px;padding:14px 16px}
.stat b{font-family:ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums;
  font-size:24px;color:var(--ink);line-height:1.1}
.stat span{font-size:12.5px;color:var(--muted);line-height:1.35}

.layers{display:flex;flex-direction:column;gap:10px;margin:0 0 22px}
.layer{display:grid;grid-template-columns:auto minmax(0,1fr);gap:16px;
  background:var(--raise);border:1px solid var(--line);border-radius:10px;
  padding:16px 18px}
.layer .n{font-family:ui-monospace,Menlo,monospace;font-size:12px;font-weight:700;
  color:var(--muted);padding-top:3px}
.layer h4{margin:0 0 4px}
.layer p{margin:0 0 8px;font-size:15px}
.layer > div > :last-child{margin-bottom:0}

/* ------------------------------------------------------------------ footer */
.next{display:flex;gap:14px;flex-wrap:wrap;align-items:center;
  margin:64px 0 0;padding-top:24px;border-top:1px solid var(--line)}
.next a{display:inline-flex;flex-direction:column;gap:2px;text-decoration:none;
  border:1px solid var(--line);border-radius:9px;padding:12px 18px;
  background:var(--raise);color:var(--ink)}
.next a small{font-size:11.5px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--muted)}
.next a:hover{border-color:var(--search)}
.foot{max-width:1180px;margin:0 auto;padding:26px;color:var(--muted);
  font-size:13px;border-top:1px solid var(--line)}

a:focus-visible,button:focus-visible{outline:2px solid var(--search);
  outline-offset:2px;border-radius:3px}
@media (prefers-reduced-motion:reduce){*{transition:none!important;
  animation:none!important;scroll-behavior:auto!important}}
html{scroll-behavior:smooth}
:target{scroll-margin-top:86px}
/* --------------------------------------------------------------- accordion */
/* Native <details>. The whole document is ten screens of continuous column
   otherwise — measured at ~9,100px and ~10,200px — which is the complaint this
   answers. The risk of collapsing a submission is that a reader never opens a
   section, so it is mitigated three ways: the summary line carries the finding
   rather than only a title, "Expand all" is one click, and anything that needs
   the content open (printing, following an anchor) opens it automatically. */
details.sec{border-top:1px solid var(--line)}
details.sec:first-of-type{border-top:0}
summary{cursor:pointer;list-style:none;padding:19px 0;
  display:grid;grid-template-columns:auto minmax(0,1fr) auto;
  column-gap:14px;align-items:start}
summary::-webkit-details-marker{display:none}
summary::marker{content:""}
summary:hover h2,summary:focus-visible h2{color:var(--search)}
summary h2{grid-column:2;margin:0;padding:0;border-top:0;
  font-size:clamp(20px,2.4vw,25px);line-height:1.24}
.sc{grid-column:1;grid-row:1/span 2;font-family:ui-monospace,Menlo,monospace;
  font-size:11.5px;font-weight:700;color:var(--muted);letter-spacing:.04em;
  padding-top:7px;min-width:26px}
.sb{grid-column:2;margin:5px 0 0;font-size:14.5px;line-height:1.5;
  color:var(--muted);max-width:var(--measure)}
.chev{grid-column:3;grid-row:1;width:9px;height:9px;margin-top:9px;
  border-right:2px solid var(--muted);border-bottom:2px solid var(--muted);
  transform:rotate(-45deg);transition:transform .18s ease}
details[open] > summary .chev{transform:rotate(45deg)}
details[open] > summary h2{color:var(--ink)}
.secbody{padding:0 0 36px}
.secbody > :first-child{margin-top:0}
.secbody h3:first-child{margin-top:0}

.allbar{display:flex;align-items:center;gap:12px;margin:26px 0 6px}
#toggle-all{font:inherit;font-size:13px;font-weight:600;cursor:pointer;
  color:var(--ink);background:var(--raise);border:1px solid var(--line);
  border-radius:7px;padding:7px 14px}
#toggle-all:hover{border-color:var(--search);color:var(--search)}
.allbar span{font-size:13px;color:var(--muted)}

/* ------------------------------------------------------------ small screens */
/* Written as a max-width block rather than by lowering the base, because the
   desktop reading experience is the one the type scale was set for. */
@media (max-width:639px){
  :root{--gut:16px}
  body{font-size:16px;line-height:1.62}
  .top-in{padding:11px var(--gut);gap:10px}
  .who{font-size:14px;width:100%}
  .who span{display:none}
  .top nav{margin-left:0;width:100%;gap:6px}
  .top nav a{font-size:12.5px;padding:6px 10px;background:var(--paper)}

  h1{font-size:28px;margin:26px 0 10px}
  h2{font-size:22px;margin:40px 0 6px;padding-top:20px}
  h3{font-size:17.5px;margin:26px 0 6px}
  .lede{font-size:17.5px}

  /* The formula is the one block that must not be cut off — it is the answer to
     "show the prioritisation logic". Wrapping beats scrolling here, because a
     reader who does not notice the scroll sees a divided-by with no divisor. */
  .formula{white-space:pre-wrap;word-break:break-word;font-size:12.5px;
    padding:16px 15px;line-height:1.9}

  table{font-size:13.5px}
  th,td{padding:9px 10px}
  .card,.layer{padding:15px 16px}
  .layer{grid-template-columns:auto minmax(0,1fr);gap:12px}
  .stat b{font-size:21px}
  .next a{width:100%}
  :target{scroll-margin-top:112px}
}
/* Between phone and desktop the rail is still hidden, so give the column back
   the space it would have used. */
@media (min-width:640px) and (max-width:1039px){
  .page{max-width:760px}
}

@media print{.top,.rail,.next{display:none}body{font-size:11pt}
  .scroll{background-image:none;overflow:visible}
  h2{break-after:avoid}.layer,.card{break-inside:avoid}}
"""


_H2 = re.compile(r'<h2 id="([\w-]+)">(.*?)</h2>', re.S)


def _accordion(body: str, blurbs: dict, code: str) -> tuple[str, str]:
    """Turn a linear document into collapsed sections, and build the rail from
    the same split.

    Mechanical on purpose. It splits the existing markup on its own `<h2 id>`
    boundaries rather than the content being re-authored into sections by hand,
    so no prose can be dropped in the move — a test asserts the text length
    survives. It also makes the rail and the sections one source of truth; they
    were two lists before, and a rail entry pointing at an id that no longer
    existed was a real possibility.

    The first section is open, because a page of nothing but closed boxes reads
    as an empty page.
    """
    parts = _H2.split(body)
    intro, rest = parts[0], parts[1:]

    out = [intro,
           '<div class="allbar"><button id="toggle-all" type="button" '
           'aria-label="Expand every section">Expand all</button>'
           f'<span>{len(rest) // 3} sections</span></div>']
    rail = []

    for i in range(0, len(rest), 3):
        sid, title, chunk = rest[i], rest[i + 1], rest[i + 2]
        n = i // 3 + 1
        blurb = blurbs.get(sid, "")
        out.append(
            f'<details class="sec"{" open" if n == 1 else ""}>'
            f'<summary>'
            f'<span class="sc">{code}{n}</span>'
            f'<h2 id="{sid}">{title}</h2>'
            + (f'<p class="sb">{blurb}</p>' if blurb else "")
            + '<span class="chev" aria-hidden="true"></span>'
            f'</summary><div class="secbody">{chunk}</div></details>'
        )
        # Strip tags from the heading for the rail: some carry inline markup.
        label = re.sub(r"<[^>]+>", "", title).strip()
        rail.append(f'<a href="#{sid}">{code}{n} &middot; {label}</a>')

    return "".join(out), "".join(rail)


# Opens whatever needs to be open. Three cases, all of which would otherwise
# leave a reader looking at a closed box: following an anchor from the rail or a
# shared link, printing, and clicking "Expand all". Without JS the page still
# works — <details> is native, and every summary carries its own finding.
_JS = """
(function(){
  var secs=document.querySelectorAll('details.sec');
  var btn=document.getElementById('toggle-all');
  function setAll(open){for(var i=0;i<secs.length;i++)secs[i].open=open;}
  if(btn)btn.addEventListener('click',function(){
    var closed=false;
    for(var i=0;i<secs.length;i++)if(!secs[i].open){closed=true;break;}
    setAll(closed);
    btn.textContent=closed?'Collapse all':'Expand all';
  });
  function reveal(){
    var id=location.hash.slice(1);if(!id)return;
    var el=document.getElementById(id);if(!el)return;
    var d=el.closest('details.sec');
    if(d&&!d.open){d.open=true;el.scrollIntoView();}
  }
  window.addEventListener('hashchange',reveal);reveal();
  window.addEventListener('beforeprint',function(){setAll(true);});
})();
"""


def _shell(*, title: str, description: str, current: str, rail: str,
           body: str) -> str:
    """One document skeleton for both pages, so they cannot drift apart."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description)}">
<!-- Shared by link with a named reader, not published to be found. -->
<meta name="robots" content="noindex,nofollow">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(description)}">
<style>{_CSS}</style>
</head>
<body>
<header class="top">
  <div class="top-in">
    <div class="who">Ticmint &mdash; written response <span>&nbsp;Parts C &amp; D</span></div>
    <nav>
      <a href="/work/visibility-agent"{' aria-current="page"' if current == "c" else ""}>Part C &middot; Visibility agent</a>
      <a href="/work/growth-strategy"{' aria-current="page"' if current == "d" else ""}>Part D &middot; Growth strategy</a>
    </nav>
  </div>
</header>
<div class="page">
  <aside class="rail"><b>On this page</b>{rail}</aside>
  <main>{body}</main>
</div>
<footer class="foot">
  Written for the Ticmint exercise. Every factual claim about the live site or the
  live agent is chipped <span class="chip measured">measured</span>; judgement is
  chipped <span class="chip reasoned">reasoned</span>. Part E (proof of work) is
  personal work history and is deliberately not on these pages.
</footer>
<script>{_JS}</script>
</body>
</html>"""


# ----------------------------------------------------------------- Part C
def visibility_agent_page() -> str:
    body = """
<p class="eyebrow">Part C</p>
<h1>The organic visibility agent</h1>
<p class="lede">Search is splitting into three surfaces. They are not three
tactics &mdash; they are three different units of competition, and an agent that
treats them as one will win the cheapest and lose the one that is growing.</p>
<p class="qual">Audited live against <code>ticmint.com</code> before writing.
Findings read off the site are chipped <span class="chip measured">measured</span>;
everything else is <span class="chip reasoned">reasoned</span>.</p>

<h2 id="surfaces">Three surfaces, three units</h2>
<div class="scroll"><table>
<thead><tr><th></th>
<th><span class="s s-search">Search</span></th>
<th><span class="s s-answer">Answer</span></th>
<th><span class="s s-gen">Generative</span></th></tr></thead>
<tbody>
<tr><th>Unit</th><td>A URL</td><td>A passage, a claim</td><td>The brand as an entity</td></tr>
<tr><th>Goal</th><td>Earn a ranked position</td><td>Be the extracted answer</td><td>Be named in a recommendation</td></tr>
<tr><th>Win looks like</th><td>A click</td><td>No click &mdash; the answer sufficed</td><td>Inclusion in a shortlist you did not write</td></tr>
<tr><th>Currency</th><td>Relevance, links, crawlability</td><td>Structure, atomicity, extractability</td><td>Corroboration in sources you do not host</td></tr>
<tr><th>You control</th><td>The page</td><td>The markup and the sentence shape</td><td>Almost nothing directly</td></tr>
<tr><th>Feedback lag</th><td class="num">days</td><td class="num">days&ndash;weeks</td><td class="num">weeks&ndash;months</td></tr>
</tbody></table></div>

<p><strong>SEO</strong> is a competition for a slot. Crawl, index, rank, click.
Unchanged, and it still funds the pipeline today.</p>

<p><strong>AEO</strong> is a competition to be <em>quoted</em>. The winning asset is
not a two-thousand-word page; it is a self-contained, verifiable sentence a machine
can lift without context. &ldquo;Ticmint charges from 2% per ticket&rdquo; survives
extraction. &ldquo;Our pricing is competitive and flexible&rdquo; does not.</p>

<p><strong>GEO</strong> is a competition for reputation in a corpus you do not own.
Asked for the best white-label ticketing platform for an Indian festival, a model is
not ranking pages &mdash; it is reconstructing a consensus from review sites,
listicles, forum threads and training data. The lever is not on-site content.</p>

<div class="note"><strong>The consequence that shapes the whole design:</strong>
on-site work has a ceiling for GEO. Past it, the work is off-site &mdash; review
corpus, listicle inclusion, community threads, entity graph. An agent that only
edits the website will plateau on the surface growing fastest.</div>

<h2 id="audit">Ticmint audit</h2>
<p class="qual">Homepage, <code>robots.txt</code> and sitemap index, read live.</p>

<div class="grid2">
  <div class="stat"><b>345 KB</b><span>homepage HTML <span class="chip measured">measured</span></span></div>
  <div class="stat"><b>90</b><span>&lt;script&gt; tags on the homepage</span></div>
  <div class="stat"><b>5</b><span>JSON-LD types present, incl. FAQPage</span></div>
  <div class="stat"><b>0</b><span>AI crawlers blocked in robots.txt</span></div>
</div>

<h3>What is already right &mdash; do not &ldquo;fix&rdquo; these</h3>
<ul>
<li>The meta description leads with the actual wedge &mdash; <em>white-label, own
your attendee data, fees from 2%, free to start</em>. That is a positioning
sentence, not a keyword string.</li>
<li>Clean single <code>h1</code>; sane tree (1&nbsp;&times;&nbsp;H1,
13&nbsp;&times;&nbsp;H2, 22&nbsp;&times;&nbsp;H3). Self-referencing canonical.</li>
<li><strong>JSON-LD already carries <code>Organization</code>,
<code>WebSite</code>, <code>WebPage</code>, <code>BreadcrumbList</code> and
<code>FAQPage</code>.</strong> The FAQPage is the most valuable
<span class="s s-answer">Answer</span> asset on the site and it exists already.</li>
<li><code>industries</code> and <code>case-studies</code> are separate post types
with their own sitemaps &mdash; the right shape for vertical-specific answers.</li>
<li><strong><code>robots.txt</code> does not block <code>GPTBot</code>,
<code>ClaudeBot</code>, <code>CCBot</code>, <code>PerplexityBot</code> or
<code>Google-Extended</code>.</strong> Many Cloudflare-fronted sites now ship a
managed <code>robots.txt</code> that blocks AI trainers by default, which silently
makes <span class="s s-gen">Generative</span> impossible. Ticmint is eligible.
Protect that setting &mdash; it is one dashboard toggle away from being lost.</li>
</ul>

<h3>Gaps, in priority order</h3>

<h4>1. No <code>SoftwareApplication</code> or <code>Offer</code> schema
<span class="s s-answer">Answer</span></h4>
<p>A SaaS with a public price and no machine-readable representation of it. Answer
engines cannot quote a price they cannot parse. Add <code>SoftwareApplication</code>
+ <code>Offer</code>, and <code>AggregateRating</code> once reviews exist. Cheapest
win available, and it serves the question buyers actually ask.</p>

<h4>2. Index bloat from generated archives <span class="s s-search">Search</span></h4>
<p>The sitemap index exposes <code>author-</code>, <code>date-</code>,
<code>post_tag-</code> and <code>post-archive-</code> sitemaps. On a small corpus
these are thin near-duplicates that dilute crawl budget and compete with the pages
that matter. <code>noindex</code> them; drop them from the index.</p>

<h4>3. Elementor weight is an extraction problem, not only a speed one
<span class="s s-answer">Answer</span></h4>
<p>345&nbsp;KB and 90 scripts is an LCP and INP risk. The sharper issue: Elementor
nests copy inside deep <code>div</code> scaffolding, and extraction favours clean
semantic blocks. For answer-critical pages &mdash; comparisons, pricing, FAQ,
industries &mdash; use a lean template with real <code>table</code>,
<code>dl</code>, and a heading followed by one self-contained paragraph.</p>

<h4>4. The comparison surface is the commercial gap
<span class="s s-search">Search</span> <span class="s s-answer">Answer</span>
<span class="s s-gen">Generative</span></h4>
<p>This category is bought comparatively: <em>Eventbrite alternative</em>,
<em>white label ticketing software</em>, <em>BookMyShow alternative for
organisers</em>. Those strings are simultaneously high-intent search, ideal
structured-answer material, and the literal prompts that feed generative
recommendations. One asset class, three surfaces. Build it per competitor and per
vertical &mdash; it is the highest-leverage content decision on the list.</p>

<h4>5. The generative substrate barely exists &mdash; and that is the opportunity
<span class="s s-gen">Generative</span></h4>
<p>Checked across the event-ticketing set: <strong>only Eventbrite has a verified
G2 product presence.</strong> BookMyShow, Townscript, Explara, MeraEvents, Paytm
Insider, Zoho Backstage, Ticketmaster and Ticket Tailor have no verified slug.
The third-party corpus a model would reconstruct a recommendation from is close to
empty. That is an unclaimed default answer: whoever becomes the best-documented
option on review sites, in listicles and in organiser communities becomes the name
these systems return, cheaply, for years.</p>
<div class="note"><strong>Method caveat</strong>
<span class="chip reasoned">reasoned</span> &mdash; G2 returned
<code>403</code> to my server for <em>every</em> product path, including one that
certainly exists. So the absence of a <em>verified slug</em> is established; the
absence of a <em>page</em> is inferred, not measured. Stating this is the
difference between a finding and a guess.</div>

<h4>6. No <code>llms.txt</code></h4>
<p>Low cost, uncertain payoff, real option value. A plain-language map of what
Ticmint is, who it serves, and its factual claims.</p>

<h2 id="agent">The agent &mdash; what it reads</h2>
<div class="scroll"><table>
<thead><tr><th>Source</th><th>Signal</th><th>Why it is in the loop</th></tr></thead>
<tbody>
<tr><td><strong>Search Console</strong></td><td>Query, impressions, position, CTR</td><td>The only first-party view of demand</td></tr>
<tr><td><strong>Server / edge logs</strong></td><td>Hits by <code>GPTBot</code>, <code>ClaudeBot</code>, <code>PerplexityBot</code>, <code>OAI-SearchBot</code></td><td>Retrieval evidence. Owned, free, unambiguous &mdash; and the layer nobody instruments</td></tr>
<tr><td><strong>SERP API</strong></td><td>Rank <em>and feature presence</em>: AI Overview, PAA, snippet owner</td><td>Feature presence matters more than position now</td></tr>
<tr><td><strong>Prompt panel</strong></td><td>Versioned ICP prompts &times; engines &times; repeats: mentioned, rank in list, sentiment, cited source</td><td>The only instrument that sees the generative surface at all</td></tr>
<tr><td><strong>Third-party corpus</strong></td><td>G2 / Capterra / Trustpilot volume and recency, Reddit threads, listicle inclusion, Wikidata entity</td><td>Where generative consensus is actually formed</td></tr>
<tr><td><strong>CRM + GA4</strong></td><td>Page &rarr; demo &rarr; pipeline, and self-reported source</td><td>Ties visibility to money</td></tr>
<tr><td><strong>Competitor set</strong></td><td>All of the above, for 6&ndash;9 rivals</td><td>Share is the metric; absolute counts mislead</td></tr>
</tbody></table></div>

<h2 id="priority">How it decides what to do next</h2>
<p>Not a backlog. A score recomputed weekly, and a capacity policy that stops it
over-fitting to what already works.</p>

<div class="formula">              Demand &times; Winnability &times; SurfaceLeverage &times; CommercialProximity
Priority =  &mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;&mdash;
                                  CostToProduce</div>

<div class="scroll"><table>
<thead><tr><th>Term</th><th>What it is</th><th>Why it exists</th></tr></thead>
<tbody>
<tr><td>Demand</td><td>Query volume <em>plus prompt frequency</em></td><td>How often the ICP asks beats how often the keyword is typed</td></tr>
<tr><td>Winnability</td><td>Our gap to the weakest incumbent, adjusted for their authority</td><td>Stops it attacking Eventbrite&rsquo;s strongest terms first</td></tr>
<tr><td>SurfaceLeverage</td><td>How many of the three surfaces one asset serves (1&ndash;3&times;)</td><td>A comparison table with FAQ schema and a review-site counterpart is worth 3&times; a blog post</td></tr>
<tr><td>CommercialProximity</td><td>Distance to a demo (BOFU 3&times;, MOFU 2&times;, TOFU 1&times;)</td><td>Prevents a traffic-maximising agent</td></tr>
<tr><td>CostToProduce</td><td>refresh &lt; schema patch &lt; new page &lt; off-site placement</td><td>Cheap reversible work should win ties</td></tr>
</tbody></table></div>

<h3>Capacity policy &mdash; the part that keeps it honest</h3>
<div class="grid2">
  <div class="stat"><b>70%</b><span>Exploit &mdash; highest-scoring unblocked work</span></div>
  <div class="stat"><b>20%</b><span>Maintain &mdash; assets losing position, mentions or citation share</span></div>
</div>
<div class="stat" style="margin:0 0 20px"><b>10%</b><span>Explore &mdash; deliberately low-confidence new query and prompt space</span></div>
<p>Without the reserved 10% it converges on what already works and goes blind to a
shifting category. Without the 20% it publishes new pages while old ones rot
&mdash; and decay defence is usually the higher actual return.</p>

<h3>What it produces</h3>
<ul>
<li>Briefs and drafts &mdash; comparisons, industry pages, definitions, FAQ blocks written to be extractable</li>
<li>Schema patches as diffs &mdash; <code>SoftwareApplication</code>, <code>Offer</code>, <code>FAQPage</code>, <code>HowTo</code></li>
<li>Technical fixes &mdash; internal links, <code>noindex</code> on archives, sitemap hygiene, semantic-template conversions</li>
<li><strong>Off-site work orders</strong> &mdash; which customer to ask for which review on which platform, listicle outreach lists, community threads worth a real answer. This is what makes it a generative-surface agent rather than a content tool</li>
<li>Entity hygiene &mdash; Wikidata, <code>sameAs</code>, NAP consistency</li>
<li>A weekly diff: what moved, what it attributes that to, what it wants permission for</li>
</ul>

<h3>Where the human sits</h3>
<div class="scroll"><table>
<thead><tr><th>Gate</th><th>Why exactly here</th></tr></thead>
<tbody>
<tr><td>Any factual or <strong>pricing</strong> claim</td><td>A wrong price gets quoted back by a prospect. That is a trust event, not a typo</td></tr>
<tr><td>Any <strong>named competitor</strong> comparison</td><td>Comparative claims must be defensible</td></tr>
<tr><td>Any <strong>customer</strong> name or result</td><td>Contractual and relationship risk</td></tr>
<tr><td>New page on a <strong>commercial template</strong></td><td>Cannibalisation and voice on the pages that carry revenue</td></tr>
<tr><td><strong>Sitewide directives</strong> &mdash; canonical, robots, schema template</td><td>Blast radius: one bad rule deindexes the site</td></tr>
</tbody></table></div>
<div class="note"><strong>The principle:</strong> humans sit where the mistake is
irreversible or where it is a judgement about risk &mdash; not at &ldquo;is this
good writing&rdquo;. That is what the agent is for, and a human reading every draft
is the bottleneck that kills the programme.</div>

<h2 id="publishing">Would I let it publish unattended?</h2>
<p>Partly. And the line is not about quality &mdash; modern drafts are fine. The
line is <strong>reversibility &times; claim risk</strong>.</p>

<div class="grid2">
<div class="card"><h4>Yes, unattended</h4>
<ul>
<li>Refreshes that change no factual claim</li>
<li>Meta titles and descriptions</li>
<li>Schema on already-approved facts</li>
<li>Glossary pages from an approved fact base</li>
<li>Technical hygiene &mdash; <code>noindex</code>, sitemaps, internal links</li>
</ul></div>
<div class="card"><h4>No, human-gated</h4>
<ul>
<li>Any price, fee, SLA or compliance fact</li>
<li>Any page naming a competitor comparatively</li>
<li>Anything citing a customer or a result</li>
<li>Net-new pages on commercial templates</li>
<li><strong>Anything that generates a statistic</strong></li>
</ul></div>
</div>

<h3>What has to be true before I move the line</h3>
<div class="layers">
<div class="layer"><div class="n">1</div><div><h4>Claim provenance</h4>
<p>Every factual sentence traceable to a record in an approved store. No source, no
sentence &mdash; enforced at generation, not at review.</p></div></div>
<div class="layer"><div class="n">2</div><div><h4>Blocking pre-publish gates</h4>
<p>Unsourced-number detector, embedding similarity against the existing corpus,
plagiarism, brand-voice classifier, schema validation, internal-link sanity.</p></div></div>
<div class="layer"><div class="n">3</div><div><h4>A track record with a denominator</h4>
<p>Two quarters, at least a hundred reviewed drafts, factual correction rate under
a pre-agreed threshold. Measured on the gated flow <em>before</em> trusting the
ungated one.</p></div></div>
<div class="layer"><div class="n">4</div><div><h4>Instant rollback</h4>
<p>Content in version control, one-command revert, an alert when a live page
changes.</p></div></div>
<div class="layer"><div class="n">5</div><div><h4>Staged publish</h4>
<p>New pages go live <code>noindex</code>, get sampled, then get indexed. Turns a
publishing mistake into a private one.</p></div></div>
</div>
<p>Given those five I would move non-commercial pages to unattended, and keep
pricing, competitor and customer claims gated permanently. I do not expect to move
that last gate: the cost is asymmetric and the throughput gain is small.</p>

<h3>Damage, and how fast I would know</h3>
<div class="scroll"><table>
<thead><tr><th>Failure</th><th>Damage</th><th>Detected in</th></tr></thead>
<tbody>
<tr><td>Broken schema, canonical or <code>noindex</code> at template level</td><td>Deindexing, traffic collapse</td><td class="num">hours</td></tr>
<tr><td>Fabricated statistic or feature</td><td>Trust, legal, contradicted by sales</td><td class="num">days&ndash;weeks</td></tr>
<tr><td>Cannibalisation, index bloat</td><td>Existing rankings decay</td><td class="num">2&ndash;6 weeks</td></tr>
<tr><td><strong>Wrong claim ingested into model corpora</strong></td><td>Answer engines repeat it; no rollback exists</td><td class="num">months</td></tr>
<tr><td>Voice drift at volume</td><td>Slow credibility loss with a small expert audience</td><td class="num">months</td></tr>
</tbody></table></div>
<p>That table <em>is</em> the argument for where the line sits. The fast failures
can be automated away. The slow ones cannot &mdash; and they are the ones that
touch claims.</p>

<h2 id="measure">Measurement</h2>
<p class="lede">There is no rank in an answer engine, often no click, no referrer,
nothing in GA4. So stop measuring rank. Measure presence, eligibility, and demand
transfer &mdash; three layers, three different instruments.</p>

<div class="layers">
<div class="layer"><div class="n">L1</div><div>
<h4>Presence &mdash; does the machine name us? <span class="s s-gen">Generative</span></h4>
<p><strong>Share of Model Voice.</strong> A versioned panel of 60&ndash;150 prompts
in real ICP language, run weekly across ChatGPT, Perplexity, Gemini, Claude and AI
Overviews. Each prompt run <strong>k&nbsp;&ge;&nbsp;5 times</strong> &mdash; these
systems are non-deterministic, so a single run is anecdote. Report a mention
<em>rate with a confidence interval</em>, never a binary.</p>
<p>Parsed per response: mentioned, <strong>rank within the list</strong>, sentiment,
and <strong>which source was cited</strong>. Every raw response stored &mdash; when
the number moves you must be able to read what changed.</p>
<p class="qual">Discipline: the panel is <strong>frozen and versioned</strong>
&mdash; editing it silently manufactures an improvement. And a
<strong>control set</strong> of prompts you never work on, or you cannot separate
your effect from category drift.</p>
</div></div>

<div class="layer"><div class="n">L2</div><div>
<h4>Eligibility &mdash; can they retrieve us? <span class="s s-answer">Answer</span></h4>
<p>The layer people skip, and the only one that is fully owned, free and
unambiguous: your own logs.</p>
<ul>
<li>AI crawler hits by bot, by URL, by week</li>
<li>Coverage: share of priority URLs fetched by any AI agent in 30 days</li>
<li><strong>Errors served to AI agents</strong> &mdash; 4xx, 5xx, WAF challenges. A
bot rule quietly 403-ing a crawler is a total generative outage with no symptom
anywhere else. I have hit exactly this pattern live: a Cloudflare-fronted host
returning 403 to one client class while serving browsers normally
<span class="chip measured">measured</span></li>
<li>Plus snippet and PAA ownership, and impressions on AI-Overview-eligible queries</li>
</ul>
<p>Crawl precedes citation, so L2 leads L1.</p>
</div></div>

<div class="layer"><div class="n">L3</div><div>
<h4>Demand transfer &mdash; does it produce business?</h4>
<ul>
<li><strong>Branded search volume trend</strong> &mdash; the best single proxy for
zero-click influence. Described well, people search your name</li>
<li><strong>Self-reported attribution on the demo form</strong>, required, with an
&ldquo;AI assistant / ChatGPT&rdquo; option. Cheap, unfashionable, and the highest-signal
instrument available for dark traffic. The number I would defend hardest</li>
<li>Direct and no-referrer sessions landing on commercial pages, correlated against
SoMV movement</li>
<li>True LLM referrals where they exist</li>
<li>Pipeline: demos, SQLs and pilots where self-report is AI or organic &mdash; and
win rate against other sources</li>
</ul>
</div></div>
</div>

<h3>Cadence</h3>
<div class="scroll"><table>
<thead><tr><th>Instrument</th><th>Frequency</th><th>Why that interval</th></tr></thead>
<tbody>
<tr><td>AI crawler logs</td><td><strong>Daily</strong></td><td>Free, and catches an outage same day</td></tr>
<tr><td>Search Console, SERP features</td><td>Weekly</td><td>Matches data latency</td></tr>
<tr><td>Prompt panel / SoMV</td><td>Weekly</td><td>Cost and variance &mdash; k repeats make daily wasteful</td></tr>
<tr><td>Branded search</td><td>Monthly</td><td>Too noisy weekly</td></tr>
<tr><td>Self-report and pipeline</td><td>Continuous, reviewed monthly</td><td>Cohorts need time</td></tr>
<tr><td>Full audit, competitive SoMV</td><td>Quarterly</td><td>Strategy cadence</td></tr>
</tbody></table></div>

<h2 id="kill">What number shuts it down</h2>
<p>No single metric can carry this, because honest payback is two to four quarters.
So: one compound stop-condition, and two switches that do not wait for it.</p>

<div class="card"><h4>Compound &mdash; evaluated at end of quarter two, all four must hold</h4>
<ol>
<li>SoMV on the priority panel has not moved beyond the control set&rsquo;s drift</li>
<li>and branded search is flat or declining</li>
<li>and zero pilots sourced with AI or organic self-report</li>
<li>and cost per published asset exceeds the CAC-justified ceiling for the ICP</li>
</ol>
<p>All four true &rarr; shut it down. That is not a slow market, that is a wrong
thesis.</p></div>

<div class="note stop"><strong>Immediate, no debate:</strong> a manual action or
measurable deindexing traceable to agent output &mdash; or a factual error rate
above 2% on a sampled audit, because that damage compounds into corpora and cannot
be rolled back.</div>

<div class="note ok"><strong>And a de-scope trigger short of shutdown:</strong> if
L2 is healthy but L3 is flat, the agent is working and the <em>positioning</em> is
wrong. Fix the message; do not kill the channel. Being able to tell those two apart
is the entire reason for measuring in three layers.</div>

<h2 id="failure">The three failure modes that worry me</h2>

<div class="layers">
<div class="layer"><div class="n">01</div><div>
<h4>Confident fabrication at scale</h4>
<p>An invented statistic, a competitor&rsquo;s fee, a feature that does not exist.
At one page a week a human catches it; at forty it ships. And a wrong fact can be
ingested and repeated by answer engines long after correction &mdash; the one
failure with no clean rollback.</p>
<p><strong>Catch it with:</strong> provenance as a generation constraint, a blocking
unsourced-number gate, a monitor that re-checks live claims against the
source-of-truth weekly, and a monthly sampled audit whose
<strong>correction rate is published as a headline metric</strong>. A quality
control nobody sees is not a control.</p>
</div></div>

<div class="layer"><div class="n">02</div><div>
<h4>Goodharting the new metric</h4>
<p>SoMV is young and easy to game &mdash; including accidentally, by the agent
itself. It can win mentions on easy irrelevant prompts. The number rises and the
business does not move.</p>
<p><strong>Catch it with:</strong> a panel weighted by ICP-verified language taken
from sales calls, the control set, commercial-proximity weighting &mdash; and a
<strong>divergence alarm: mention rate rising while demo self-report stays flat for
two consecutive months.</strong> That specific divergence is this failure&rsquo;s
signature, and it is invisible if you only watch the channel metric.</p>
</div></div>

<div class="layer"><div class="n">03</div><div>
<h4>Cannibalisation and index bloat</h4>
<p>The fastest way to lose the rankings you have is to publish forty pages that
compete with the twelve that work. Ticmint is already exposed: author, date and tag
archives sit in the sitemap index on a small corpus
<span class="chip measured">measured</span>.</p>
<p><strong>Catch it with:</strong> a pre-publish embedding-similarity check that
blocks above a threshold and proposes refreshing the incumbent instead, a query-overlap
monitor for two URLs trading impressions, and a <strong>net-URL budget</strong> per
quarter so growth is a decision rather than a side effect.</p>
</div></div>
</div>

<p class="qual"><strong>Honourable mention &mdash; platform dependency.</strong>
Engines can change citation behaviour, block crawlers, or strike licensing deals.
Not defensible, only diversifiable: keep the substrate spread across third-party
corpora no single vendor&rsquo;s policy change can erase.</p>

<div class="next">
  <a href="/work/growth-strategy"><small>Next</small>Part D &middot; Growth strategy &rarr;</a>
</div>
"""
    # Each blurb carries the section's finding, not a restatement of its title.
    # It is the mitigation for the one real cost of collapsing a submission: a
    # reader who never opens a section should still take the argument away.
    blurbs = {
        "surfaces": "Three units of competition, not three tactics — a URL, a claim, an entity. Each fails differently.",
        "audit": "Schema and AI-crawler access are already right. Six gaps; the biggest is a SaaS with a public price and no price schema.",
        "agent": "Seven sources — including the one nobody instruments: AI crawler hits in your own server logs.",
        "priority": "A scoring function, plus a 70/20/10 capacity policy so it cannot over-fit to whatever already works.",
        "publishing": "Yes for reversible work, never for claims. The line is reversibility × claim risk, not writing quality.",
        "measure": "Presence, eligibility, demand transfer — because rank does not exist here and GA4 sees nothing.",
        "kill": "One compound stop-condition, and two switches that do not wait for it.",
        "failure": "Fabrication at scale, Goodharting the new metric, and cannibalisation from volume.",
    }
    body_html, rail = _accordion(body, blurbs, "C")
    return _shell(
        title="Part C — The Organic Visibility Agent | Ticmint",
        description=("How one agent owns ranked search, answer engines and "
                     "generative recommendation for Ticmint — with a live audit, "
                     "prioritisation logic, and measurement that works when "
                     "nothing lands in GA4."),
        current="c", rail=rail, body=body_html,
    )


# ----------------------------------------------------------------- Part D
def growth_strategy_page() -> str:
    body = """
<p class="eyebrow">Part D</p>
<h1>Growth strategy</h1>
<p class="lede">One repeatable motion into a market you can enumerate, plus one
compounding asset. Nothing whose feedback loop is longer than the runway.</p>

<h2 id="icp">Segmenting a white-label ticketing market</h2>
<p>Split on the two things that decide the deal: <strong>who owns the audience</strong>
and <strong>who carries the risk</strong>.</p>

<div class="scroll"><table>
<thead><tr><th></th><th>Segment</th><th class="num">Volume</th><th class="num">ACV</th><th class="num">Cycle</th><th>Verdict</th></tr></thead>
<tbody>
<tr><td class="num">1</td><td>Independent creators, small promoters</td><td>very high</td><td>very low</td><td>days</td><td>Self-serve. CAC unrecoverable</td></tr>
<tr><td class="num">2</td><td><strong>Mid-market promoters &amp; festival operators</strong></td><td>medium</td><td>med&ndash;high</td><td><strong>2&ndash;8 wks</strong></td><td><strong>Primary</strong></td></tr>
<tr><td class="num">3</td><td>Venues, stadium operators</td><td>low</td><td>high</td><td>3&ndash;6 mo</td><td>Integration-heavy</td></tr>
<tr><td class="num">4</td><td><strong>Sports federations &amp; leagues</strong></td><td>very low</td><td>very high</td><td><strong>3&ndash;9 mo</strong></td><td><strong>Secondary</strong></td></tr>
<tr><td class="num">5</td><td>Conference &amp; association organisers</td><td>medium</td><td>medium</td><td>1&ndash;3 mo</td><td>Data-hungry, later</td></tr>
<tr><td class="num">6</td><td>Agencies, white-label resellers</td><td>low</td><td>medium</td><td>1&ndash;2 mo</td><td>Channel, not ICP</td></tr>
<tr><td class="num">7</td><td>Enterprise brands, owned experiences</td><td>low</td><td>high</td><td>3&ndash;6 mo</td><td>Procurement-led</td></tr>
</tbody></table></div>

<h2 id="primary">Primary &mdash; mid-market promoters &amp; festival operators</h2>
<p><strong>Profile.</strong> 10&ndash;100 ticketed events a year, real ticket
revenue, India and comparable emerging markets. Small team, no in-house
engineering, already paying platform fees on real volume.</p>

<div class="scroll"><table>
<thead><tr><th>Why primary</th><th></th></tr></thead>
<tbody>
<tr><td><strong>Urgency</strong></td><td>The pain is a line item. The gap between ~2% and ~6&ndash;8% take rate on real GTV is money they can compute in their head &mdash; and the site already leads with &ldquo;fees from 2%&rdquo;</td></tr>
<tr><td><strong>Budget</strong></td><td>Already exists. Displacement of current spend, not a new line to justify. Shortest path to a yes</td></tr>
<tr><td><strong>Cycle</strong></td><td>2&ndash;8 weeks. Fast enough to learn from, slow enough to be real</td></tr>
<tr><td><strong>Expansion</strong></td><td>Grows with their event calendar without new sales effort; upsells into white-label app, attendee CRM, data</td></tr>
</tbody></table></div>

<h3>Buyer roles</h3>
<div class="scroll"><table>
<thead><tr><th>Role</th><th>Cares about</th><th>Function in the deal</th></tr></thead>
<tbody>
<tr><td>Founder / promoter</td><td>Fees, payout timing, cash flow</td><td>Economic buyer</td></tr>
<tr><td>Head of marketing</td><td><strong>Owning attendee data</strong>, brand at checkout</td><td>Champion &mdash; the emotional trigger lives here</td></tr>
<tr><td>Ops / box office</td><td>Check-in, scanning, refunds, on-site reality</td><td>Blocker if ignored</td></tr>
<tr><td>Finance</td><td>Settlement, reconciliation, compliance</td><td>Late-stage gate</td></tr>
</tbody></table></div>

<h3>Core pain, in their words</h3>
<p>The incumbent owns the audience. The brand disappears at checkout. Payouts arrive
late. And the platform markets competing events to the list they built.</p>

<h3>What actually triggers a decision</h3>
<p>Not interest &mdash; an event:</p>
<ol>
<li>A payout that arrived late or short, on an event with real cash exposure</li>
<li>Discovering the incumbent marketed a rival event to their own attendees</li>
<li>A new season, tour or festival edition being announced &mdash; a natural switch point</li>
<li>Contract renewal, or a fee increase</li>
<li>Scaling past the point the current tool breaks &mdash; multi-day, multi-venue, tiered</li>
</ol>
<div class="note"><strong>Trigger 3 is the operational one:</strong> nobody switches
ticketing mid-season. In this segment timing beats persuasion, which is why the CRM
re-engagement date matters more than another sequence.</div>

<h2 id="secondary">Secondary &mdash; federations, leagues &amp; venues</h2>
<p>Higher ACV and logo value, but RFP-driven with a 3&ndash;9 month cycle and
several veto-holders. As a primary motion it would starve the pipeline for two
quarters. As a secondary it is the right shape, because
<strong>its case studies are the highest-value trust and generative-surface assets
for the primary motion</strong>. Federation credibility sells to mid-market
promoters; the reverse is not true.</p>
<p><strong>Roles:</strong> commercial director (economic), CTO or IT (integration),
data protection (first-party obligations), finance (settlement).
<strong>Triggers:</strong> season start, sponsorship commitments requiring
first-party attendee data, incumbent contract expiry, a public failure &mdash; a
queue collapse or a refund scandal.</p>
<p class="qual"><strong>Explicitly not an ICP:</strong> independent creators. Keep
the free tier &mdash; it is a useful funnel feeder and a source of product signal
&mdash; but spend no acquisition money there. Signups are not the business.</p>

<h2 id="channels">Channels &mdash; and the cut</h2>
<p class="qual">Available: organic across the three surfaces &middot; outbound
(email, LinkedIn, WhatsApp) &middot; paid search &middot; paid social &middot;
review sites &middot; partnerships (payment gateways, agencies, venues) &middot;
industry events &middot; communities &middot; PR &middot; referral &middot; ABM
&middot; product-led free tier.</p>

<div class="layers">
<div class="layer"><div class="n">01</div><div>
<h4>Signal-qualified outbound &mdash; job: <strong>pipeline</strong></h4>
<p>This ICP is <em>enumerable</em>. Promoters advertise their events publicly, and
the incumbent platform is detectable from the event page. You can build a list of
companies who verifiably run ticketed events on a named competitor &mdash; targeting
on evidence, not on a job-title filter.</p>
<p><strong>90 days:</strong> a repeatable list &rarr; contact &rarr; conversation
loop, a benchmarked reply and meeting rate per segment, and at least one paid pilot
event booked. A validated message matters more than pipeline value.</p>
</div></div>

<div class="layer"><div class="n">02</div><div>
<h4>Comparison-led organic &mdash; job: <strong>trust &rarr; pipeline</strong></h4>
<p>The category is bought comparatively, and one asset class &mdash; competitor
comparisons, per-vertical industry pages, a fee calculator &mdash; serves ranked
search, structured answers and generative recommendation simultaneously. It is also
the only channel that touches the generative surface at all.</p>
<p><strong>90 days:</strong> comparison and industry pages on a lean semantic
template, <code>SoftwareApplication</code> and <code>Offer</code> schema live,
archive bloat cleaned, and a <strong>SoMV baseline established</strong> &mdash; the
baseline is itself a deliverable.</p>
</div></div>

<div class="layer"><div class="n">03</div><div>
<h4>Review sites &amp; communities &mdash; job: <strong>trust, and substrate</strong></h4>
<p>The highest-leverage cheap move, and the reason is measured: among the
event-ticketing set, <strong>only Eventbrite has a verified G2 presence</strong>
<span class="chip measured">measured</span>. The corpus generative engines
reconstruct a recommendation from barely exists. An unclaimed corpus is an
unclaimed default answer.</p>
<p><strong>90 days:</strong> verified reviews past the display threshold on
G2, Capterra and Trustpilot, inclusion in a target list of
&ldquo;best white-label ticketing&rdquo; listicles, and genuine presence in two or
three organiser communities.</p>
</div></div>
</div>

<h2 id="notdoing">What I am explicitly not doing</h2>
<div class="scroll"><table>
<thead><tr><th>Not doing</th><th>Why</th></tr></thead>
<tbody>
<tr><td><strong>Paid search at scale</strong></td><td>The keyword space is polluted by consumer <em>ticket-buying</em> intent. &ldquo;Buy tickets&rdquo; and &ldquo;ticketing platform&rdquo; bring attendees, not organisers, and CPCs are bid up by an audience that will never convert. Keep a small budget as a keyword-validation instrument only</td></tr>
<tr><td><strong>Paid social, brand awareness</strong></td><td>No trigger, and a small enumerable ICP. Outbound reaches the same companies for less, with a reply you can learn from</td></tr>
<tr><td><strong>Sponsorships and industry events</strong></td><td>Real in this category, but high cash and slow feedback. Right after the ICP is proven; wrong while the message is a hypothesis</td></tr>
<tr><td><strong>PLG optimisation of the free tier</strong></td><td>Keep it, do not invest. It produces signal, not revenue, and optimising it would flatter the wrong metric</td></tr>
<tr><td><strong>Enterprise ABM as a primary motion</strong></td><td>Cycle too long to carry two quarters. Runs as secondary, sales-led</td></tr>
</tbody></table></div>

<h2 id="outbound">Cold outreach to organisers who are already frustrated</h2>
<p>The motion is built on the observation that dissatisfaction is
<em>discoverable</em>. Organisers complain in public &mdash; in reviews, in
communities, in threads about held payouts. That gives you the two halves of an
outbound message that is not guesswork: <strong>who is on a competitor</strong>, and
<strong>what specifically annoys people about it</strong>.</p>

<h3>Sequence &mdash; 6&ndash;7 touches over 18&ndash;21 days</h3>
<div class="scroll"><table>
<thead><tr><th class="num">#</th><th class="num">Day</th><th>Channel</th><th>Job of the touch</th></tr></thead>
<tbody>
<tr><td class="num">1</td><td class="num">0</td><td>Email</td><td>Observed trigger, one-line hypothesis, soft ask</td></tr>
<tr><td class="num">2</td><td class="num">2</td><td>LinkedIn</td><td>Profile view and connect. No pitch</td></tr>
<tr><td class="num">3</td><td class="num">4</td><td>Email</td><td>Proof &mdash; same vertical, same region</td></tr>
<tr><td class="num">4</td><td class="num">8</td><td>Email</td><td>Fee comparison run on <em>their</em> volume</td></tr>
<tr><td class="num">5</td><td class="num">12</td><td>LinkedIn DM</td><td>Short, references the asset</td></tr>
<tr><td class="num">6</td><td class="num">16</td><td>WhatsApp</td><td>Where appropriate and reachable &mdash; the normal business channel for Indian mid-market. Consent-aware</td></tr>
<tr><td class="num">7</td><td class="num">21</td><td>Email</td><td>Break-up, leaves the asset behind</td></tr>
</tbody></table></div>

<h3>Worth contacting versus worth ignoring</h3>
<div class="grid2">
<div class="card"><h4>Contact &mdash; all four</h4>
<ul>
<li>Verified ticketed event activity in the last 90 days &mdash; evidence, not a firmographic guess</li>
<li>Detectable incumbent platform &mdash; gives you the fee delta and the switch story</li>
<li>A named human who owns audience or revenue</li>
<li>Volume above the floor where the fee delta is material money</li>
</ul></div>
<div class="card"><h4>Ignore</h4>
<ul>
<li>One event a year, or free events with no ticket revenue</li>
<li>Resellers of someone else&rsquo;s inventory</li>
<li>No named contact &mdash; a generic inbox is not a lead</li>
<li>Suppression list, or a known multi-year exclusive</li>
<li>Anything where the &ldquo;evidence&rdquo; is an inference, not a stored fact</li>
</ul></div>
</div>

<h3>Personalisation at volume, without mail-merge theatre</h3>
<p>The rule: <strong>personalise the observation, never the adjective.</strong>
&ldquo;I saw you&rsquo;re doing great work&rdquo; is theatre. &ldquo;Your last three
events sold through [incumbent]; your checkout hands your attendee list to
them&rdquo; is an observation.</p>

<div class="scroll"><table>
<thead><tr><th>Tier</th><th class="num">Volume</th><th>Personalisation</th><th>Source</th></tr></thead>
<tbody>
<tr><td><strong>T1</strong></td><td class="num">~50</td><td>Human-written first line from a real artefact &mdash; their checkout flow, a review complaint, a payout thread</td><td>Human research</td></tr>
<tr><td><strong>T2</strong></td><td class="num">~500</td><td>Agent-written line grounded in <strong>one stored evidence row</strong>: the platform plus the specific complaint category</td><td>Agent, gated</td></tr>
<tr><td><strong>T3</strong></td><td class="num">rest</td><td>Segment relevance only &mdash; vertical, region, platform. <strong>No fake personalisation</strong></td><td>Templated, honest</td></tr>
</tbody></table></div>

<div class="note stop"><strong>The gate that prevents theatre:</strong> no stored
evidence row, no personalised line. The lead drops to T3 or is skipped. Never let a
model invent the specific detail &mdash; an invented specific is worse than an
honest generic, because it is falsifiable and the prospect will falsify it.</div>

<h2 id="agent">How this connects to the agent</h2>
<p>The agent from Part A is the qualification engine. Described with its real
limits rather than its brochure, because the limits are what shaped the motion.</p>

<div class="grid2">
<div class="card"><h4>What it does well</h4>
<ul>
<li><strong>Discovery from competitor organiser sitemaps.</strong> A company listed there is a <em>verified install</em> &mdash; the strongest cheap targeting signal in this category, free and robots-permitted</li>
<li>Resolution and enrichment: name &rarr; domain &rarr; firmographics, headcount, industry, phone</li>
<li>Complaint classification across the review corpus, producing the message angle &mdash; high fees, limited customisation, payout delay</li>
<li>Complaint-keyed drafting: an opener that speaks to the specific pattern</li>
</ul></div>
<div class="card"><h4>The limitation that matters</h4>
<p><strong>Review signals cannot be used for targeting.</strong> G2 and Trustpilot
publish no employer and no domain, and trim the surname to an initial.</p>
<p>Measured on live data: of 50 collected signals, the 29 review rows matched
<strong>zero</strong> companies; all 14 organiser-install rows matched
<span class="chip measured">measured</span>. Reviewer identity resolution also needs
paid people endpoints that return <code>403</code> on a free plan.</p>
</div>
</div>

<div class="grid2">
  <div class="stat"><b>29 &rarr; 0</b><span>review signals &rarr; companies matched</span></div>
  <div class="stat"><b>14 &rarr; 14</b><span>install signals &rarr; companies matched</span></div>
</div>

<div class="note ok"><strong>So the division of labour is:</strong> install signals
do the <em>targeting</em>, review signals do the <em>messaging</em>. Conflating them
builds a pipeline of unreachable rows. That distinction came from running the
thing, not from designing it.</div>

<h3>What I measure, and what kills it</h3>
<div class="scroll"><table>
<thead><tr><th>Metric</th><th>What it tells me</th></tr></thead>
<tbody>
<tr><td>Contact &rarr; reply, by segment and message</td><td>The message test</td></tr>
<tr><td>Reply &rarr; meeting</td><td>Qualification quality</td></tr>
<tr><td>Meeting &rarr; SQL / pilot</td><td>Whether the ICP is right</td></tr>
<tr><td>Cost per meeting</td><td>Motion viability</td></tr>
<tr><td>Bounce, spam complaint, unsubscribe</td><td>Domain survival</td></tr>
</tbody></table></div>

<div class="note stop"><strong>Immediate kill:</strong> bounce above 5% or spam
complaints above 0.1% &mdash; pause everything. Domain reputation is slow to detect
and expensive to undo.<br>
<strong>Message-level kill:</strong> after ~300 contacted accounts in a segment with
two message iterations, if reply is below benchmark and meetings are near zero, kill
<em>that segment or message</em> &mdash; not the channel. Most
&ldquo;outbound doesn&rsquo;t work&rdquo; conclusions are a message conclusion
misattributed to a channel.</div>

<h3>Tools</h3>
<p>The Part A agent for discovery, enrichment, classification and drafting &middot;
Apollo for firmographics, with the free-tier limits above &middot; Instantly or
Smartlead for sending, inbox rotation and warm-up &middot; HubSpot as CRM and the
source of truth for self-reported attribution &middot; n8n for orchestration
&middot; WhatsApp Business API &mdash; and the unglamorous prerequisite:
<strong>SPF, DKIM and DMARC on a separate sending subdomain</strong>, so outbound
cannot damage the primary domain.</p>

<h2 id="funnel">Funnel</h2>
<div class="layers">
<div class="layer"><div class="n">TOFU</div><div>
<h4>Getting found by organisers, not ticket buyers</h4>
<p><strong>Channels:</strong> the three organic surfaces, review sites, communities,
referral, PR. <strong>Action that matters:</strong> an <em>organiser</em> reaching a
commercial page &mdash; or asking an answer engine and seeing Ticmint named.
<strong>Metric:</strong> qualified new-visitor sessions on commercial pages; SoMV.</p>
<p><strong>Drop-off risk &mdash; audience pollution.</strong> This category shares
its vocabulary with consumers buying tickets. You can triple traffic and add zero
pipeline. Judge TOFU by page-level conversion, never volume.</p>
</div></div>

<div class="layer"><div class="n">MOFU</div><div>
<h4>Self-qualification</h4>
<p><strong>Channels:</strong> comparison pages, fee calculator, vertical case
studies, retargeting, outbound nurture. <strong>Action that matters:</strong>
completing the fee calculator with their real volume &mdash; one action that reveals
segment, incumbent and deal size at once. <strong>Metric:</strong> calculator
completion; MQL &rarr; demo request.</p>
<p><strong>Drop-off risk &mdash; the trust gap on money and migration.</strong>
&ldquo;Will I be paid on time, and how painful is switching mid-calendar?&rdquo;
Unanswered, this is where mid-market quietly disappears.</p>
</div></div>

<div class="layer"><div class="n">BOFU</div><div>
<h4>One real event</h4>
<p><strong>Channels:</strong> sales conversation, compliance documentation,
reference calls, a pilot. <strong>Action that matters:</strong> agreeing to run
<strong>one live event</strong> &mdash; in ticketing that is the real commitment, not
a signature. <strong>Metric:</strong> pilots started, pilot &rarr; contract,
time-to-first-event.</p>
<p><strong>Drop-off risk:</strong> operational diligence and <em>the calendar</em>.
A yes in mid-season is a yes in four months. Forecast on their event calendar, not
your quarter.</p>
</div></div>
</div>

<h3>Qualification</h3>
<div class="scroll"><table>
<thead><tr><th>State</th><th>Definition</th></tr></thead>
<tbody>
<tr><td><strong>Sales-ready</strong></td><td>All four: verified volume above the fee-materiality floor, a named decision-maker engaged, <strong>a dated upcoming event</strong>, and an articulated trigger</td></tr>
<tr><td><strong>Nurture</strong></td><td>Right profile, wrong timing &mdash; mid-season or under contract. Not lost, <em>dated</em>. Re-engage on their season boundary</td></tr>
<tr><td><strong>Disqualified</strong></td><td>No ticket revenue, one event a year, reselling others&rsquo; inventory, multi-year exclusive with no break clause, or no reachable human. Disqualify loudly and early</td></tr>
</tbody></table></div>

<h2 id="metrics">Metrics</h2>
<h3>North star &mdash; live ticketed events processed per month</h3>
<ul>
<li>It moves <strong>only</strong> when the whole system works: a real organiser,
onboarded, trusting Ticmint with a real audience on a real date. Signups, traffic
and even ARR can all rise while it is flat</li>
<li>Every event is itself an acquisition surface &mdash; a branded ticket page in
front of that organiser&rsquo;s audience. Events compound; revenue does not yet</li>
<li>It <strong>leads</strong> revenue, because fees are a function of events &times; GTV</li>
<li>Revenue is a poor steering metric now: take rate is small, variable and
discountable, so ARR can be moved by pricing decisions that teach nothing about fit</li>
</ul>
<p class="qual"><strong>Why not in two years:</strong> once volume exists the
constraint moves from acquisition to value capture, and the north star should become
GTV per account or net revenue retention. The risk stops being &ldquo;can we get
events&rdquo; and becomes &ldquo;do we keep and grow accounts&rdquo;.</p>

<h3>Leading indicators &mdash; and the decision each one changes</h3>
<div class="scroll"><table>
<thead><tr><th>Indicator</th><th>Decision it changes</th></tr></thead>
<tbody>
<tr><td>Qualified conversations per week</td><td>Falling &rarr; list or message is wrong. Fix targeting before adding volume</td></tr>
<tr><td>Pilot events scheduled</td><td>Conversations high, pilots low &rarr; a trust or ops objection, not a demand problem. Build proof, not more outreach</td></tr>
<tr><td>Time-to-first-event after signup</td><td>Rising &rarr; onboarding is the bottleneck. Stop buying top-funnel; it is leaking</td></tr>
<tr><td>SoMV and branded search</td><td>Flat while pipeline grows &rarr; outbound is carrying it; cut organic spend or fix positioning. Rising while pipeline is flat &rarr; visible and unpersuasive: a message problem</td></tr>
<tr><td>Contactable share of discovered install base</td><td>Low &rarr; invest in enrichment, not discovery. Measured today: discovery is cheap and abundant; reachability is the constraint <span class="chip measured">measured</span></td></tr>
</tbody></table></div>

<h3>Lagging</h3>
<div class="scroll"><table>
<thead><tr><th>Indicator</th><th>Use</th></tr></thead>
<tbody>
<tr><td>GTV and revenue per account</td><td>Is the ICP the <em>valuable</em> one, or merely the easiest to close</td></tr>
<tr><td>Pilot &rarr; contract win rate</td><td>Segment truth. Persistently low means the ICP definition is wrong, not the sales team</td></tr>
<tr><td>Logo and revenue retention, CAC payback</td><td>Whether any of this compounds</td></tr>
</tbody></table></div>

<h2 id="risks">Risks and trade-offs</h2>
<h3>The assumptions underneath everything above</h3>
<ol>
<li><strong>Fee and data pain is urgent enough to force a switch</strong> &mdash; not
merely agreed with. &ldquo;Your fees are lower&rdquo; and &ldquo;I will move my next
festival&rdquo; are very different sentences</li>
<li><strong>The ICP is enumerable and reachable at volume</strong> &mdash; that
discovery from public event data survives contact with real names and real numbers</li>
<li><strong>White-label is a differentiator, not a checkbox</strong></li>
<li><strong>Generative surfaces will influence this category&rsquo;s buying</strong>
within the horizon. Plausible, unproven &mdash; which is why Part C measures rather
than assumes</li>
</ol>

<h3>The three most likely failures in six months</h3>
<div class="layers">
<div class="layer"><div class="n">01</div><div>
<h4>Seasonality makes the real cycle two to three times the model</h4>
<p>Everyone says yes; nobody starts until their next season. Pipeline looks healthy,
revenue does not arrive, cash planning breaks. Most likely, and least dramatic.</p>
</div></div>
<div class="layer"><div class="n">02</div><div>
<h4>Outbound gets throttled</h4>
<p>Deliverability, India DND regulation, WhatsApp Business policy. The primary
pipeline channel is the one most exposed to a rule change outside our control.</p>
</div></div>
<div class="layer"><div class="n">03</div><div>
<h4>The channel thesis is simply wrong</h4>
<p>This category may buy through relationships, agencies and payment-gateway
partners rather than search or cold email. Two quarters would produce learning, not
pipeline.</p>
</div></div>
</div>

<h3>If early signals come back flat</h3>
<p><strong>Do not add volume &mdash; change the unit of test.</strong> Volume on a
wrong hypothesis buys nothing but a damaged domain.</p>
<ol>
<li><strong>Narrow hard:</strong> one vertical, one region, one trigger. Ten
well-chosen accounts beat a thousand generic ones for learning</li>
<li><strong>Go conversation-first:</strong> 10&ndash;15 discovery calls with
target-profile organisers, even unpaid. Re-derive the message from their language</li>
<li><strong>Test the alternative thesis cheaply:</strong> two partnership
conversations &mdash; a payment gateway, an event agency. If relationship-led wins,
move budget. The plan should lose to evidence</li>
<li><strong>Re-examine the ICP floor:</strong> flat response often means the fee
delta was not material at the volume we targeted</li>
</ol>

<h3>What I am knowingly trading away</h3>
<ul>
<li>Self-serve creator volume, and the flattering signup chart with it</li>
<li>Broad brand awareness &mdash; no paid social, no sponsorships, for two quarters</li>
<li>Fast paid pipeline &mdash; paid search stays an instrument, not a channel</li>
<li>Enterprise and federation logos early &mdash; slower prestige in exchange for one
repeatable mid-market motion</li>
<li>Breadth of channel coverage, and the real risk that one of my three is the wrong bet</li>
</ul>
<p class="lede">Depth over coverage, evidence over reach &mdash; at the cost of
looking slower for two quarters.</p>

<div class="next">
  <a href="/work/visibility-agent"><small>Previous</small>&larr; Part C &middot; Visibility agent</a>
</div>
"""
    blurbs = {
        "icp": "Seven segments, split on who owns the audience and who carries the risk.",
        "primary": "Mid-market promoters. The fee delta is a line item they can compute in their head — displacement, not new budget.",
        "secondary": "Federations. Bigger logos, 3–9 month cycles, and the case studies that sell the primary ICP.",
        "channels": "Three, not eight: signal-qualified outbound, comparison-led organic, review sites.",
        "notdoing": "No paid search at scale — the keyword space is polluted by consumers buying tickets.",
        "outbound": "Frustration is discoverable, so the opener is evidence rather than guesswork. No evidence row, no personalised line.",
        "agent": "Install signals do the targeting, review signals do the messaging — 29 review signals matched zero companies.",
        "funnel": "The real bottom-of-funnel commitment is agreeing to run one live event, not a signature.",
        "metrics": "North star: live ticketed events per month. Revenue is a lagging function of it.",
        "risks": "Seasonality is the most likely failure and the least dramatic — the cycle runs 2–3× the model.",
    }
    body_html, rail = _accordion(body, blurbs, "D")
    return _shell(
        title="Part D — Growth Strategy | Ticmint",
        description=("ICP segmentation, channel cuts, and an outbound motion "
                     "built on discoverable organiser frustration — for a "
                     "white-label event ticketing platform."),
        current="d", rail=rail, body=body_html,
    )
