import { useCallback, useEffect, useState } from "react";

import { api } from "./api.js";

const SCREENS = {
  queue: ["Lead queue", "Companies running a competitor, ranked by readiness to switch"],
  signals: ["Signal feed", "Every intent signal collected, matched to a company where possible"],
  watchlist: ["Watchlist", "Competitors tracked and what each one produces"],
  settings: ["Settings", "Targeting, spend caps and outreach guardrails"],
};

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

const ageDays = (iso) =>
  Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86400000));

function chipClass(days) {
  if (days <= 14) return "s-hot";
  if (days <= 45) return "s-warm";
  return "";
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
  const [watchlist, setWatchlist] = useState([]);
  const [suppression, setSuppression] = useState([]);
  const [prefs, setPrefs] = useState(null);
  const [collectors, setCollectors] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState(null);
  const [toast, setToast] = useToast();

  const refreshQueue = useCallback(async () => {
    try {
      const params = FILTERS.find((f) => f.key === filter).params;
      const [s, l] = await Promise.all([api.stats(), api.leads(params)]);
      setStats(s);
      setLeads(l);
      setError(null);
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

  useEffect(() => {
    if (screen === "signals") api.signals({ limit: 60 }).then(setSignals).catch(() => {});
    if (screen === "watchlist") loadWatchlist();
    if (screen === "settings") {
      loadSuppression();
      api.settings().then(setPrefs).catch(() => {});
      api.scanStatus().then(setCollectors).catch(() => {});
    }
  }, [screen, loadWatchlist, loadSuppression]);

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
    const text = `Subject: ${detail.draft_subject ?? ""}\n\n${detail.draft_body ?? ""}`;
    navigator.clipboard?.writeText(text);
    setToast("Draft copied — send it from your own mailbox");
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
          <a className="btn" href={api.exportUrl} download>
            Export CSV
          </a>
          <button className="btn btn-primary" onClick={runScan} disabled={scanning}>
            {scanning ? "Scanning…" : "Run scan"}
          </button>
        </header>

        {error ? <div className="error">Could not load: {error}</div> : null}

        {screen === "queue" ? (
          <>
            <Kpis stats={stats} />
            <div className="workspace">
              <LeadTable
                leads={leads}
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
                    onAct={act}
                    onSave={saveDraft}
                    onCopy={copyDraft}
                  />
                ) : (
                  <div className="empty">Select a lead to see its signals and draft.</div>
                )}
              </aside>
            </div>
          </>
        ) : null}

        {screen === "signals" ? <SignalFeed signals={signals} /> : null}
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

function Kpis({ stats }) {
  if (!stats) return <section className="kpis" />;
  const cards = [
    ["New today", stats.new_today, `${stats.signals_7d} signals in 7 days`, false],
    ["Hot", stats.hot, "live complaint plus install", true],
    ["Awaiting you", stats.awaiting, "drafts to review"],
    ["Approved this week", stats.approved_7d, `${stats.suppressed} domains suppressed`],
    ["Install base", stats.install_base, `${stats.identifiable_pct}% contactable`],
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

function LeadTable({ leads, filter, setFilter, selectedId, onSelect }) {
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
        {leads.length === 0 ? <div className="empty">Nothing matches this filter.</div> : null}
      </div>
    </section>
  );
}

function LeadDetail({ detail, setDetail, onAct, onSave, onCopy }) {
  const d = detail;
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

        {d.contact_email ? (
          <div className="contact">
            <b>{d.contact_name}</b>
            <div className="role">{d.contact_title}</div>
            <div className="mail">{d.contact_email}</div>
          </div>
        ) : (
          <div className="contact">
            <b>No contact yet</b>
            <div className="role">
              Enrichment has not found a named decision maker at this company.
            </div>
          </div>
        )}

        <div>
          <div className="eyebrow" style={{ marginBottom: 7 }}>
            Draft — edit before approving
          </div>
          <div className="draft">
            <input
              aria-label="Subject"
              value={d.draft_subject ?? ""}
              placeholder="No draft yet — generated in Phase 2"
              onChange={(e) => setDetail({ ...d, draft_subject: e.target.value })}
            />
            <textarea
              aria-label="Body"
              value={d.draft_body ?? ""}
              placeholder="No draft yet — generated in Phase 2"
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

function SignalFeed({ signals }) {
  return (
    <div className="workspace wide">
      <section className="panel">
        <div className="panel-head">
          <span className="eyebrow">Raw intent signals</span>
          <div className="grow" />
          <span className="eyebrow">
            {signals.filter((s) => s.company_id).length} of {signals.length} matched
          </span>
        </div>
        <div className="feed">
          {signals.map((s) => {
            const days = ageDays(s.observed_at);
            return (
              <div className="feed-item" key={s.id}>
                <span className={`sig ${chipClass(days)}`}>{s.source.toUpperCase()}</span>
                <div>
                  <div className={`who${s.company ? "" : " unmatched"}`}>
                    {s.company ?? "Unmatched"}
                  </div>
                  {s.quote ? <q>{s.quote}</q> : null}
                </div>
                <time>{days}d</time>
              </div>
            );
          })}
          {signals.length === 0 ? (
            <div className="empty">
              No signals yet. Once collectors run, an empty feed here means a scraper broke.
            </div>
          ) : null}
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

function Settings({ prefs, collectors, suppression, onSave, onUnsuppress }) {
  const [draft, setDraft] = useState(null);
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
              Value proposition used by the drafter
            </div>
            <div className="draft">
              <input
                aria-label="Value proposition"
                value={current.value_proposition}
                onChange={(e) => set("value_proposition", e.target.value)}
              />
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
