async function req(path, options = {}) {
  const res = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (res.status === 401) {
    // Session expired or never existed. Go to the branded sign-in page rather
    // than straight to Google: there is now a password option too, and the page
    // is also where a rejected sign-in can explain itself.
    window.location.href = "/login";
    throw new Error("Redirecting to sign in");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* response had no JSON body */
    }
    throw new Error(detail);
  }
  return res.json();
}

const qs = (params) => {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, v);
  });
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  stats: () => req("/api/stats"),
  leads: (filters = {}) => req(`/api/leads${qs(filters)}`),
  lead: (id) => req(`/api/leads/${id}`),
  patchLead: (id, body) =>
    req(`/api/leads/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  // filters: kind, matched, since, until, limit, platform, source_site,
  // rating_lte, country, category, switched_only
  signals: (filters = {}) => req(`/api/signals${qs(filters)}`),
  signalCounts: (days = 30) => req(`/api/signals/counts?days=${days}`),
  signalHealth: () => req("/api/signals/health"),
  // What the selector should offer. Derived from stored rows, so it can never
  // list a competitor with nothing behind it — an empty result that reads as a
  // broken filter rather than an honest absence.
  signalFacets: () => req("/api/signals/facets"),
  // Registry state for the source tabs: available / needs credentials /
  // known broken / not built. Lets an empty tab say why it is empty.
  sources: () => req("/api/sources"),

  me: () => req("/api/me"),
  patchMe: (body) => req("/api/me", { method: "PATCH", body: JSON.stringify(body) }),
  changePassword: (current, newPassword) =>
    req("/api/me/password", {
      method: "POST",
      body: JSON.stringify({ current, new_password: newPassword }),
    }),
  // Multipart: the browser has to set its own boundary, so the JSON
  // content-type default in req() would break the upload.
  uploadAvatar: async (file) => {
    const body = new FormData();
    body.append("file", file);
    const res = await fetch("/api/me/avatar", { method: "POST", body });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail ?? detail;
      } catch {
        /* no JSON body */
      }
      throw new Error(detail);
    }
    return res.json();
  },
  deleteAvatar: () => req("/api/me/avatar", { method: "DELETE" }),
  // `v` busts the cache after an upload; without it the ETag keeps the old
  // photo on screen until the 5-minute max-age lapses.
  avatarUrl: (email, v) =>
    `/api/users/${encodeURIComponent(email)}/avatar${v ? `?v=${encodeURIComponent(v)}` : ""}`,
  watchlist: () => req("/api/watchlist"),
  addWatchlist: (competitor) =>
    req("/api/watchlist", { method: "POST", body: JSON.stringify({ competitor }) }),
  removeWatchlist: (competitor) =>
    req(`/api/watchlist/${encodeURIComponent(competitor)}`, { method: "DELETE" }),

  suppression: () => req("/api/suppression"),
  unsuppress: (domain) =>
    req(`/api/suppression/${encodeURIComponent(domain)}`, { method: "DELETE" }),
  suppressBulk: (text, reason = "bulk upload") =>
    req("/api/suppression/bulk", {
      method: "POST",
      body: JSON.stringify({ text, reason }),
    }),

  alerts: () => req("/api/alerts"),
  digest: (days = 7) => req(`/api/digest?days=${days}`),
  draftLead: (id) => req(`/api/leads/${id}/draft`, { method: "POST" }),
  draftPending: (limit = 10) =>
    req(`/api/drafts/generate?limit=${limit}`, { method: "POST" }),
  enrichPending: (limit = 25) => req(`/api/enrich?limit=${limit}`, { method: "POST" }),

  settings: () => req("/api/settings"),
  patchSettings: (body) =>
    req("/api/settings", { method: "PATCH", body: JSON.stringify(body) }),

  scan: () => req("/api/scan", { method: "POST" }),
  scanStatus: () => req("/api/scan/status"),

  // ------------------------------------------------ paid work, on a click
  // Every one of these is priced before it runs. The estimate call is free and
  // is what decides whether the button renders enabled — a source can refuse a
  // specific brand, and the reason belongs on the control rather than in an
  // error after the money is gone.
  collectEstimate: (source, competitor, n = 20) =>
    req(`/api/collect/estimate${qs({ source, competitor, n })}`),
  collect: (source, competitor, overrideCap = false) =>
    req("/api/collect", {
      method: "POST",
      body: JSON.stringify({ source, competitor, override_cap: overrideCap }),
    }),

  // Free: reads stored data and reports which tier this reviewer could reach.
  signalIdentity: (id) => req(`/api/signals/${id}/identity`),
  // Paid, cached, and refused outright at the `low` tier.
  enrichReviewer: (id, overrideCap = false) =>
    req(`/api/signals/${id}/enrich-reviewer${qs({ override_cap: overrideCap || undefined })}`, {
      method: "POST",
    }),
  // Free — Apollo's organizations/enrich works on the free plan.
  enrichSignalCompany: (id) =>
    req(`/api/signals/${id}/enrich-company`, { method: "POST" }),
  identityStats: () => req("/api/identity/stats"),

  spend: (month) => req(`/api/spend${qs({ month })}`),

  // Plain hrefs rather than fetch: the response is a file download, and the
  // session cookie rides along on a normal navigation.
  exportUrl: (fmt = "csv", filters = {}) => `/api/export/leads.${fmt}${qs(filters)}`,
  // Reads stored rows only and never collects. A date range is cheap to type and
  // the sources behind these rows bill per run.
  reviewsExportUrl: (filters = {}) => `/api/export/reviews${qs(filters)}`,
};
