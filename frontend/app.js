/* EventForge organizer console — vanilla JS, hash-routed. */
const RANK = { viewer: 1, staff: 2, admin: 3, owner: 4 };
const S = { user: null, orgs: [], org: null };
const can = min => S.org && RANK[S.org.role] >= RANK[min];
const app = $("#app");
const orgPath = p => `/api/orgs/${S.org.id}${p}`;

/* ------------------------------------------------------------ boot + auth */
async function boot() {
  if (!Api.store.access && !Api.store.refresh) return renderAuth("login");
  try {
    S.user = await Api.request("/api/auth/me");
    await loadOrgs();
  } catch { Api.store.clear(); return renderAuth("login"); }
  S.orgs.length ? renderShell() : renderOnboarding();
}

async function loadOrgs() {
  S.orgs = await Api.request("/api/orgs");
  const saved = Number(localStorage.getItem("ef_org"));
  S.org = S.orgs.find(o => o.id === saved) || S.orgs[0] || null;
}

function renderAuth(mode) {
  const reg = mode === "register";
  app.innerHTML = `
  <div class="auth">
    <section class="auth-art">
      <div class="brand"><i></i>EventForge</div>
      <div>
        <h1>Sell out the room. Scan them in.</h1>
        <p>Run every event your team hosts from one console: tickets, capacity, payments, and door check-in.</p>
      </div>
      <div class="ticket mini-ticket" aria-hidden="true" style="--stub:110px;color:var(--ink)">
        <div class="ticket-main"><span class="badge published">published</span><h3>Rooftop launch night</h3><div class="ticket-meta"><span>Fri, 7:30 pm</span></div></div>
        <div class="ticket-stub"><div class="stub-date"><b>14</b><span>Nov</span></div><div class="meter"><i style="width:82%"></i></div><small>164 of 200</small></div>
      </div>
    </section>
    <section class="auth-form">
      <h2>${reg ? "Create your account" : "Log in"}</h2>
      <form id="auth-form" novalidate>
        ${reg ? `<div class="field"><label for="name">Full name</label><input id="name" autocomplete="name" required></div>` : ""}
        <div class="field"><label for="email">Email</label><input id="email" type="email" autocomplete="email" required></div>
        <div class="field"><label for="pw">Password</label><input id="pw" type="password" autocomplete="${reg ? "new-password" : "current-password"}" minlength="8" required>
          ${reg ? `<small class="muted">At least 8 characters.</small>` : ""}</div>
        <p class="error" id="auth-err" role="alert"></p>
        <button type="submit" style="width:100%;justify-content:center">${reg ? "Create account" : "Log in"}</button>
      </form>
      <p class="switch muted">${reg ? "Already have an account?" : "New to EventForge?"}
        <button type="button" id="swap">${reg ? "Log in" : "Create an account"}</button></p>
    </section>
  </div>`;
  $("#swap").onclick = () => renderAuth(reg ? "login" : "register");
  $("#auth-form").onsubmit = async e => {
    e.preventDefault();
    const btn = e.submitter; btn.disabled = true; $("#auth-err").textContent = "";
    try {
      const body = { email: $("#email").value.trim(), password: $("#pw").value };
      if (reg) body.full_name = $("#name").value.trim();
      Api.store.set(await Api.request(`/api/auth/${reg ? "register" : "login"}`, { method: "POST", auth: false, body }));
      await boot();
    } catch (err) { $("#auth-err").textContent = err.message; btn.disabled = false; }
  };
}

function renderOnboarding() {
  app.innerHTML = `<div class="auth"><section class="auth-art"><div class="brand"><i></i>EventForge</div>
    <div><h1>Name your organization.</h1><p>Everything you create (events, tickets, team members) lives inside it, and stays private to it.</p></div><span></span></section>
    <section class="auth-form"><h2>Welcome, ${esc(S.user.full_name.split(" ")[0])}</h2>
    <form id="org-form"><div class="field"><label for="oname">Organization name</label><input id="oname" required minlength="2" placeholder="Northside Music Collective"></div>
    <p class="error" id="oerr" role="alert"></p><button type="submit">Create organization</button></form>
    <p class="switch"><button type="button" id="logout">Log out</button></p></section></div>`;
  $("#logout").onclick = logout;
  $("#org-form").onsubmit = async e => {
    e.preventDefault();
    try { const o = await Api.request("/api/orgs", { method: "POST", body: { name: $("#oname").value } }); localStorage.setItem("ef_org", o.id); await boot(); }
    catch (err) { $("#oerr").textContent = err.message; }
  };
}

