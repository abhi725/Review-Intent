import { useCallback, useEffect, useState } from "react";

import { api } from "./api.js";
import { ExportPanel, Sources } from "./Sources.jsx";

const SCREENS = {
  queue: ["Lead queue", "Companies running a competitor, ranked by readiness to switch"],
  signals: ["Signal feed", "Every intent signal collected, matched to a company where possible"],
  sources: ["Sources", "Where paid collection is triggered, with the price on the button"],
  exports: ["Export", "Reviews by period and the lead queue, from stored rows only"],
  watchlist: ["Watchlist", "Competitors tracked and what each one produces"],
  settings: ["Settings", "Targeting, spend caps and outreach guardrails"],
  profile: ["Your profile", "Your details, photo and password"],
};

// Order matters: this is the reading order of the counts strip, and reviews
// lead because they are the signal the queue is actually built on.
const COUNT_ORDER = [
  ["review", "Reviews"],
  ["job_post", "Job posts"],
  ["install", "Installs"],
  ["forum", "Forum"],
  ["vendor_news", "Vendor news"],
];

const FILTERS = [
  { key: "all", label: "All", params: {} },
  { key: "hot", label: "Hot", params: { heat: "hot" } },
  { key: "new", label: "Awaiting review", params: { status: "NEW" } },
  { key: "approved", label: "Approved", params: { status: "APPROVED" } },
];

const KIND_LABEL = {
  job_post: "JOB POST",
  review: "REVIEW",
  forum: "FORUM",
  vendor_news: "PRICE HIKE",
  install: "INSTALL",
};

// Where a signal was published, as distinct from the collector that fetched it.
// One collector can serve several sites, and the feed groups by site.
const SOURCE_LABEL = {
  g2: "G2",
  apify_g2: "G2",
  trustpilot: "Trustpilot",
  apify_capterra: "Capterra",
  capterra: "Capterra",
  google_news: "Google News",
  vendor_news: "Google News",
  reddit: "Reddit",
  apify_jobs: "Job boards",
  trustradius: "TrustRadius",
  softwaresuggest: "SoftwareSuggest",
  producthunt: "Product Hunt",
};

const ageDays = (iso) =>
  Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86400000));

function chipClass(days) {
  if (days <= 14) return "s-hot";
  if (days <= 45) return "s-warm";
  return "";
}

