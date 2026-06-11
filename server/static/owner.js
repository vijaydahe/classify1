/* ClassifyHub platform owner console */
let TOKEN = localStorage.getItem("ch_owner_token");

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------- Theme (light is the default) ---------- */
function applyTheme() {
  document.body.classList.toggle("light", (localStorage.getItem("ch_theme") || "light") === "light");
}
function toggleTheme() {
  const next = (localStorage.getItem("ch_theme") || "light") === "light" ? "dark" : "light";
  localStorage.setItem("ch_theme", next);
  applyTheme();
}
applyTheme();

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
  if (opts.body) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.body); }
  const resp = await fetch(path, { ...opts, headers });
  // A 401 from the login endpoint means bad credentials, not an expired session.
  if (resp.status === 401 && !path.startsWith("/api/auth/")) {
    logout();
    throw new Error("Session expired");
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || resp.statusText);
  }
  return resp.json();
}

function flash(text, kind = "ok") {
  const el = document.getElementById("view-msg");
  el.className = "msg " + kind;
  el.textContent = text;
  setTimeout(() => { el.className = "msg"; }, 4000);
}

async function doLogin() {
  const msg = document.getElementById("auth-msg");
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: {
        email: document.getElementById("login-email").value.trim(),
        password: document.getElementById("login-password").value,
      },
    });
    if (data.role !== "owner") {
      msg.className = "msg err";
      msg.textContent = "This console is for the platform owner. Tenant users sign in at /";
      return;
    }
    TOKEN = data.access_token;
    localStorage.setItem("ch_owner_token", TOKEN);
    boot();
  } catch (e) { msg.className = "msg err"; msg.textContent = e.message; }
}

function logout() {
  localStorage.removeItem("ch_owner_token");
  TOKEN = null;
  location.reload();
}

function boot() {
  if (!TOKEN) {
    document.getElementById("auth").classList.remove("hidden");
    document.getElementById("app").classList.add("hidden");
    return;
  }
  document.getElementById("auth").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  document.querySelectorAll(".nav-item").forEach(btn =>
    btn.onclick = () => nav(btn.dataset.view));
  nav("overview");
}

function nav(view) {
  document.querySelectorAll(".nav-item").forEach(b =>
    b.classList.toggle("active", b.dataset.view === view));
  views[view]().catch(e => flash(e.message, "err"));
}

function render(html) { document.getElementById("view").innerHTML = html; }

function donutSVG(items, centerLabel) {
  const total = items.reduce((s, i) => s + (i.count || 0), 0);
  if (!total) return '<div class="muted" style="padding:40px 20px;text-align:center">No data yet</div>';
  const C = 2 * Math.PI * 80;
  let off = 0, segs = "";
  for (const i of items) {
    if (!i.count) continue;
    const len = (i.count / total) * C;
    segs += `<circle cx="100" cy="100" r="80" fill="none" stroke="${esc(i.color)}" stroke-width="30"
      stroke-dasharray="${len} ${C}" stroke-dashoffset="${-off}" transform="rotate(-90 100 100)"/>`;
    off += len;
  }
  return `<svg width="200" height="200" viewBox="0 0 200 200" role="img">${segs}
    <text x="100" y="95" text-anchor="middle" font-size="26" font-weight="800" style="fill:var(--text)" font-family="inherit">${total}</text>
    <text x="100" y="116" text-anchor="middle" font-size="11" style="fill:var(--muted)" font-family="inherit">${esc(centerLabel)}</text>
  </svg>`;
}

const PALETTE = ["#4f46e5", "#16a34a", "#d97706", "#dc2626", "#0ea5e9", "#a855f7"];

