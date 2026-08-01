async function req(path, options = {}) {
  const res = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (res.status === 401) {
    // Session expired or never existed — hand off to Google rather than
    // leaving the operator staring at an error they cannot act on.
    window.location.href = "/auth/login";
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
  signals: (filters = {}) => req(`/api/signals${qs(filters)}`),
  signalHealth: () => req("/api/signals/health"),
  watchlist: () => req("/api/watchlist"),
  suppression: () => req("/api/suppression"),
};