function initials(name, email) {
  const src = (name || email || "?").trim();
  const parts = src.split(/[\s.@_-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

// Deterministic hue from the address, so an account without a photo still has a
// consistent identity rather than a grey blank.
function avatarHue(email) {
  let h = 0;
  for (const ch of email || "") h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

function Avatar({ me, size = 32 }) {
  const [failed, setFailed] = useState(false);
  const src = me?.has_avatar && !failed
    ? api.avatarUrl(me.email, me.avatar_updated_at ?? "")
    : null;
  const style = { width: size, height: size, fontSize: Math.round(size / 2.6) };

  if (src) {
    return (
      <img
        className="avatar"
        style={style}
        src={src}
        alt=""
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <div
      className="avatar avatar-initials"
      style={{ ...style, "--hue": avatarHue(me?.email) }}
      aria-hidden="true"
    >
      {initials(me?.name, me?.email)}
    </div>
  );
}

function useToast() {
  const [msg, setMsg] = useState(null);
  useEffect(() => {
    if (!msg) return undefined;
    const t = setTimeout(() => setMsg(null), 2600);
    return () => clearTimeout(t);
  }, [msg]);
  return [msg, setMsg];
}

export default function App() {
  const [screen, setScreen] = useState("queue");
  const [filter, setFilter] = useState("all");
  const [stats, setStats] = useState(null);
  const [leads, setLeads] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [signals, setSignals] = useState([]);
  const [signalCounts, setSignalCounts] = useState(null);
  const [signalKind, setSignalKind] = useState("all");
  // The three-level selector: competitor → review site → everything else.
  const [feedFilters, setFeedFilters] = useState({
    platform: "",
    source_site: "",
    rating_lte: "",
    country: "",
    switched_only: false,
  });
  const [facets, setFacets] = useState(null);
  const [sources, setSources] = useState([]);
  const [me, setMe] = useState(null);
  const [watchlist, setWatchlist] = useState([]);
  const [suppression, setSuppression] = useState([]);
  const [prefs, setPrefs] = useState(null);
  const [collectors, setCollectors] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [spend, setSpend] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [error, setError] = useState(null);
  const [toast, setToast] = useToast();

  const refreshQueue = useCallback(async () => {
    try {
      const params = FILTERS.find((f) => f.key === filter).params;
      const [s, l] = await Promise.all([api.stats(), api.leads(params)]);
      setStats(s);
      setLeads(l);
      setError(null);
      // Alerts must not be able to break the queue: a failure here means the
      // health check is down, which is not a reason to hide the leads.
      api.alerts().then(setAlerts).catch(() => setAlerts([]));
      return l;
    } catch (e) {
      setError(e.message);
      return [];
    }
  }, [filter]);

  useEffect(() => {
    refreshQueue().then((l) => {
      if (l.length && !l.some((x) => x.id === selectedId)) setSelectedId(l[0].id);
      if (!l.length) {
        setSelectedId(null);
        setDetail(null);
      }
    });
    // selectedId is intentionally not a dependency: re-selecting must not refetch
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshQueue]);

  useEffect(() => {
    // Clearing the selection must clear the panel too, otherwise approving the
    // last lead in a filter leaves a stale record on screen.
    if (selectedId == null) {
      setDetail(null);
      return;
    }
    api.lead(selectedId).then(setDetail).catch((e) => setError(e.message));
  }, [selectedId]);

  const loadWatchlist = useCallback(
    () => api.watchlist().then(setWatchlist).catch((e) => setError(e.message)),
    []
  );
  const loadSuppression = useCallback(
    () => api.suppression().then(setSuppression).catch((e) => setError(e.message)),
    []
  );

  const loadMe = useCallback(() => api.me().then(setMe).catch(() => {}), []);
  useEffect(() => {
    loadMe();
  }, [loadMe]);

  const loadSignals = useCallback(() => {
    const params = { limit: 60 };
    if (signalKind !== "all") params.kind = signalKind;
    // `switched_only` is a boolean and false is meaningful — qs() drops empty
    // strings but would happily send `switched_only=false`, so it is omitted
    // rather than sent as a no-op filter.
    Object.entries(feedFilters).forEach(([k, v]) => {
      if (v !== "" && v !== false) params[k] = v;
    });
    api.signals(params).then(setSignals).catch(() => {});
    api.signalCounts(30).then(setSignalCounts).catch(() => {});
    api.signalFacets().then(setFacets).catch(() => {});
    api.sources().then(setSources).catch(() => {});
  }, [signalKind, feedFilters]);

  const loadSources = useCallback(() => {
    api.scanStatus().then(setCollectors).catch((e) => setError(e.message));
    api.spend().then(setSpend).catch(() => setSpend(null));
  }, []);

  useEffect(() => {
    if (screen === "signals") loadSignals();
    if (screen === "sources") loadSources();
    // The export screen needs the facet lists to populate its platform and site
    // pickers, and those come from stored rows — so a picker can never offer a
    // filter that matches nothing.
    if (screen === "exports") api.signalFacets().then(setFacets).catch(() => {});
    if (screen === "watchlist") loadWatchlist();
    if (screen === "settings") {
      loadSuppression();
      api.settings().then(setPrefs).catch(() => {});
      api.scanStatus().then(setCollectors).catch(() => {});
    }
  }, [screen, loadSignals, loadSources, loadWatchlist, loadSuppression]);

  async function runScan() {
    setScanning(true);
    try {
      const r = await api.scan();
      const ran = r.collectors_ran.reduce((n, c) => n + c.new, 0);
      setToast(
        r.collectors_ran.length === 0
          ? `Rescored ${r.companies_scored} companies. No collectors are wired up yet.`
          : `${ran} new signals, ${r.leads_created} new leads, ${r.companies_scored} rescored.`
      );
      await refreshQueue();
    } catch (e) {
      setError(e.message);
    } finally {
      setScanning(false);
    }
  }

  async function act(status) {
    try {
      await api.patchLead(detail.id, { status });
      setToast(
        status === "APPROVED"
          ? `${detail.company} approved`
          : `${detail.company} rejected — domain suppressed`
      );
      const l = await refreshQueue();
      if (!l.some((x) => x.id === detail.id)) setSelectedId(l[0]?.id ?? null);
      else setDetail(await api.lead(detail.id));
    } catch (e) {
      setError(e.message);
    }
  }

  async function saveDraft() {
    try {
      await api.patchLead(detail.id, {
        draft_subject: detail.draft_subject ?? "",
        draft_body: detail.draft_body ?? "",
      });
      setToast("Draft saved");
      refreshQueue();
    } catch (e) {
      setError(e.message);
    }
  }

  function copyDraft() {
    const phone = stats?.outreach_channel === "phone";
    const text = phone
      ? `${detail.contact_phone ?? "no number"} — ${detail.company}\n\n${detail.draft_body ?? ""}`
      : `Subject: ${detail.draft_subject ?? ""}\n\n${detail.draft_body ?? ""}`;
    navigator.clipboard?.writeText(text);
    setToast(phone ? "Call script copied" : "Draft copied — send it from your own mailbox");
  }

  async function generateDraft() {
    setDrafting(true);
    try {
      setDetail(await api.draftLead(detail.id));
      setToast("Draft generated — read it before approving");
      refreshQueue();
    } catch (e) {
      setError(e.message);
    } finally {
      setDrafting(false);
    }
  }

  function toggleTheme() {
    const root = document.documentElement;
    const current =
      root.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    root.setAttribute("data-theme", current === "dark" ? "light" : "dark");
  }

  const [title, subtitle] = SCREENS[screen];
  const spendPct = stats ? Math.min(100, (stats.spend_month_usd / stats.spend_cap_usd) * 100) : 0;

  return (
    <div className="app">
      <aside className="rail">
        <div className="wordmark">
          <b>Intent Desk</b> <span>v1</span>
        </div>

        <nav className="nav" aria-label="Sections">
          {Object.entries(SCREENS).map(([key, [label]]) => (
            <button
              key={key}
              aria-current={screen === key}
              onClick={() => setScreen(key)}
            >
              {label}
              {key === "queue" && stats ? (
                <span className="count">{stats.leads_total}</span>
              ) : null}
            </button>
          ))}
        </nav>

        <div className="rail-foot">
          <AccountMenu
            me={me}
            active={screen === "profile"}
            onProfile={() => setScreen("profile")}
          />
          <div className="spend">
            <div className="eyebrow">Spend this month</div>
            <div className="spend-row">
              <b>${stats ? stats.spend_month_usd.toFixed(2) : "0.00"}</b>
              <small>of ${stats ? stats.spend_cap_usd : "—"}</small>
            </div>
            <div className="meter">
              <i style={{ width: `${spendPct}%` }} />
            </div>
          </div>
          <button className="btn" onClick={toggleTheme}>
            Switch theme
          </button>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>{title}</h1>
            <div className="sub">{subtitle}</div>
          </div>
          <div className="grow" />
          <ExportMenu filters={FILTERS.find((f) => f.key === filter).params} />
          <button className="btn btn-primary" onClick={runScan} disabled={scanning}>
            {scanning ? "Scanning…" : "Run scan"}
          </button>
        </header>

        {error ? <div className="error">Could not load: {error}</div> : null}
        <AlertBar alerts={alerts} />

        {screen === "queue" ? (
          <>
            <Kpis stats={stats} />
            <div className="workspace">
              <LeadTable
                leads={leads}
                stats={stats}
                filter={filter}
                setFilter={setFilter}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
              <aside className="panel detail">
                {detail ? (
                  <LeadDetail
                    detail={detail}
                    setDetail={setDetail}
                    channel={stats?.outreach_channel ?? "both"}
                    genericPitch={stats?.generic_pitch}
                    drafting={drafting}
                    onAct={act}
                    onSave={saveDraft}
                    onCopy={copyDraft}
                    onGenerate={generateDraft}
                  />
                ) : (
                  <div className="empty">Select a lead to see its signals and draft.</div>
                )}
              </aside>
            </div>
          </>
        ) : null}

        {screen === "signals" ? (
          <SignalFeed
            signals={signals}
            counts={signalCounts}
            kind={signalKind}
            setKind={setSignalKind}
            filters={feedFilters}
            setFilters={setFeedFilters}
            facets={facets}
            sources={sources}
          />
        ) : null}
        {screen === "sources" ? (
          <Sources
            status={collectors}
            spend={spend}
            onRan={(msg) => {
              setToast(msg);
              loadSources();
              refreshQueue();
            }}
            onError={setError}
          />
        ) : null}
        {screen === "exports" ? (
          <ExportPanel
            facets={facets}
            leadFilters={FILTERS.find((f) => f.key === filter).params}
          />
        ) : null}
        {screen === "profile" ? (
          <Profile
            me={me}
            onSaved={(msg) => {
              setToast(msg);
              loadMe();
            }}
            onError={setError}
          />
        ) : null}
        {screen === "watchlist" ? (
          <Watchlist
            rows={watchlist}
            onAdd={async (name) => {
              await api.addWatchlist(name);
              setToast(`${name} added to the watchlist`);
              loadWatchlist();
            }}
            onRemove={async (name) => {
              await api.removeWatchlist(name);
              setToast(`${name} deactivated`);
              loadWatchlist();
            }}
          />
        ) : null}
        {screen === "settings" ? (
          <Settings
            prefs={prefs}
            collectors={collectors}
            suppression={suppression}
            onSave={async (changes) => {
              try {
                setPrefs(await api.patchSettings(changes));
                setToast("Settings saved — takes effect on the next scan");
              } catch (e) {
                setError(e.message);
              }
            }}
            onUnsuppress={async (domain) => {
              await api.unsuppress(domain);
              setToast(`${domain} removed from suppression`);
              loadSuppression();
            }}
            onBulkSuppress={async (text) => {
              try {
                const r = await api.suppressBulk(text);
                setToast(
                  `${r.suppressed} suppressed` +
                    (r.duplicates ? `, ${r.duplicates} duplicate` : "") +
                    (r.rejected_count ? `, ${r.rejected_count} unparseable` : "")
                );
                loadSuppression();
                return r;
              } catch (e) {
                setError(e.message);
                return null;
              }
            }}
          />
        ) : null}
      </main>

      {toast ? (
        <div className="toast" role="status" aria-live="polite">
          {toast}
        </div>
      ) : null}
    </div>
  );
}

function AlertBar({ alerts }) {
  // Info-level entries are "waiting on a token", which the Settings screen
  // already lists in full. Surfacing them here would train the eye to skip the
  // bar, and the bar exists for the day something is actually broken.
  const shown = (alerts ?? []).filter((a) => a.severity !== "info");
  if (!shown.length) return null;
  return (
    <div className="alertbar">
      {shown.map((a, i) => (
        <div className={`alert alert-${a.severity}`} key={i}>
          <b>{a.severity === "critical" ? "Broken" : "Check"}</b>
          <span>{a.message}</span>
        </div>
      ))}
    </div>
  );
}

function Kpis({ stats }) {
  if (!stats) return <section className="kpis" />;
  const channel = stats.outreach_channel ?? "both";
  const reachNote =
    channel === "phone"
      ? `${stats.reachable_phone_pct}% have a number`
      : channel === "email"
      ? `${stats.reachable_email_pct}% have an address`
      : `${stats.reachable_phone_pct}% phone · ${stats.reachable_email_pct}% email`;
  const cards = [
    ["New today", stats.new_today, `${stats.signals_7d} signals in 7 days`, false],
    ["Hot", stats.hot, "live complaint plus install", true],
    ["Awaiting you", stats.awaiting, "drafts to review"],
    ["Contactable", stats.contactable, reachNote],
    ["Install base", stats.install_base, `${stats.suppressed} domains suppressed`],
  ];
  return (
    <section className="kpis">
      {cards.map(([label, value, note, hot]) => (
        <div className={`kpi${hot ? " is-hot" : ""}`} key={label}>
          <div className="eyebrow">{label}</div>
          <b>{value}</b>
          <div className="note">{note}</div>
        </div>
      ))}
    </section>
  );
}

function LeadTable({ leads, stats, filter, setFilter, selectedId, onSelect }) {
  // An empty queue has two very different causes and the same appearance. If
  // there is no install base at all, no amount of scanning will help — the
  // pipeline has no input, and saying so is more useful than "no leads".
  const noInstallBase = stats && stats.install_base === 0;

  return (
    <section className="panel">
      <div className="panel-head">
        <div className="filters" role="group" aria-label="Filter leads">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              className="chip"
              aria-pressed={filter === f.key}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="grow" />
        <span className="eyebrow">
          {leads.length} {leads.length === 1 ? "lead" : "leads"}
        </span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Runs</th>
              <th>Why now</th>
              <th>Reach</th>
              <th className="num">Score</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {leads.map((l) => (
              <tr
                key={l.id}
                className={`heat heat-${l.heat}`}
                aria-selected={l.id === selectedId}
                onClick={() => onSelect(l.id)}
              >
                <td>
                  <div className="co">{l.company}</div>
                  <div className="co-meta">
                    {[l.city, l.domain].filter(Boolean).join(" · ")}
                  </div>
                </td>
                <td>
                  <div style={{ fontSize: 13 }}>{l.vendor}</div>
                  <div className="co-meta">
                    {l.agents_est ? `${l.agents_est} agents` : "size unknown"}
                  </div>
                </td>
                <td>
                  <div className="sigs">
                    {l.chips.length === 0 ? (
                      <span className="sig">INSTALL ONLY</span>
                    ) : (
                      l.chips.map((c, i) => {
                        const d = ageDays(c.observed_at);
                        return (
                          <span className={`sig ${chipClass(d)}`} key={i}>
                            {KIND_LABEL[c.kind] ?? c.kind.toUpperCase()} · {d}d
                          </span>
                        );
                      })
                    )}
                  </div>
                </td>
                <td>
                  {l.contact_phone ? (
                    <div style={{ fontSize: 13 }}>{l.contact_phone}</div>
                  ) : l.contact_email ? (
                    <div style={{ fontSize: 13 }}>{l.contact_email}</div>
                  ) : (
                    <span className="sig">NO CONTACT</span>
                  )}
                  {l.vendor_verified ? <div className="co-meta">verified</div> : null}
                </td>
                <td className="num">
                  <span className={`score ${l.heat}`}>{l.score}</span>
                </td>
                <td>
                  <span className={`pill p-${l.status.toLowerCase()}`}>{l.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {leads.length === 0 ? (
          <div className="empty">
            {noInstallBase ? (
              <>
                <b>No install base yet.</b>
                <div style={{ marginTop: 6 }}>
                  Nothing can be scored until companies exist. Load one with{" "}
                  <code>python -m scripts.import_installbase file.csv</code>, or run a
                  scan — the job-board collector is the only source that produces
                  companies on its own.
                </div>
              </>
            ) : (
              "Nothing matches this filter."
            )}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function LeadDetail({
  detail,
  setDetail,
  channel,
  genericPitch,
  drafting,
  onAct,
  onSave,
  onCopy,
  onGenerate,
}) {
  const d = detail;
  const isPhone = channel === "phone";
  const draftLabel = isPhone ? "Call script — read it before dialling" : "Draft — edit before approving";
  const placeholder = isPhone
    ? "No script yet — press Generate"
    : "No draft yet — press Generate";
  return (
    <>
      <div className="panel-head">
        <span className="eyebrow">Lead detail</span>
        <div className="grow" />
        <span className={`pill p-${d.status.toLowerCase()}`}>{d.status}</span>
      </div>

      <div className="detail-body">
        <div>
          <h2>{d.company}</h2>
          <div className="co-meta">{[d.city, d.domain].filter(Boolean).join(" · ")}</div>
        </div>

        <div className="facts">
          <div className="fact">
            <div className="eyebrow">Currently runs</div>
            <b>{d.vendor}</b>
          </div>
          <div className="fact">
            <div className="eyebrow">Agents</div>
            <b>{d.agents_est ?? "—"}</b>
          </div>
          <div className="fact">
            <div className="eyebrow">Intent score</div>
            <b style={{ color: `var(--${d.heat})` }}>{d.score}</b>
          </div>
          <div className="fact">
            <div className="eyebrow">Signals</div>
            <b>{d.signals.length}</b>
          </div>
        </div>

        <div>
          <div className="eyebrow" style={{ marginBottom: 9 }}>
            Why now
          </div>
          <div className="timeline">
            {d.signals.map((s) => {
              const days = ageDays(s.observed_at);
              const cls = days <= 14 ? "e-hot" : days <= 45 ? "e-warm" : "";
              return (
                <div className={`ev ${cls}`} key={s.id}>
                  <div className="ev-dot" />
                  <div>
                    <div className="ev-src">
                      <b>
                        {KIND_LABEL[s.kind] ?? s.kind} — {s.source}
                      </b>
                      <time>{days}d ago</time>
                    </div>
                    {s.quote ? <q>{s.quote}</q> : null}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {d.contact_phone || d.contact_email ? (
          <div className="contact">
            <b>{d.contact_name ?? d.company}</b>
            <div className="role">
              {d.contact_title ??
                "Company switchboard — ask for whoever runs ticketing"}
            </div>
            {d.contact_phone ? <div className="mail">{d.contact_phone}</div> : null}
            {d.contact_email ? <div className="mail">{d.contact_email}</div> : null}
            {d.vendor_verified ? (
              <div className="role" style={{ marginTop: 4 }}>
                Apollo confirms they run {d.vendor}.
              </div>
            ) : null}
          </div>
        ) : (
          <div className="contact">
            <b>No way to reach them yet</b>
            <div className="role">
              {d.enriched_at
                ? "Apollo has no phone number for this domain."
                : "Not enriched yet — run enrichment to look for a company number."}
            </div>
          </div>
        )}

        {genericPitch ? (
          <div className="alert alert-warning">
            <b>Generic pitch</b>
            <span>
              Drafts are using the placeholder value proposition. Replace it in
              Settings before sending anything.
            </span>
          </div>
        ) : null}

        <div>
          <div className="eyebrow" style={{ marginBottom: 7 }}>
            {draftLabel}
          </div>
          <div className="draft">
            <input
              aria-label={isPhone ? "Reason for the call" : "Subject"}
              value={d.draft_subject ?? ""}
              placeholder={placeholder}
              onChange={(e) => setDetail({ ...d, draft_subject: e.target.value })}
            />
            <textarea
              aria-label={isPhone ? "Call script" : "Body"}
              value={d.draft_body ?? ""}
              placeholder={placeholder}
              onChange={(e) => setDetail({ ...d, draft_body: e.target.value })}
            />
          </div>
        </div>

        <div className="actions">
          <button className="btn btn-good" onClick={() => onAct("APPROVED")}>
            Approve
          </button>
          <button className="btn btn-bad" onClick={() => onAct("REJECTED")}>
            Reject
          </button>
          <button className="btn" onClick={onGenerate} disabled={drafting}>
            {drafting ? "Generating…" : "Generate"}
          </button>
          <button className="btn" onClick={onSave}>
            Save
          </button>
          <button className="btn" onClick={onCopy} disabled={!d.draft_body}>
            Copy
          </button>
        </div>
      </div>
    </>
  );
}

function AccountMenu({ me, active, onProfile }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    const close = () => setOpen(false);
    const esc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("click", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("click", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div className="menu-wrap" onClick={(e) => e.stopPropagation()}>
      <button
        className="who-btn"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-current={active}
      >
        <Avatar me={me} size={30} />
        <span className="who-name">{me?.name ?? me?.email ?? "Account"}</span>
        <span className="who-caret" aria-hidden="true">▾</span>
      </button>

      {open ? (
        <div className="menu menu-up" role="menu">
          <div className="menu-head">
            <div className="menu-name">{me?.name ?? "Signed in"}</div>
            <div className="menu-email">{me?.email}</div>
            {me && !me.email_verified ? (
              <span className="pill warn">Unverified</span>
            ) : null}
          </div>
          <button
            role="menuitem"
            onClick={() => {
              onProfile();
              setOpen(false);
            }}
          >
            Your profile <small>Photo, details, password</small>
          </button>
          {/* A plain navigation, not fetch: /auth/logout clears the session
              cookie and redirects to the sign-in page, and letting the browser
              follow that is the whole behaviour we want. */}
          <a role="menuitem" className="danger" href="/auth/logout">
            Sign out <small>{me?.email}</small>
          </a>
        </div>
      ) : null}
    </div>
  );
}

function ExportMenu({ filters }) {
  const [open, setOpen] = useState(false);

  // Closes on any outside click. Without this the menu survives a screen change
  // and hangs over the next view.
  useEffect(() => {
    if (!open) return undefined;
    const close = () => setOpen(false);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [open]);

  return (
    <div className="menu-wrap" onClick={(e) => e.stopPropagation()}>
      <button className="btn" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        Export ▾
      </button>
      {open ? (
        <div className="menu" role="menu">
          {/* The active queue filter rides along, so "Export" means what is on
              screen rather than everything. */}
          <a href={api.exportUrl("csv", filters)} download onClick={() => setOpen(false)}>
            CSV <small>Google Sheets, anything</small>
          </a>
          <a href={api.exportUrl("xlsx", filters)} download onClick={() => setOpen(false)}>
            Excel <small>.xlsx, formatted</small>
          </a>
        </div>
      ) : null}
    </div>
  );
}

function Stars({ rating }) {
  if (rating == null) return null;
  const full = Math.round(rating);
  return (
    <span className="stars" title={`${rating} out of 5`}>
      {"★".repeat(Math.max(0, full))}
      {"☆".repeat(Math.max(0, 5 - full))}
      <small>{rating}</small>
    </span>
  );
}

// Why a source tab is empty. An empty tab that cannot explain itself is
// indistinguishable from a broken scraper, which is the failure this whole
// system is most likely to hide.
const SOURCE_STATE = {
  available: ["ok", "Collecting"],
  credentials: ["warn", "Needs credentials"],
  broken: ["bad", "Known broken"],
  unbuilt: ["off", "Not built"],
};

function sourceState(c) {
  if (!c) return null;
  if (!c.implemented) return "unbuilt";
  if (c.known_broken) return "broken";
  if (c.missing?.length) return "credentials";
  return "available";
}

function SourceTabs({ sources, facets, value, onChange }) {
  // Sites that have stored rows, plus every registered collector — so a source
  // that has never returned anything still appears, with a reason.
  const bySite = new Map();
  (facets?.pairs ?? []).forEach((p) => {
    bySite.set(p.source_site, (bySite.get(p.source_site) ?? 0) + Number(p.n));
  });
  const registered = (sources ?? []).map((c) => ({
    key: c.name === "apify_g2" ? "g2" : c.name === "vendor_news" ? "google_news" : c.name,
    label: SOURCE_LABEL[c.name] ?? c.name,
    collector: c,
  }));
  const seen = new Set(registered.map((r) => r.key));
  [...bySite.keys()].forEach((k) => {
    if (!seen.has(k)) registered.push({ key: k, label: SOURCE_LABEL[k] ?? k, collector: null });
  });

  return (
    <div className="source-tabs">
      <button
        className={`src-tab${value === "" ? " on" : ""}`}
        onClick={() => onChange("")}
      >
        All sources
        <small>{[...bySite.values()].reduce((a, b) => a + b, 0)}</small>
      </button>
      {registered.map(({ key, label, collector }) => {
        const state = sourceState(collector);
        const [tone, reason] = SOURCE_STATE[state] ?? ["ok", ""];
        const n = bySite.get(key) ?? 0;
        return (
          <button
            key={key}
            className={`src-tab ${tone}${value === key ? " on" : ""}`}
            onClick={() => onChange(value === key ? "" : key)}
            title={
              collector?.known_broken ||
              (collector?.missing?.length
                ? `Missing: ${collector.missing.join(", ")}`
                : reason)
            }
          >
            {label}
            <small>{n > 0 ? n : reason}</small>
          </button>
        );
      })}
    </div>
  );
}

function SignalFeed({ signals, counts, kind, setKind, filters, setFilters, facets, sources }) {
  const [openId, setOpenId] = useState(null);
  const matched = signals.filter((s) => s.company_id).length;
  const set = (k, v) => setFilters({ ...filters, [k]: v });
  const platforms = facets?.platforms ?? [];
  const countries = [...new Set(signals.map((s) => s.country).filter(Boolean))].sort();
  const active =
    filters.platform || filters.source_site || filters.rating_lte ||
    filters.country || filters.switched_only;

  return (
    <div className="workspace wide">
      <section className="panel selector">
        <div className="sel-row">
          <label>Competitor</label>
          <select value={filters.platform} onChange={(e) => set("platform", e.target.value)}>
            <option value="">All competitors</option>
            {platforms.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>

          <label>Rating</label>
          <select value={filters.rating_lte} onChange={(e) => set("rating_lte", e.target.value)}>
            <option value="">Any rating</option>
            <option value="1">1★ only</option>
            <option value="2">2★ and below</option>
            <option value="3">3★ and below</option>
          </select>

          <label>Country</label>
          <select value={filters.country} onChange={(e) => set("country", e.target.value)}>
            <option value="">Anywhere</option>
            {countries.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>

          <label className="check">
            <input
              type="checkbox"
              checked={filters.switched_only}
              onChange={(e) => set("switched_only", e.target.checked)}
            />
            {/* The strongest signal in the payload: someone saying in writing
                that they changed platforms, and why. */}
            Switched platforms
          </label>

          <div className="grow" />
          {active ? (
            <button
              className="link-btn"
              onClick={() =>
                setFilters({
                  platform: "", source_site: "", rating_lte: "",
                  country: "", switched_only: false,
                })
              }
            >
              Clear filters
            </button>
          ) : null}
        </div>

        <SourceTabs
          sources={sources}
          facets={facets}
          value={filters.source_site}
          onChange={(v) => set("source_site", v)}
        />
      </section>

      {counts ? (
        <div className="counts">
          <button
            className={`count-tile${kind === "all" ? " on" : ""}`}
            onClick={() => setKind("all")}
          >
            <b>{counts.total}</b>
            <span>All signals</span>
            <small>{counts.matched} matched to a company</small>
          </button>
          {COUNT_ORDER.map(([key, label]) => {
            const c = counts.by_kind[key] ?? { total: 0, matched: 0, avg_rating: null };
            return (
              <button
                key={key}
                className={`count-tile${kind === key ? " on" : ""}`}
                onClick={() => setKind(kind === key ? "all" : key)}
              >
                <b>{c.total}</b>
                <span>{label}</span>
                <small>
                  {c.avg_rating != null
                    ? `avg ${c.avg_rating}★`
                    : `${c.matched} matched`}
                </small>
              </button>
            );
          })}
          <div className="counts-note">Last {counts.days} days</div>
        </div>
      ) : null}

      <section className="panel">
        <div className="panel-head">
          <span className="eyebrow">
            {kind === "all"
              ? "Raw intent signals"
              : `Raw intent signals · ${KIND_LABEL[kind] ?? kind}`}
          </span>
          <div className="grow" />
          <span className="eyebrow">
            {matched} of {signals.length} matched
          </span>
        </div>
        <div className="feed">
          {signals.map((s) => {
            const days = ageDays(s.observed_at);
            const open = openId === s.id;
            // Nothing beyond the quote to reveal — do not offer a toggle that
            // opens an empty drawer.
            const hasDetail = Boolean(
              s.author || s.rating != null || s.url || s.subscores ||
              s.switched_reason || (s.raw_text && s.raw_text !== s.quote)
            );
            const site = SOURCE_LABEL[s.source_site ?? s.source] ?? s.source_site ?? s.source;
            return (
              <div className={`feed-item${open ? " open" : ""}`} key={s.id}>
                <span className={`sig ${chipClass(days)}`}>{site.toUpperCase()}</span>
                <div>
                  <div className="sig-line">
                    {/* The competitor is the headline fact: the whole point of
                        a row is which platform someone is unhappy with. */}
                    {s.platform ? <b className="platform">{s.platform}</b> : null}
                    {s.rating != null ? <Stars rating={s.rating} /> : null}
                    {s.switched_from ? (
                      <span className="badge switched" title={s.switched_reason || ""}>
                        switched platforms
                      </span>
                    ) : null}
                    {s.country ? <span className="badge muted">{s.country}</span> : null}
                    {s.category ? <span className="badge cat">{s.category}</span> : null}
                  </div>
                  <div className={`who${s.company ? "" : " unmatched"}`}>
                    {s.company ?? (s.author ? `${s.author} · unmatched` : "Unmatched")}
                  </div>
                  {s.quote ? <q>{s.quote}</q> : null}
                  {s.core_complaint ? <p className="complaint">{s.core_complaint}</p> : null}

                  {hasDetail ? (
                    <button className="link-btn" onClick={() => setOpenId(open ? null : s.id)}>
                      {open ? "Hide detail" : "Show detail"}
                    </button>
                  ) : null}

                  {open ? (
                    <div className="sig-detail">
                      <dl>
                        {s.author ? (
                          <>
                            <dt>Written by</dt>
                            <dd>
                              {s.author}
                              {s.author_role ? <em> · {s.author_role}</em> : null}
                            </dd>
                          </>
                        ) : null}
                        {s.rating != null ? (
                          <>
                            <dt>Rating</dt>
                            <dd>{s.rating} out of 5</dd>
                          </>
                        ) : null}
                        {s.switched_reason ? (
                          <>
                            <dt>Switched because</dt>
                            <dd>{s.switched_reason}</dd>
                          </>
                        ) : null}
                        {s.subscores ? (
                          <>
                            {/* The source's own dimension scores. A dimension
                                it did not rate is absent, not zero — zero would
                                read as "rated terrible". */}
                            <dt>Scored by reviewer</dt>
                            <dd className="subscores">
                              {Object.entries(s.subscores).map(([k, v]) => (
                                <span key={k} className="subscore">
                                  {k.replace(/([A-Z])/g, " $1").toLowerCase()} <b>{v}</b>
                                </span>
                              ))}
                            </dd>
                          </>
                        ) : null}
                        <dt>Kind</dt>
                        <dd>{KIND_LABEL[s.kind] ?? s.kind}</dd>
                        {s.url ? (
                          <>
                            <dt>Source</dt>
                            <dd>
                              {/* noreferrer as well as noopener: the target is a
                                  scraped third-party URL. */}
                              <a href={s.url} target="_blank" rel="noopener noreferrer">
                                Open original ↗
                              </a>
                            </dd>
                          </>
                        ) : null}
                      </dl>
                      {s.raw_text && s.raw_text !== s.quote ? (
                        <p className="sig-full">{s.raw_text}</p>
                      ) : null}
                      {/* Rendered inside the open drawer, not on every row: the
                          identity check is one request per signal, and firing 60
                          of them to draw a screen nobody has expanded is a lot of
                          work to decide whether a button is grey. */}
                      <SignalActions signal={s} />
                    </div>
                  ) : null}
                </div>
                <time>{days}d</time>
              </div>
            );
          })}
          {signals.length === 0 ? (
            <div className="empty">
              {/* Three different emptinesses that need three different fixes:
                  a filter that excludes everything, a source that was never
                  built, and a genuinely quiet feed. Saying "no signals" to all
                  three is what makes a working system look broken. */}
              {active ? (
                <>
                  Nothing matches these filters.
                  <button
                    className="link-btn"
                    onClick={() =>
                      setFilters({
                        platform: "", source_site: "", rating_lte: "",
                        country: "", switched_only: false,
                      })
                    }
                  >
                    Clear them
                  </button>
                </>
              ) : kind === "all" ? (
                "No signals yet. Once collectors run, an empty feed here means a scraper broke."
              ) : (
                `No ${(KIND_LABEL[kind] ?? kind).toLowerCase()} signals in this window.`
              )}
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

const TIER_NOTE = {
  high: "Rare name with an employer named in the review — usable.",
  medium: "Held for a person to look at. Not auto-draftable.",
  low: "Cannot be narrowed to one person, so it is never enriched or contacted.",
};

/**
 * The per-row controls, and the reason this screen was worth building.
 *
 * Two of the three states here are refusals, and both are decided *before* any
 * money moves. `low` means the name cannot identify one person — G2 trims a
 * surname to an initial, and no amount of Apollo credit undoes that — so the
 * button renders disabled with the reason on it rather than taking a payment to
 * report the obvious. A cached result is free, which is why even a `low` verdict
 * is stored.
 */
function SignalActions({ signal }) {
  const [assessment, setAssessment] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const [note, setNote] = useState(null);

  const load = useCallback(() => {
    api
      .signalIdentity(signal.id)
      .then((a) => {
        setAssessment(a);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }, [signal.id]);

  useEffect(load, [load]);

  async function enrichReviewer() {
    setBusy("reviewer");
    try {
      const r = await api.enrichReviewer(signal.id);
      setNote(
        r.refused
          ? `Not resolved — ${r.reason}`
          : `${r.full_name ?? "resolved"}${r.title ? ` · ${r.title}` : ""}` +
            ` (${r.confidence}${r.cached ? ", cached — free" : `, $${r.cost_usd}`})`
      );
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function enrichCompany() {
    setBusy("company");
    try {
      const r = await api.enrichSignalCompany(signal.id);
      setNote(
        r.vendor_verified
          ? "Company enriched, and the platform was confirmed from its tech stack."
          : "Company enriched. No ticketing platform showed up in its tech list — "
            + "common for small Indian firms, so the sitemap remains the evidence."
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  const cached = assessment?.cached;
  const tier = cached?.confidence ?? assessment?.predicted_tier;
  const priced = assessment?.estimate;
  const refusal = assessment?.refusal;

  return (
    <div className="sig-actions">
      {tier ? (
        <span className={`badge tier-${tier}`} title={TIER_NOTE[tier]}>
          identity: {tier}
          {cached ? " (resolved)" : ""}
        </span>
      ) : null}

      <button
        className="btn btn-pay"
        disabled={Boolean(refusal) || busy === "reviewer" || !assessment}
        title={refusal ?? priced?.note ?? undefined}
        onClick={enrichReviewer}
      >
        {busy === "reviewer"
          ? "Resolving…"
          : cached
            ? "Reviewer resolved · free"
            : `Enrich reviewer · ${priced ? `${priced.measured ? "" : "~"}$${priced.estimated_usd.toFixed(2)}` : "—"}`}
      </button>

      {signal.company_id ? (
        <button className="btn" disabled={busy === "company"} onClick={enrichCompany}>
          {busy === "company" ? "Enriching…" : "Enrich company · free"}
        </button>
      ) : null}

      {refusal ? <div className="refusal">{refusal}</div> : null}
      {note ? <div className="note">{note}</div> : null}
      {error ? <div className="error inline">{error}</div> : null}
    </div>
  );
}

function Profile({ me, onSaved, onError }) {
  const [form, setForm] = useState(null);
  const [pw, setPw] = useState({ current: "", next: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (me) setForm({ name: me.name ?? "", job_title: me.job_title ?? "", phone: me.phone ?? "" });
  }, [me]);

  if (!me || !form) return <div className="workspace wide"><div className="empty">Loading…</div></div>;

  // A session minted before accounts existed authenticates fine but has no row
  // behind it, so every save here would fail. Say so once, at the top, instead
  // of letting them fill the form and hit an error on submit.
  if (me.stale_session) {
    return (
      <div className="workspace wide">
        <section className="panel">
          <div className="panel-head">
            <span className="eyebrow">Finish setting up your account</span>
          </div>
          <div className="stale">
            <p>
              You are signed in with a session created before this deploy had
              accounts, so there is no profile behind it yet.
            </p>
            <p>
              <b>Sign out and sign in again.</b> One click — it creates the
              account, and everything on this screen starts working.
            </p>
            <a className="btn btn-primary" href="/auth/logout">
              Sign out and back in
            </a>
          </div>
        </section>
      </div>
    );
  }

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function saveDetails() {
    setBusy(true);
    try {
      await api.patchMe(form);
      onSaved("Profile saved");
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function upload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      await api.uploadAvatar(file);
      onSaved("Photo updated");
    } catch (err) {
      onError(err.message);
    } finally {
      setBusy(false);
      // Reset the input so re-picking the same file fires change again.
      e.target.value = "";
    }
  }

  async function removePhoto() {
    try {
      await api.deleteAvatar();
      onSaved("Photo removed");
    } catch (e) {
      onError(e.message);
    }
  }

  async function changePassword() {
    setBusy(true);
    try {
      await api.changePassword(pw.current, pw.next);
      setPw({ current: "", next: "" });
      onSaved("Password changed");
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="workspace wide">
      <section className="panel">
        <div className="panel-head">
          <span className="eyebrow">Your details</span>
        </div>

        <div className="profile-head">
          <Avatar me={me} size={72} />
          <div>
            <div className="profile-email">
              {me.email}
              {me.email_verified ? (
                <span className="pill ok">Verified</span>
              ) : (
                <span className="pill warn">Unverified</span>
              )}
            </div>
            <div className="profile-how">
              Signs in with{" "}
              {[me.has_password && "a password", me.has_google && "Google"]
                .filter(Boolean)
                .join(" and ") || "no method configured"}
              {me.is_admin ? " · admin" : ""}
            </div>
            <div className="profile-actions">
              <label className="btn">
                {me.has_avatar ? "Change photo" : "Upload photo"}
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  onChange={upload}
                  hidden
                />
              </label>
              {me.has_avatar ? (
                <button className="btn" onClick={removePhoto}>
                  Remove
                </button>
              ) : null}
            </div>
            <div className="hint">PNG, JPEG, WebP or GIF up to 2 MB. Cropped square to 256px.</div>
          </div>
        </div>

        <div className="form-grid">
          <label>
            Name
            <input value={form.name} onChange={set("name")} placeholder="Priya Nair" />
          </label>
          <label>
            Job title
            <input value={form.job_title} onChange={set("job_title")} placeholder="Head of Sales" />
          </label>
          <label>
            Phone
            <input value={form.phone} onChange={set("phone")} placeholder="+91 98765 43210" />
          </label>
        </div>
        <div className="sig-actions">
          <button className="btn btn-primary" onClick={saveDetails} disabled={busy}>
            Save details
          </button>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <span className="eyebrow">Password</span>
        </div>
        <div className="form-grid">
          <label>
            Current password
            <input
              type="password"
              autoComplete="current-password"
              value={pw.current}
              onChange={(e) => setPw({ ...pw, current: e.target.value })}
              placeholder={me.has_password ? "••••••••••••" : "You have no password yet"}
            />
          </label>
          <label>
            New password
            <input
              type="password"
              autoComplete="new-password"
              value={pw.next}
              onChange={(e) => setPw({ ...pw, next: e.target.value })}
              placeholder="At least 12 characters"
            />
          </label>
        </div>
        <div className="hint">
          Length beats symbols — a short phrase you will remember is stronger than P@ssw0rd1.
          Locked out instead? Use <a href="/forgot">forgot password</a>.
        </div>
        <div className="sig-actions">
          <button
            className="btn btn-primary"
            onClick={changePassword}
            disabled={busy || pw.next.length < 12}
          >
            Change password
          </button>
        </div>
      </section>
    </div>
  );
}

function Watchlist({ rows, onAdd, onRemove }) {
  const [name, setName] = useState("");

  return (
    <div className="workspace wide">
      <section className="panel">
        <div className="panel-head">
          <span className="eyebrow">Competitors tracked</span>
          <div className="grow" />
          <form
            className="inline-form"
            onSubmit={(e) => {
              e.preventDefault();
              const v = name.trim();
              if (!v) return;
              setName("");
              onAdd(v);
            }}
          >
            <input
              aria-label="Competitor name"
              placeholder="Add a competitor"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <button className="btn" type="submit" disabled={!name.trim()}>
              Add
            </button>
          </form>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Competitor</th>
                <th>Sources</th>
                <th className="num">Install base</th>
                <th className="num">Negatives 180d</th>
                <th className="num">Leads produced</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((w) => (
                <tr key={w.id} style={{ cursor: "default" }}>
                  <td>
                    <div className="co">{w.competitor}</div>
                    {!w.active ? <div className="co-meta">inactive</div> : null}
                  </td>
                  <td>
                    <div className="sigs">
                      {(w.sources ?? []).map((s) => (
                        <span className="sig" key={s}>
                          {s}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="num">{w.install_base}</td>
                  <td className="num">{w.negatives_180d}</td>
                  <td className="num">{w.leads_produced}</td>
                  <td className="num">
                    {w.active ? (
                      <button className="btn btn-bad" onClick={() => onRemove(w.competitor)}>
                        Deactivate
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

const PREF_FIELDS = [
  ["target_country", "Country", "text"],
  ["target_agents_min", "Agents min", "number"],
  ["target_agents_max", "Agents max", "number"],
  ["signal_recency_days", "Signal recency (days)", "number"],
  ["monthly_spend_cap_usd", "Monthly cap (USD)", "number"],
];

function Settings({ prefs, collectors, suppression, onSave, onUnsuppress, onBulkSuppress }) {
  const [draft, setDraft] = useState(null);
  const [bulk, setBulk] = useState("");
  const current = draft ?? prefs;

  if (!current) return <div className="workspace wide"><div className="empty">Loading…</div></div>;

  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(prefs);
  const set = (k, v) => setDraft({ ...current, [k]: v });

  return (
    <div className="workspace wide">
      <section className="panel">
        <div className="panel-head">
          <span className="eyebrow">Targeting and guardrails</span>
          <div className="grow" />
          <button
            className="btn btn-primary"
            disabled={!dirty}
            onClick={() => {
              onSave(draft);
              setDraft(null);
            }}
          >
            {dirty ? "Save changes" : "Saved"}
          </button>
        </div>
        <div className="detail-body" style={{ maxWidth: 720 }}>
          <div className="facts" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))" }}>
            {PREF_FIELDS.map(([key, label, type]) => (
              <label className="fact" key={key}>
                <div className="eyebrow">{label}</div>
                <input
                  className="fact-input"
                  type={type}
                  value={current[key]}
                  onChange={(e) =>
                    set(key, type === "number" ? Number(e.target.value) : e.target.value)
                  }
                />
              </label>
            ))}
          </div>

          <div>
            <div className="eyebrow" style={{ marginBottom: 7 }}>
              Who can sign in
            </div>
            <div className="filters" role="group" aria-label="Access mode">
              {[
                ["open", "Anyone with Google"],
                ["domain", "Our domain only"],
                ["allowlist", "Domain + approved guests"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  className="chip"
                  aria-pressed={current.access_mode === value}
                  onClick={() => set("access_mode", value)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="draft" style={{ marginTop: 8 }}>
              <input
                aria-label="Allowed email domains"
                value={current.allowed_email_domains ?? ""}
                placeholder="example.com, partner.com — only used by the two modes above"
                onChange={(e) => set("allowed_email_domains", e.target.value)}
              />
            </div>
            {current.access_mode === "open" ? (
              <div className="alert alert-warning" style={{ marginTop: 8 }}>
                <b>Open</b>
                <span>
                  Anyone with this URL can sign up and read the lead queue,
                  drafts and suppression list. No domain restriction is in
                  force. The other two modes are here for when you want one.
                </span>
              </div>
            ) : (
              <div className="role" style={{ marginTop: 6 }}>
                Checked on every sign-in, not just at signup — tightening this
                locks out accounts created while it was open.
              </div>
            )}
          </div>

          <div>
            <div className="eyebrow" style={{ marginBottom: 7 }}>
              Outreach channel
            </div>
            <div className="filters" role="group" aria-label="Outreach channel">
              {[
                ["phone", "Phone"],
                ["email", "Email"],
                ["both", "Both"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  className="chip"
                  aria-pressed={current.outreach_channel === value}
                  onClick={() => set("outreach_channel", value)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="role" style={{ marginTop: 6 }}>
              Apollo&rsquo;s free plan returns a company phone number and never an
              email address. On <b>Email</b> the queue will report nothing
              contactable until a paid Apollo plan exists. The channel also
              decides what the drafter writes — a spoken call opener or an email.
            </div>
          </div>

          <div>
            <div className="eyebrow" style={{ marginBottom: 7 }}>
              Value proposition used by the drafter
            </div>
            <div className="draft">
              <input
                aria-label="Value proposition"
                value={current.value_proposition}
                onChange={(e) => set("value_proposition", e.target.value)}
              />
            </div>
            <div className="role" style={{ marginTop: 6 }}>
              This is the one input the tool cannot supply. Every draft inherits it.
            </div>
          </div>

          {collectors ? (
            <div>
              <div className="eyebrow" style={{ marginBottom: 7 }}>
                Collectors — {collectors.ready} of {collectors.total} ready
              </div>
              <div className="feed">
                {collectors.collectors.map((c) => (
                  <div className="feed-item" key={c.name} style={{ gridTemplateColumns: "1fr auto" }}>
                    <div>
                      <div className="who">{c.name}</div>
                      <q>
                        {c.available
                          ? "ready"
                          : c.missing.length
                          ? `waiting on ${c.missing.join(", ")}`
                          : c.note ?? "not built yet"}
                      </q>
                    </div>
                    <span className={`pill ${c.available ? "p-approved" : "p-rejected"}`}>
                      {c.available ? "ready" : "blocked"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <div className="contact">
            <b>Outreach is company-level by default</b>
            <div className="role" style={{ marginTop: 4 }}>
              Drafts never quote or reference the signal that surfaced the lead. Nothing
              sends without approval — Approve puts the draft on your clipboard.
            </div>
          </div>

          <div>
            <div className="eyebrow" style={{ marginBottom: 7 }}>
              Load a do-not-contact list
            </div>
            <div className="draft">
              <textarea
                aria-label="Domains to suppress"
                placeholder={
                  "One per line, or comma separated.\n" +
                  "Existing customers, live deals, anyone who has asked not to be contacted.\n" +
                  "URLs and email addresses are accepted."
                }
                value={bulk}
                onChange={(e) => setBulk(e.target.value)}
              />
            </div>
            <div className="actions" style={{ marginTop: 8 }}>
              <button
                className="btn"
                disabled={!bulk.trim()}
                onClick={async () => {
                  const r = await onBulkSuppress(bulk);
                  if (r) setBulk("");
                }}
              >
                Suppress these
              </button>
            </div>
          </div>

          <div>
            <div className="eyebrow" style={{ marginBottom: 7 }}>
              Suppression list ({suppression.length})
            </div>
            <div className="feed">
              {suppression.slice(0, 25).map((s) => (
                <div
                  className="feed-item"
                  key={s.domain}
                  style={{ gridTemplateColumns: "1fr auto auto" }}
                >
                  <div>
                    <div className="who">{s.domain}</div>
                    <q>{s.reason}</q>
                  </div>
                  <time>{ageDays(s.added_at)}d</time>
                  <button className="btn" onClick={() => onUnsuppress(s.domain)}>
                    Remove
                  </button>
                </div>
              ))}
              {suppression.length === 0 ? (
                <div className="empty">Nothing suppressed yet.</div>
              ) : null}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