const views = {
  async overview() {
    const [s, tenants] = await Promise.all([api("/api/owner/stats"), api("/api/owner/tenants")]);
    const byPlan = {};
    tenants.forEach(t => { const k = t.plan || "No plan"; byPlan[k] = (byPlan[k] || 0) + 1; });
    const planItems = Object.entries(byPlan).map(([name, count], i) =>
      ({ name, count, color: PALETTE[i % PALETTE.length] }));
    const statusItems = [
      { name: "Active", count: s.active_tenants, color: "#16a34a" },
      { name: "Suspended", count: s.tenants - s.active_tenants, color: "#dc2626" },
    ];
    const legend = items => items.map(i => `
      <div class="bar-row"><span class="level-dot" style="width:12px;height:12px;border-radius:3px;background:${esc(i.color)};display:inline-block"></span>
        <div class="name" style="width:auto">${esc(i.name)}</div>
        <div style="margin-left:auto;font-weight:700">${i.count}</div></div>`).join("");
    render(`
      <h2>Platform overview</h2>
      <div class="cards">
        <div class="card"><div class="num">${s.tenants}</div><div class="lbl">Tenants (${s.active_tenants} active)</div></div>
        <div class="card"><div class="num">${s.users}</div><div class="lbl">Registered users</div></div>
        <div class="card"><div class="num">${s.assets.toLocaleString()}</div><div class="lbl">Assets classified</div></div>
        <div class="card"><div class="num">${s.endpoints}</div><div class="lbl">Endpoints</div></div>
        <div class="card"><div class="num">$${s.revenue.toLocaleString()}</div><div class="lbl">Revenue (${s.payments} payments)</div></div>
      </div>
      <div class="row" style="align-items:stretch">
        <div class="panel" style="flex:1;min-width:280px">
          <h3>Tenants by plan</h3>
          <div class="donut-flex">
            <div>${donutSVG(planItems, "tenants")}</div>
            <div style="flex:1;min-width:140px">${legend(planItems)}</div>
          </div>
        </div>
        <div class="panel" style="flex:1;min-width:280px">
          <h3>Tenant status</h3>
          <div class="donut-flex">
            <div>${donutSVG(statusItems, "tenants")}</div>
            <div style="flex:1;min-width:140px">${legend(statusItems)}</div>
          </div>
        </div>
      </div>
    `);
  },

  async tenants() {
    const tenants = await api("/api/owner/tenants");
    render(`
      <h2>Tenants</h2>
      <div class="panel">
        <table>
          <tr><th>Name</th><th>Slug</th><th>Plan</th><th>Users</th><th>Assets</th><th>Endpoints</th><th>Status</th><th>Created</th><th></th></tr>
          ${tenants.map(t => `<tr>
            <td>${esc(t.name)}</td><td class="mono">${esc(t.slug)}</td>
            <td><span class="badge badge-outline">${esc(t.plan || "—")}</span></td>
            <td>${t.users}</td><td>${t.assets}</td><td>${t.endpoints}</td>
            <td><span class="badge ${t.status === "active" ? "pill-green" : "pill-red"}">${esc(t.status)}</span></td>
            <td class="muted">${t.created_at.slice(0, 10)}</td>
            <td><button class="btn-sm ${t.status === "active" ? "btn-danger" : "btn-ghost"}"
                 onclick="toggleTenant(${t.id})">${t.status === "active" ? "Suspend" : "Reactivate"}</button></td>
          </tr>`).join("") || "<tr><td colspan=9 class='muted'>No tenants yet</td></tr>"}
        </table>
      </div>
    `);
  },

  async users() {
    const users = await api("/api/owner/users");
    render(`
      <h2>Registered users (all tenants)</h2>
      <div class="panel">
        <table>
          <tr><th>Email</th><th>Name</th><th>Tenant</th><th>Role</th><th>Status</th><th>Registered</th></tr>
          ${users.map(u => `<tr>
            <td>${esc(u.email)}</td><td>${esc(u.full_name)}</td><td>${esc(u.tenant || "—")}</td>
            <td>${esc(u.role)}</td>
            <td><span class="badge ${u.is_active ? "pill-green" : "pill-red"}">${u.is_active ? "active" : "disabled"}</span></td>
            <td class="muted">${u.created_at.slice(0, 10)}</td>
          </tr>`).join("") || "<tr><td colspan=6 class='muted'>No users yet</td></tr>"}
        </table>
      </div>
    `);
  },

  async payments() {
    const payments = await api("/api/owner/payments");
    render(`
      <h2>Payments</h2>
      <div class="panel">
        <table>
          <tr><th>Date</th><th>Tenant</th><th>Plan</th><th>Amount</th><th>Status</th><th>Reference</th></tr>
          ${payments.map(p => `<tr>
            <td class="muted">${p.created_at.replace("T", " ").slice(0, 16)}</td>
            <td>${esc(p.tenant || "—")}</td><td>${esc(p.plan || "—")}</td>
            <td>$${p.amount} ${esc(p.currency)}</td>
            <td><span class="badge ${p.status === "succeeded" ? "pill-green" : "pill-amber"}">${esc(p.status)}</span></td>
            <td class="mono">${esc(p.ref)}</td>
          </tr>`).join("") || "<tr><td colspan=6 class='muted'>No payments yet</td></tr>"}
        </table>
      </div>
    `);
  },

  async plans() {
    const plans = await api("/api/owner/plans");
    render(`
      <h2>Subscription plans</h2>
      <div class="panel">
        <table>
          <tr><th>Plan</th><th>Price / mo</th><th>Max users</th><th>Max endpoints</th><th>Max assets</th><th>Active</th><th></th></tr>
          ${plans.map(p => `<tr>
            <td>${esc(p.name)}</td>
            <td><input class="mono" style="width:90px;margin:0" id="p-price-${p.id}" value="${p.price_monthly}"></td>
            <td><input class="mono" style="width:80px;margin:0" id="p-users-${p.id}" value="${p.max_users}"></td>
            <td><input class="mono" style="width:80px;margin:0" id="p-eps-${p.id}" value="${p.max_endpoints}"></td>
            <td><input class="mono" style="width:100px;margin:0" id="p-assets-${p.id}" value="${p.max_assets}"></td>
            <td><span class="badge ${p.is_active ? "pill-green" : "pill-red"}">${p.is_active ? "yes" : "no"}</span></td>
            <td><button class="btn-sm" onclick="savePlan(${p.id})">Save</button></td>
          </tr>`).join("")}
        </table>
      </div>
    `);
  },

  async messages() {
    const msgs = await api("/api/owner/messages");
    render(`
      <h2>Contact messages</h2>
      <div class="panel">
        <table>
          <tr><th>Date</th><th>From</th><th>Company</th><th>Topic</th><th>Message</th><th>Status</th><th></th></tr>
          ${msgs.map(m => `<tr>
            <td class="muted" style="white-space:nowrap">${m.created_at.replace("T", " ").slice(0, 16)}</td>
            <td>${esc(m.name)}<br><span class="muted">${esc(m.email)}</span></td>
            <td>${esc(m.company || "—")}</td>
            <td><span class="badge badge-outline">${esc(m.topic)}</span></td>
            <td style="max-width:340px;overflow-wrap:anywhere">${esc(m.message)}</td>
            <td><span class="badge ${m.status === "new" ? "pill-amber" : "pill-green"}">${esc(m.status)}</span></td>
            <td><button class="btn-sm btn-ghost" onclick="toggleMessage(${m.id})">
              ${m.status === "new" ? "Mark replied" : "Mark new"}</button></td>
          </tr>`).join("") || "<tr><td colspan=7 class='muted'>No messages yet</td></tr>"}
        </table>
      </div>
    `);
  },

  async gateway() {
    const g = await api("/api/owner/gateway");
    render(`
      <h2>Payment gateway configuration</h2>
      <div class="panel" style="max-width:560px">
        <p class="muted" style="font-size:13px;margin-bottom:16px">
          ${g.configured ? "Gateway is configured." : "No gateway configured yet — checkout runs in mock mode."}
          Secret values are shown masked; re-enter to replace.
        </p>
        <label>Provider</label>
        <select id="g-provider">
          ${["stripe", "razorpay", "paypal"].map(p =>
            `<option ${g.provider === p ? "selected" : ""}>${p}</option>`).join("")}
        </select>
        <label>Mode</label>
        <select id="g-mode">
          <option ${g.mode === "test" ? "selected" : ""}>test</option>
          <option ${g.mode === "live" ? "selected" : ""}>live</option>
        </select>
        <label>Publishable key</label>
        <input id="g-pub" value="${esc(g.publishable_key)}" placeholder="pk_test_...">
        <label>Secret key</label>
        <input id="g-secret" value="${esc(g.secret_key)}" placeholder="sk_test_...">
        <label>Webhook secret</label>
        <input id="g-webhook" value="${esc(g.webhook_secret)}" placeholder="whsec_...">
        <button onclick="saveGateway()">Save configuration</button>
      </div>
    `);
  },
};