async function logout() {
  try { await Api.request("/api/auth/logout", { method: "POST", body: { refresh_token: Api.store.refresh } }); } catch {}
  Api.store.clear(); S.user = S.org = null; renderAuth("login");
}

/* ------------------------------------------------------------ shell + router */
const NAV = [["overview", "Overview"], ["events", "Events"], ["checkin", "Check-in", "staff"], ["team", "Team"], ["activity", "Activity", "admin"]];

function renderShell() {
  app.innerHTML = `<div class="shell">
    <aside class="rail">
      <div class="brand"><i></i>EventForge</div>
      <div><label class="sr" for="org-switch">Organization</label>
        <select id="org-switch">${S.orgs.map(o => `<option value="${o.id}" ${o.id === S.org.id ? "selected" : ""}>${esc(o.name)}</option>`).join("")}<option value="new">New organization…</option></select></div>
      <nav aria-label="Main">${NAV.filter(n => !n[2] || can(n[2])).map(([k, l]) => `<a href="#/${k}" data-nav="${k}">${l}</a>`).join("")}</nav>
      <div class="who">${esc(S.user.full_name)}<br>${esc(S.org.role)} in ${esc(S.org.name)}<br><button class="small" id="logout">Log out</button></div>
    </aside>
    <main id="view" tabindex="-1"></main></div>`;
  $("#logout").onclick = logout;
  $("#org-switch").onchange = async e => {
    if (e.target.value === "new") return newOrgDialog();
    localStorage.setItem("ef_org", e.target.value); await loadOrgs(); location.hash = "#/overview"; renderShell();
  };
  route();
}

function newOrgDialog() {
  dialog(`<h2>New organization</h2><form method="dialog" id="f"><div class="field"><label for="n">Name</label><input id="n" required minlength="2"></div>
    <p class="error" id="e"></p><div class="actions"><button>Create</button><button type="button" class="ghost" data-close>Cancel</button></div></form>`,
    async (d) => { const o = await Api.request("/api/orgs", { method: "POST", body: { name: $("#n", d).value } }); localStorage.setItem("ef_org", o.id); await loadOrgs(); renderShell(); },
    () => { $("#org-switch").value = S.org.id; });
}

window.addEventListener("hashchange", () => S.org && route());

async function route() {
  const [, page = "overview", arg] = location.hash.split("/");
  $$(".rail nav a").forEach(a => a.dataset.nav === page ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  const view = $("#view");
  view.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    if (page === "events" && arg) await viewEvent(view, Number(arg));
    else await ({ overview: viewOverview, events: viewEvents, checkin: viewCheckin, team: viewTeam, activity: viewActivity }[page] || viewOverview)(view);
  } catch (err) { view.innerHTML = `<div class="empty"><h3>Couldn't load this page</h3><p>${esc(err.message)}</p></div>`; }
}

/* ------------------------------------------------------------ dialog helper */
function dialog(html, onSubmit, onClose) {
  const d = document.createElement("dialog");
  d.innerHTML = html; document.body.append(d); d.showModal();
  const close = () => { d.close(); d.remove(); onClose && onClose(); };
  d.addEventListener("cancel", () => onClose && onClose());
  $$("[data-close]", d).forEach(b => b.onclick = close);
  const f = $("form", d);
  f.onsubmit = async e => {
    e.preventDefault(); const btn = e.submitter; btn && (btn.disabled = true); $(".error", d).textContent = "";
    try { await onSubmit(d); d.close(); d.remove(); } catch (err) { $(".error", d).textContent = err.message; btn && (btn.disabled = false); }
  };
  return d;
}

/* ------------------------------------------------------------ views */
async function viewOverview(v) {
  const [s, events] = await Promise.all([Api.request(orgPath("/stats")), Api.request(orgPath("/events"))]);
  const link = `${location.origin}/events.html?org=${S.org.slug}`;
  const upcoming = events.filter(e => e.status === "published" && new Date(e.starts_at) > new Date()).slice(0, 3);
  v.innerHTML = `<div class="page-head"><h1>${esc(S.org.name)}</h1></div>
    <div class="figures">
      <div><b>${s.events}</b><span>Events, ${s.published_events} live</span></div>
      <div><b>${s.tickets_sold}</b><span>Tickets sold</span></div>
      <div><b>${money(s.revenue_cents).replace("Free", "$0.00")}</b><span>Revenue</span></div>
      <div><b>${s.checked_in}</b><span>Checked in</span></div>
      <div><b>${s.pending_registrations}</b><span>Awaiting payment</span></div>
    </div>
    <section class="panel"><h2>Your public ticket page</h2>
      <p class="muted">Attendees can browse your published events and register here. No account needed.</p>
      <div class="copyrow"><input readonly value="${esc(link)}" aria-label="Public page link"><button id="copy" class="ghost">Copy link</button><a class="btn" href="${esc(link)}" target="_blank" rel="noopener">Open page</a></div></section>
    <section><h2 style="margin-bottom:.9rem">Coming up</h2>
      ${upcoming.length ? `<div class="tickets">${upcoming.map(e => ticketHTML(e, { href: `#/events/${e.id}` })).join("")}</div>`
        : `<div class="empty"><h3>Nothing scheduled yet</h3><p>Publish an event and it shows up here and on your public page.</p><a class="btn" href="#/events">Go to events</a></div>`}
    </section>`;
  $("#copy").onclick = () => navigator.clipboard.writeText(link).then(() => toast("Link copied"));
}

