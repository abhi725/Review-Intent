import { useCallback, useEffect, useState } from "react";

import { api } from "./api.js";

// Human names for the collector ids, so a screen about money does not read like
// a variable dump.
const SOURCE_LABEL = {
  vendor_news: "Google News",
  reddit: "Reddit",
  trustpilot: "Trustpilot",
  apify_g2: "G2",
  apify_capterra: "Capterra",
  apify_jobs: "Job boards",
  trustradius: "TrustRadius",
  softwaresuggest: "SoftwareSuggest",
  meraevents_organisers: "MeraEvents organisers",
  townscript_organisers: "Townscript organisers",
};

const KIND_LABEL = {
  review: "Reviews",
  forum: "Forum posts",
  vendor_news: "Vendor news",
  job_post: "Job posts",
  discovery: "Company discovery",
  install: "Install base",
};

function label(name) {
  return SOURCE_LABEL[name] ?? name;
}

/** Why this source cannot run right now, in the order the reader can act on. */
function blockedReason(c) {
  if (c.known_broken) return c.known_broken;
  if (c.missing?.length) return `Needs ${c.missing.join(", ")}`;
  if (!c.implemented) return c.note || "Not built yet";
  if (!c.available) return c.note || "Not available";
  return null;
}

/**
 * Sources — where paid collection is triggered, one source at a time.
 *
 * The governing rule of this product is that free work runs on a schedule and
 * paid work runs on a click. This screen is the click. Every button carries its
 * own price, taken from measured figures on the server rather than from a
 * constant in the UI, because a price that lives in two places eventually
 * disagrees with itself and the copy on the button is the one people believe.
 */