async function toggleMessage(id) {
  try {
    await api(`/api/owner/messages/${id}/toggle`, { method: "PATCH" });
    nav("messages");
  } catch (e) { flash(e.message, "err"); }
}

async function toggleTenant(id) {
  try {
    const r = await api(`/api/owner/tenants/${id}/toggle`, { method: "PATCH" });
    flash(`Tenant is now ${r.status}`);
    nav("tenants");
  } catch (e) { flash(e.message, "err"); }
}

async function savePlan(id) {
  try {
    await api(`/api/owner/plans/${id}`, {
      method: "PATCH",
      body: {
        price_monthly: parseFloat(document.getElementById(`p-price-${id}`).value),
        max_users: parseInt(document.getElementById(`p-users-${id}`).value),
        max_endpoints: parseInt(document.getElementById(`p-eps-${id}`).value),
        max_assets: parseInt(document.getElementById(`p-assets-${id}`).value),
      },
    });
    flash("Plan updated");
  } catch (e) { flash(e.message, "err"); }
}

async function saveGateway() {
  try {
    await api("/api/owner/gateway", {
      method: "PUT",
      body: {
        provider: document.getElementById("g-provider").value,
        mode: document.getElementById("g-mode").value,
        publishable_key: document.getElementById("g-pub").value,
        secret_key: document.getElementById("g-secret").value,
        webhook_secret: document.getElementById("g-webhook").value,
      },
    });
    flash("Gateway configuration saved");
    nav("gateway");
  } catch (e) { flash(e.message, "err"); }
}

boot();
