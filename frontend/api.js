/* Tiny API client with automatic access-token refresh. */
const Api = (() => {
  const store = {
    get access() { return localStorage.getItem("ef_access"); },
    get refresh() { return localStorage.getItem("ef_refresh"); },
    set(t) { localStorage.setItem("ef_access", t.access_token); localStorage.setItem("ef_refresh", t.refresh_token); },
    clear() { localStorage.removeItem("ef_access"); localStorage.removeItem("ef_refresh"); },
  };
  let refreshing = null;

  function message(detail) {
    if (Array.isArray(detail)) return detail.map(d => (d.msg || "").replace(/^Value error, /, "")).join("; ");
    return detail || "Something went wrong";
  }

  async function raw(path, { method = "GET", body, auth = true } = {}) {
    const headers = { "Content-Type": "application/json" };
    if (auth && store.access) headers.Authorization = "Bearer " + store.access;
    const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
    return res;
  }

  async function doRefresh() {
    if (!store.refresh) return false;
    refreshing ||= raw("/api/auth/refresh", { method: "POST", auth: false, body: { refresh_token: store.refresh } })
      .then(async r => { if (!r.ok) { store.clear(); return false; } store.set(await r.json()); return true; })
      .finally(() => { refreshing = null; });
    return refreshing;
  }

  async function request(path, opts = {}) {
    let res = await raw(path, opts);
    if (res.status === 401 && opts.auth !== false && await doRefresh()) res = await raw(path, opts);
    if (res.status === 204) return null;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(message(data.detail));
      err.status = res.status;
      throw err;
    }
    return data;
  }

  return { store, request };
})();

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = c => c === 0 ? "Free" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(c / 100);
const fmtDate = iso => new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
const dayParts = iso => { const d = new Date(iso); return { day: d.getDate(), mon: d.toLocaleString(undefined, { month: "short" }) }; };

function toast(msg, kind = "") {
  let box = $(".toasts");
  if (!box) { box = document.createElement("div"); box.className = "toasts"; box.setAttribute("role", "status"); document.body.append(box); }
  const t = document.createElement("div");
  t.className = "toast " + kind; t.textContent = msg; box.append(t);
  setTimeout(() => t.remove(), 3800);
}

function ticketHTML(ev, { href, stub } = {}) {
  const cap = ev.ticket_types.reduce((a, t) => a + t.capacity, 0);
  const sold = ev.ticket_types.reduce((a, t) => a + t.sold, 0);
  const { day, mon } = dayParts(ev.starts_at);
  const pct = cap ? Math.round(sold / cap * 100) : 0;
  return `<${href ? "a" : "div"} class="ticket" ${href ? `href="${href}"` : ""}>
    <div class="ticket-main">
      ${ev.status ? `<span class="badge ${ev.status}">${esc(ev.status)}</span>` : ""}
      <h3>${esc(ev.title)}</h3>
      <div class="ticket-meta"><span>${esc(fmtDate(ev.starts_at))}</span>${ev.venue ? `<span>${esc(ev.venue)}</span>` : ""}</div>
      ${stub === "public" ? `<p class="muted" style="margin:.6rem 0 0">${esc(ev.description || "")}</p>` : ""}
    </div>
    <div class="ticket-stub">
      <div class="stub-date"><b>${day}</b><span>${esc(mon)}</span></div>
      ${stub === "public" ? "" : `<div class="meter ${pct >= 100 ? "full" : ""}"><i style="width:${pct}%"></i></div><small>${sold} of ${cap} sold</small>`}
    </div></${href ? "a" : "div"}>`;
}
