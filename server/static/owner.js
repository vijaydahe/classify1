/* ClassifyHub platform owner console */
let TOKEN = localStorage.getItem("ch_owner_token");

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

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

const views = {
  async overview() {
    const s = await api("/api/owner/stats");
    render(`
      <h2>Platform overview</h2>
      <div class="cards">
        <div class="card"><div class="num">${s.tenants}</div><div class="lbl">Tenants (${s.active_tenants} active)</div></div>
        <div class="card"><div class="num">${s.users}</div><div class="lbl">Registered users</div></div>
        <div class="card"><div class="num">${s.assets.toLocaleString()}</div><div class="lbl">Assets classified</div></div>
        <div class="card"><div class="num">${s.endpoints}</div><div class="lbl">Endpoints</div></div>
        <div class="card"><div class="num">$${s.revenue.toLocaleString()}</div><div class="lbl">Revenue (${s.payments} payments)</div></div>
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