async function viewEvents(v) {
  const events = await Api.request(orgPath("/events"));
  v.innerHTML = `<div class="page-head"><h1>Events</h1>${can("admin") ? `<button id="new-ev">New event</button>` : ""}</div>
    ${events.length ? `<div class="tickets">${events.map(e => ticketHTML(e, { href: `#/events/${e.id}` })).join("")}</div>`
      : `<div class="empty"><h3>No events yet</h3><p>${can("admin") ? "Create your first event, add ticket types, then publish it." : "Ask an admin to create an event."}</p></div>`}`;
  if (can("admin")) $("#new-ev").onclick = () => eventDialog();
}

function eventDialog(ev) {
  const local = iso => iso ? new Date(new Date(iso) - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "";
  dialog(`<h2>${ev ? "Edit event" : "New event"}</h2><form id="f">
    <div class="field"><label for="t">Title</label><input id="t" required value="${esc(ev?.title)}"></div>
    <div class="row"><div class="field"><label for="s">Starts</label><input id="s" type="datetime-local" required value="${local(ev?.starts_at)}"></div>
    <div class="field"><label for="en">Ends (optional)</label><input id="en" type="datetime-local" value="${local(ev?.ends_at)}"></div></div>
    <div class="field"><label for="ve">Venue</label><input id="ve" value="${esc(ev?.venue)}"></div>
    <div class="field"><label for="de">Description</label><textarea id="de">${esc(ev?.description)}</textarea></div>
    <p class="error" role="alert"></p><div class="actions"><button>${ev ? "Save changes" : "Create event"}</button><button type="button" class="ghost" data-close>Cancel</button></div></form>`,
    async d => {
      const body = { title: $("#t", d).value, starts_at: new Date($("#s", d).value).toISOString(),
        ends_at: $("#en", d).value ? new Date($("#en", d).value).toISOString() : null, venue: $("#ve", d).value, description: $("#de", d).value };
      const saved = ev ? await Api.request(orgPath(`/events/${ev.id}`), { method: "PATCH", body }) : await Api.request(orgPath("/events"), { method: "POST", body });
      toast(ev ? "Event saved" : "Event created");
      location.hash = `#/events/${saved.id}`; route();
    });
}

async function viewEvent(v, id) {
  const ev = await Api.request(orgPath(`/events/${id}`));
  const regs = can("staff") ? await Api.request(orgPath(`/events/${id}/registrations`)) : [];
  const ttName = Object.fromEntries(ev.ticket_types.map(t => [t.id, t.name]));
  v.innerHTML = `<p><a href="#/events">Back to events</a></p>
    <div class="page-head"><div><span class="badge ${ev.status}">${ev.status}</span><h1 style="margin-top:.4rem">${esc(ev.title)}</h1>
      <p class="muted" style="margin:.3rem 0 0">${esc(fmtDate(ev.starts_at))}${ev.venue ? ", " + esc(ev.venue) : ""}</p></div>
      ${can("admin") ? `<div class="actions">
        ${ev.status !== "published" ? `<button data-st="published">Publish</button>` : `<button class="ghost" data-st="draft">Unpublish</button>`}
        ${ev.status !== "cancelled" ? `<button class="ghost" data-st="cancelled">Cancel event</button>` : ""}
        <button class="ghost" id="edit">Edit</button><button class="danger" id="del">Delete</button></div>` : ""}</div>
    ${ev.description ? `<p>${esc(ev.description)}</p>` : ""}
    <section class="panel"><h2>Ticket types</h2>
      ${ev.ticket_types.length ? `<div class="table-wrap"><table><thead><tr><th>Name</th><th>Price</th><th>Sold</th><th>Capacity</th></tr></thead><tbody>
        ${ev.ticket_types.map(t => `<tr><td>${esc(t.name)}</td><td>${money(t.price_cents)}</td><td>${t.sold}</td><td>${t.capacity}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="muted">No ticket types yet. Add one before publishing.</p>`}
      ${can("admin") ? `<form id="tt-form" class="row" style="margin-top:1rem;align-items:end">
        <div><label for="tn">Name</label><input id="tn" required placeholder="General admission"></div>
        <div><label for="tp">Price (USD)</label><input id="tp" type="number" min="0" step="0.01" value="0" required></div>
        <div><label for="tc">Capacity</label><input id="tc" type="number" min="1" value="100" required></div>
        <div style="flex:0 0 auto"><button>Add ticket type</button></div></form><p class="error" id="tt-err" role="alert"></p>` : ""}</section>
    ${can("staff") ? `<section class="panel"><h2>Registrations (${regs.filter(r => r.status !== "cancelled").length})</h2>
      ${regs.length ? `<div class="table-wrap"><table><thead><tr><th>Attendee</th><th>Ticket</th><th>Qty</th><th>Total</th><th>Status</th><th></th></tr></thead><tbody>
        ${regs.map(r => `<tr><td>${esc(r.attendee_name)}<br><small class="muted">${esc(r.attendee_email)}</small></td><td>${esc(ttName[r.ticket_type_id] || "")}<br><span class="code">${esc(r.code)}</span></td>
          <td>${r.quantity}</td><td>${money(r.total_cents)}</td>
          <td><span class="badge ${r.checked_in_at ? "checked" : r.status}">${r.checked_in_at ? "checked in" : r.status}</span></td>
          <td><div class="actions">
            ${r.status === "confirmed" && !r.checked_in_at ? `<button class="small" data-checkin="${r.id}">Check in</button>` : ""}
            ${can("admin") && r.status !== "cancelled" && !r.checked_in_at ? `<button class="small danger" data-cancel="${r.id}">Cancel</button>` : ""}</div></td></tr>`).join("")}</tbody></table></div>`
        : `<p class="muted">Nobody has registered yet.</p>`}</section>` : ""}`;

  $$("[data-st]", v).forEach(b => b.onclick = async () => {
    try { await Api.request(orgPath(`/events/${id}`), { method: "PATCH", body: { status: b.dataset.st } }); toast("Event " + (b.dataset.st === "published" ? "published" : "updated")); route(); }
    catch (e) { toast(e.message, "bad"); }
  });
  if (can("admin")) {
    $("#edit").onclick = () => eventDialog(ev);
    $("#del").onclick = async () => { if (!confirm("Delete this event permanently?")) return;
      try { await Api.request(orgPath(`/events/${id}`), { method: "DELETE" }); toast("Event deleted"); location.hash = "#/events"; } catch (e) { toast(e.message, "bad"); } };
    $("#tt-form").onsubmit = async e => { e.preventDefault();
      try { await Api.request(orgPath(`/events/${id}/ticket-types`), { method: "POST", body: { name: $("#tn").value, price_cents: Math.round(parseFloat($("#tp").value) * 100), capacity: Number($("#tc").value) } }); toast("Ticket type added"); route(); }
      catch (err) { $("#tt-err").textContent = err.message; } };
  }
  $$("[data-checkin]", v).forEach(b => b.onclick = async () => { try { await Api.request(orgPath(`/registrations/${b.dataset.checkin}/check-in`), { method: "POST" }); toast("Checked in"); route(); } catch (e) { toast(e.message, "bad"); } });
  $$("[data-cancel]", v).forEach(b => b.onclick = async () => { if (!confirm("Cancel this registration and release the seats?")) return;
    try { await Api.request(orgPath(`/registrations/${b.dataset.cancel}/cancel`), { method: "POST" }); toast("Registration cancelled"); route(); } catch (e) { toast(e.message, "bad"); } });
}

async function viewCheckin(v) {
  const recent = [];
  v.innerHTML = `<div class="page-head"><h1>Check-in</h1></div>
    <section class="panel"><form class="scan" id="scan"><label class="sr" for="code">Ticket code</label>
      <input id="code" placeholder="EF-XXXXXXXX" autocomplete="off" autocapitalize="characters" spellcheck="false" autofocus><button>Check in</button></form>
      <div id="res" aria-live="polite"></div></section>
    <section class="panel"><h2>This session</h2><div id="recent"><p class="muted">Checked-in guests appear here.</p></div></section>`;
  $("#scan").onsubmit = async e => {
    e.preventDefault(); const code = $("#code").value.trim(); if (!code) return;
    try {
      const r = await Api.request(orgPath("/check-in"), { method: "POST", body: { code } });
      $("#res").innerHTML = `<div class="result ok"><h3>${esc(r.attendee_name)} is in</h3><p style="margin:0">${r.quantity} ticket${r.quantity > 1 ? "s" : ""}, code <span class="code">${esc(r.code)}</span></p></div>`;
      recent.unshift(r); $("#recent").innerHTML = `<table><tbody>${recent.map(x => `<tr><td>${esc(x.attendee_name)}</td><td><span class="code">${esc(x.code)}</span></td><td>${x.quantity}</td></tr>`).join("")}</tbody></table>`;
    } catch (err) { $("#res").innerHTML = `<div class="result bad"><h3>Not admitted</h3><p style="margin:0">${esc(err.message)}</p></div>`; }
    $("#code").value = ""; $("#code").focus();
  };
}

async function viewTeam(v) {
  const members = await Api.request(orgPath("/members"));
  const ownerCount = members.filter(m => m.role === "owner").length;
  v.innerHTML = `<div class="page-head"><h1>Team</h1></div>
    <section class="panel"><div class="table-wrap"><table><thead><tr><th>Member</th><th>Role</th><th></th></tr></thead><tbody>
      ${members.map(m => { const editable = can("admin") && (S.org.role === "owner" || m.role !== "owner");
        return `<tr><td>${esc(m.full_name)}<br><small class="muted">${esc(m.email)}</small></td><td>
        ${editable ? `<select data-role="${m.user_id}" aria-label="Role for ${esc(m.full_name)}">${["owner", "admin", "staff", "viewer"].filter(r => r !== "owner" || S.org.role === "owner").map(r => `<option ${r === m.role ? "selected" : ""}>${r}</option>`).join("")}</select>` : `<span class="badge">${m.role}</span>`}</td>
        <td><div class="actions">${editable && !(m.role === "owner" && ownerCount < 2) ? `<button class="small danger" data-rm="${m.user_id}">Remove</button>` : ""}</div></td></tr>`; }).join("")}</tbody></table></div></section>
    ${can("admin") ? `<section class="panel"><h2>Add a teammate</h2><p class="muted">They need an EventForge account first. Roles: <b>viewer</b> reads, <b>staff</b> checks guests in, <b>admin</b> manages events and people, <b>owner</b> controls everything.</p>
      <form id="add" class="row" style="align-items:end"><div><label for="me">Email</label><input id="me" type="email" required></div>
      <div><label for="mr">Role</label><select id="mr"><option>staff</option><option>viewer</option><option>admin</option></select></div>
      <div style="flex:0 0 auto"><button>Add member</button></div></form><p class="error" id="add-err" role="alert"></p></section>` : ""}`;
  $$("[data-role]", v).forEach(s => s.onchange = async () => { try { await Api.request(orgPath(`/members/${s.dataset.role}`), { method: "PATCH", body: { role: s.value } }); toast("Role updated"); route(); } catch (e) { toast(e.message, "bad"); route(); } });
  $$("[data-rm]", v).forEach(b => b.onclick = async () => { if (!confirm("Remove this member?")) return; try { await Api.request(orgPath(`/members/${b.dataset.rm}`), { method: "DELETE" }); toast("Member removed"); route(); } catch (e) { toast(e.message, "bad"); } });
  if (can("admin")) $("#add").onsubmit = async e => { e.preventDefault(); try { await Api.request(orgPath("/members"), { method: "POST", body: { email: $("#me").value, role: $("#mr").value } }); toast("Member added"); route(); } catch (err) { $("#add-err").textContent = err.message; } };
}

async function viewActivity(v) {
  if (!can("admin")) { v.innerHTML = `<div class="empty"><h3>Admins only</h3><p>Ask an admin to review activity.</p></div>`; return; }
  const rows = await Api.request(orgPath("/audit?limit=100"));
  v.innerHTML = `<div class="page-head"><h1>Activity</h1></div><section class="panel"><div class="table-wrap"><table><thead><tr><th>When</th><th>Who</th><th>What</th></tr></thead><tbody>
    ${rows.map(r => `<tr><td>${esc(fmtDate(r.created_at))}</td><td>${esc(r.actor_label)}</td><td><span class="code">${esc(r.action)}</span> ${r.meta && Object.keys(r.meta).length ? `<small class="muted">${esc(JSON.stringify(r.meta))}</small>` : ""}</td></tr>`).join("")}</tbody></table></div></section>`;
}

boot();
