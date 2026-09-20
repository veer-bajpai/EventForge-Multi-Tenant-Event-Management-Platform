/* Public attendee page: /events.html?org=<slug> — browse, register, pay (demo), look up a ticket. */
const slug = new URLSearchParams(location.search).get("org");
const root = $("#pub");
const pub = (p, opts) => Api.request(p, { auth: false, ...opts });
let DATA = null;

async function load() {
  if (!slug) { root.innerHTML = `<div class="empty"><h3>No organization selected</h3><p>Open this page with <span class="code">?org=your-slug</span>.</p></div>`; return; }
  try { DATA = await pub(`/api/public/${encodeURIComponent(slug)}/events`); }
  catch (e) { root.innerHTML = `<div class="empty"><h3>Organization not found</h3><p>${esc(e.message)}</p></div>`; return; }
  document.title = `${DATA.organization.name} — Events`;
  root.innerHTML = `<header class="public-head"><p class="muted" style="margin-bottom:.4rem">Tickets from</p><h1>${esc(DATA.organization.name)}</h1>
    <form class="find" id="find"><label class="sr" for="fc">Ticket code</label><input id="fc" placeholder="Already booked? Enter your code"><button class="ghost" type="submit">Find ticket</button></form></header>
    <div id="list" class="tickets"></div>`;
  $("#list").innerHTML = DATA.events.length ? DATA.events.map(e => `<div>${ticketHTML({ ...e, status: "", ticket_types: [] }, { stub: "public" })}
      <div class="actions" style="padding:.6rem .4rem 0"><button data-reg="${e.id}">Get tickets</button>
      <span class="muted">${e.ticket_types.map(t => `${esc(t.name)}: ${money(t.price_cents)}`).join(", ")}</span></div></div>`).join("")
    : `<div class="empty"><h3>No upcoming events</h3><p>Check back soon.</p></div>`;
  $$("[data-reg]").forEach(b => b.onclick = () => registerDialog(DATA.events.find(e => e.id === Number(b.dataset.reg))));
  $("#find").onsubmit = async e => { e.preventDefault(); const c = $("#fc").value.trim(); if (!c) return;
    try { showPass(await pub(`/api/public/registrations/${encodeURIComponent(c)}`)); } catch (err) { toast(err.message, "bad"); } };
}

function modal(html) {
  const d = document.createElement("dialog"); d.innerHTML = html; document.body.append(d); d.showModal();
  d.addEventListener("close", () => d.remove()); $$("[data-close]", d).forEach(b => b.onclick = () => d.close()); return d;
}

function registerDialog(ev) {
  const d = modal(`<h2>${esc(ev.title)}</h2><form id="rf">
    <fieldset style="border:0;padding:0;margin:0 0 1rem"><legend class="sr">Ticket type</legend>
      ${ev.ticket_types.map((t, i) => `<label class="tt-option ${t.remaining ? "" : "soldout"}"><span><input type="radio" name="tt" value="${t.id}" ${t.remaining && !ev.ticket_types.slice(0, i).some(x => x.remaining) ? "checked" : ""} ${t.remaining ? "" : "disabled"}>${esc(t.name)}</span>
      <span>${money(t.price_cents)}${t.remaining ? `<small class="muted"> · ${t.remaining} left</small>` : ` <small>Sold out</small>`}</span></label>`).join("")}</fieldset>
    <div class="field"><label for="an">Full name</label><input id="an" required autocomplete="name"></div>
    <div class="field"><label for="ae">Email</label><input id="ae" type="email" required autocomplete="email"></div>
    <div class="field"><label for="aq">Tickets</label><input id="aq" type="number" min="1" max="10" value="1"></div>
    <p class="error" id="re" role="alert"></p>
    <div class="actions"><button>Reserve tickets</button><button type="button" class="ghost" data-close>Close</button></div></form>`);
  $("#rf", d).onsubmit = async e => {
    e.preventDefault(); const btn = e.submitter; btn.disabled = true;
    const tt = $("input[name=tt]:checked", d);
    if (!tt) { $("#re", d).textContent = "Choose a ticket type."; btn.disabled = false; return; }
    try {
      const reg = await pub(`/api/public/${slug}/events/${ev.id}/register`, { method: "POST", body: { ticket_type_id: Number(tt.value), attendee_name: $("#an", d).value, attendee_email: $("#ae", d).value, quantity: Number($("#aq", d).value) } });
      d.close(); showPass(reg); load();
    } catch (err) { $("#re", d).textContent = err.message; btn.disabled = false; }
  };
}

function showPass(reg) {
  const paid = reg.status === "confirmed", pending = reg.status === "pending";
  const d = modal(`<div class="pass"><span class="badge ${reg.status}">${esc(reg.status)}</span>
    <h2 style="margin-top:.6rem">${esc(reg.event_title)}</h2>
    <p class="muted" style="margin:.2rem auto">${esc(fmtDate(reg.event_starts_at))}${reg.venue ? ", " + esc(reg.venue) : ""}</p>
    <span class="code">${esc(reg.code)}</span>
    <p style="margin:0 auto">${esc(reg.attendee_name)}, ${reg.quantity} × ${esc(reg.ticket_name)}${reg.total_cents ? ` (${money(reg.total_cents)})` : ""}</p>
    ${reg.checked_in ? `<p class="muted" style="margin:.6rem auto 0">Checked in.</p>` : ""}</div>
    <p class="error" id="pe" role="alert" style="margin-top:.8rem"></p>
    <div class="actions" style="margin-top:.6rem;justify-content:center">
      ${pending ? `<button id="pay">Pay ${money(reg.total_cents)}</button>` : ""}<button class="ghost" data-close>Close</button></div>
    ${paid ? `<p class="muted" style="text-align:center;margin:.8rem auto 0">Show this code at the door. Save it, or look it up here later.</p>` : ""}
    ${pending ? `<p class="muted" style="text-align:center;margin:.8rem auto 0">Seats are held for 15 minutes. Pay to confirm your tickets.</p>` : ""}`);
  const pay = $("#pay", d);
  if (pay) pay.onclick = async () => {
    pay.disabled = true;
    try {
      const intent = await pub(`/api/public/registrations/${reg.code}/pay`, { method: "POST" });
      if (!intent.demo_mode) { $("#pe", d).textContent = "Redirect to your payment provider here."; return; }
      await pub(`/api/public/payments/${intent.payment_ref}/confirm-demo`, { method: "POST" });
      d.close(); showPass(await pub(`/api/public/registrations/${reg.code}`)); toast("Payment received (demo)");
    } catch (err) { $("#pe", d).textContent = err.message; pay.disabled = false; }
  };
}

load();