export function Sources({ status, spend, onRan, onError }) {
  const [competitor, setCompetitor] = useState("");
  const [estimates, setEstimates] = useState({});
  const [running, setRunning] = useState(null);
  const [watchlist, setWatchlist] = useState([]);

  useEffect(() => {
    api.watchlist().then(setWatchlist).catch(() => setWatchlist([]));
  }, []);

  const collectors = status?.collectors ?? [];

  // Re-priced whenever the brand changes, because the answer depends on it:
  // Trustpilot refuses a consumer marketplace outright, and the button has to say
  // so rather than failing on click.
  const loadEstimates = useCallback(async () => {
    const priced = collectors.filter((c) => c.action);
    const results = await Promise.all(
      priced.map((c) =>
        api
          .collectEstimate(c.name, competitor || undefined, 20)
          .then((e) => [c.name, e])
          .catch(() => [c.name, null])
      )
    );
    setEstimates(Object.fromEntries(results));
    // collectors is derived from `status`, which is the real dependency
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, competitor]);

  useEffect(() => {
    if (collectors.length) loadEstimates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadEstimates]);

  async function run(source) {
    setRunning(source);
    try {
      const r = await api.collect(source, competitor || undefined);
      const found = r.collectors_ran?.reduce((n, c) => n + c.found, 0) ?? 0;
      const fresh = r.collectors_ran?.reduce((n, c) => n + c.new, 0) ?? 0;
      const cost = r.collectors_ran?.reduce((n, c) => n + c.cost_usd, 0) ?? 0;
      const declined = r.collectors_skipped?.find((s) => s.collector === source);

      onRan(
        declined
          ? `${label(source)} declined: ${declined.reason}`
          : `${label(source)}: ${found} found, ${fresh} new` +
            (cost ? `, $${cost.toFixed(4)} spent` : ", free")
      );
      loadEstimates();
    } catch (e) {
      onError(e.message);
    } finally {
      setRunning(null);
    }
  }

  const pct = spend ? Math.min(100, spend.fraction_used * 100) : 0;

  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head">
          <h2>Spend this month</h2>
          <div className="grow" />
          {spend?.exhausted ? (
            <span className="badge danger">cap reached</span>
          ) : spend?.warning ? (
            <span className="badge warn">over 80%</span>
          ) : null}
        </div>

        <div className="spend-wide">
          <div className="spend-figure">
            <b>${spend ? spend.spent_usd.toFixed(4) : "0.0000"}</b>
            <small>of ${spend ? spend.cap_usd.toFixed(2) : "—"}</small>
          </div>
          <div className="meter big">
            <i
              className={spend?.exhausted ? "over" : spend?.warning ? "warn" : ""}
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>

        {spend?.exhausted ? (
          <p className="note">
            Paid sources are refused until the month rolls over, or until the cap is
            raised in Settings. Free sources keep running.
          </p>
        ) : null}

        {spend?.unledgered_usd > 0 ? (
          <p className="note">
            ${spend.unledgered_usd.toFixed(4)} of this month&rsquo;s spend has no
            per-call record — it predates the ledger. Shown rather than hidden: a
            silent gap between the two totals is how an untracked paid path stays
            untracked.
          </p>
        ) : null}

        {spend?.by_provider?.length ? (
          <table className="grid tight">
            <thead>
              <tr>
                <th>Source</th>
                <th>Calls</th>
                <th>Quoted</th>
                <th>Billed</th>
              </tr>
            </thead>
            <tbody>
              {spend.by_provider.map((p) => (
                <tr key={p.key}>
                  <td>{label(p.key)}</td>
                  <td>{p.calls}</td>
                  <td className="num">${p.quoted_usd.toFixed(4)}</td>
                  <td className="num">
                    <b>${p.spent_usd.toFixed(4)}</b>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="note">Nothing has been billed this month.</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Collect now</h2>
          <div className="grow" />
          <label className="inline-field">
            Competitor
            <select value={competitor} onChange={(e) => setCompetitor(e.target.value)}>
              <option value="">All tracked</option>
              {watchlist
                .filter((w) => w.active)
                .map((w) => (
                  <option key={w.competitor} value={w.competitor}>
                    {w.competitor}
                    {w.segment === "consumer_marketplace" ? " (attendee audience)" : ""}
                  </option>
                ))}
            </select>
          </label>
        </div>

        <p className="note">
          Free sources also run on the nightly schedule. Paid ones only run from
          here, and the price on each button is what the last measured run
          actually cost.
        </p>

        <div className="source-list">
          {collectors.map((c) => {
            const est = estimates[c.name];
            const blocked = blockedReason(c);
            const refused = est?.blocked;
            const free = c.cost_model === "free";
            const canRun = !blocked && !refused && (free || !spend?.exhausted);

            return (
              <div className={`source-row${canRun ? "" : " off"}`} key={c.name}>
                <div className="source-id">
                  <b>{label(c.name)}</b>
                  <span className="badge muted">{KIND_LABEL[c.kind] ?? c.kind}</span>
                  {free ? (
                    <span className="badge ok">free</span>
                  ) : (
                    <span className="badge pay">paid</span>
                  )}
                  {c.cadence === "scheduled" ? (
                    <span className="badge muted">on the schedule</span>
                  ) : (
                    <span className="badge muted">on demand</span>
                  )}
                </div>

                <div className="source-why">
                  {/* Priority order matters. A brand-level refusal is more
                      specific than "needs credentials" and more actionable than
                      the generic note, so it wins the one line available. */}
                  {refused ?? blocked ?? c.note ?? est?.estimate?.note ?? ""}
                </div>

                <div className="source-act">
                  {est?.estimate && !free ? (
                    <span className="price" title={est.estimate.note}>
                      {est.estimate.measured ? "" : "~"}$
                      {est.estimate.estimated_usd.toFixed(est.estimate.estimated_usd < 0.01 ? 4 : 2)}
                      <small> / {est.estimate.units} {est.estimate.unit}</small>
                    </span>
                  ) : null}
                  <button
                    className={`btn${free ? "" : " btn-pay"}`}
                    disabled={!canRun || running === c.name}
                    onClick={() => run(c.name)}
                    title={refused ?? blocked ?? undefined}
                  >
                    {running === c.name ? "Running…" : free ? "Run" : "Run · pay"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {status?.retired?.length ? (
        <section className="panel">
          <div className="panel-head">
            <h2>Decided against</h2>
          </div>
          <p className="note">
            Sources that were tried and rejected, kept visible so a gap here reads
            as a decision rather than an oversight to be rebuilt.
          </p>
          <ul className="reasons">
            {status.retired.map((r) => (
              <li key={r.name}>
                <b>{label(r.name)}</b> — {r.reason}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

/**
 * Export — the period export, and the one thing it deliberately will not do.
 *
 * It exports stored rows. It never triggers a fetch, because a date range is a
 * cheap thing to type and the sources behind these rows bill per run: wiring
 * collection to a date picker would turn a typo into a charge.
 */
export function ExportPanel({ facets, leadFilters }) {
  const [form, setForm] = useState({
    from: "",
    to: "",
    group: "month",
    platform: "",
    source_site: "",
    rating_lte: "",
  });

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const params = Object.fromEntries(Object.entries(form).filter(([, v]) => v !== ""));

  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head">
          <h2>Reviews by period</h2>
        </div>
        <p className="note">
          The workbook opens on a Summary sheet — reviews per period, average
          rating, how many said outright that they switched platform — with every
          row behind it. Exports what has already been collected; it never fetches,
          so no date range can cost money.
        </p>

        <div className="form-grid">
          <label>
            From
            <input type="date" value={form.from} onChange={(e) => set("from", e.target.value)} />
          </label>
          <label>
            To
            <input type="date" value={form.to} onChange={(e) => set("to", e.target.value)} />
          </label>
          <label>
            Group by
            <select value={form.group} onChange={(e) => set("group", e.target.value)}>
              <option value="month">Month</option>
              <option value="year">Year</option>
            </select>
          </label>
          <label>
            Platform
            <select value={form.platform} onChange={(e) => set("platform", e.target.value)}>
              <option value="">All</option>
              {(facets?.platforms ?? []).map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <label>
            Review site
            <select
              value={form.source_site}
              onChange={(e) => set("source_site", e.target.value)}
            >
              <option value="">All</option>
              {(facets?.sites ?? []).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label>
            Rating at most
            <select value={form.rating_lte} onChange={(e) => set("rating_lte", e.target.value)}>
              <option value="">Any</option>
              <option value="2">2 stars</option>
              <option value="3">3 stars</option>
            </select>
          </label>
        </div>

        <div className="row gap">
          {/* Plain links, not fetch: the session cookie rides along on a normal
              navigation and the browser handles the download. */}
          <a className="btn btn-primary" href={api.reviewsExportUrl({ ...params, format: "xlsx" })}>
            Download .xlsx
          </a>
          <a className="btn" href={api.reviewsExportUrl({ ...params, format: "csv" })}>
            Download .csv
          </a>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Lead queue</h2>
        </div>
        <p className="note">
          The queue as it stands, with drafts. An empty range is refused with a
          reason rather than downloading a file containing only headers.
        </p>
        <div className="row gap">
          <a className="btn btn-primary" href={api.exportUrl("xlsx", leadFilters)}>
            Download .xlsx
          </a>
          <a className="btn" href={api.exportUrl("csv", leadFilters)}>
            Download .csv
          </a>
        </div>
      </section>
    </div>
  );
}
