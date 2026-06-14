/* ClassifyHub tenant app + admin console */
const S = {
  token: localStorage.getItem("ch_token"),
  role: localStorage.getItem("ch_role"),
  tenant: localStorage.getItem("ch_tenant"),
  name: localStorage.getItem("ch_name"),
  labels: [],
};

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
  if (S.token) headers["Authorization"] = "Bearer " + S.token;
  if (opts.body && !(opts.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
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
  const ct = resp.headers.get("content-type") || "";
  return ct.includes("json") ? resp.json() : resp;
}

function flash(text, kind = "ok") {
  const el = document.getElementById("view-msg");
  el.className = "msg " + kind;
  el.textContent = text;
  setTimeout(() => { el.className = "msg"; }, 4000);
}

/* ---------- Auth ---------- */
function showLogin() {
  document.getElementById("login-form").classList.remove("hidden");
  document.getElementById("register-form").classList.add("hidden");
}
function showRegister() {
  document.getElementById("login-form").classList.add("hidden");
  document.getElementById("register-form").classList.remove("hidden");
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
    onAuth(data);
  } catch (e) { msg.className = "msg err"; msg.textContent = e.message; }
}

async function doRegister() {
  const msg = document.getElementById("reg-msg");
  const email = document.getElementById("reg-email").value.trim();
  try {
    await api("/api/auth/register", {
      method: "POST",
      body: {
        company_name: document.getElementById("reg-company").value.trim(),
        full_name: document.getElementById("reg-name").value.trim(),
        email,
        password: document.getElementById("reg-password").value,
      },
    });
    // Registration done — hand the user to the login form to sign in themselves.
    showLogin();
    document.getElementById("login-email").value = email;
    const authMsg = document.getElementById("auth-msg");
    authMsg.className = "msg ok";
    authMsg.textContent = "Account created! Sign in with your email and password.";
    document.getElementById("login-password").focus();
  } catch (e) { msg.className = "msg err"; msg.textContent = e.message; }
}

async function demoLogin() {
  const msg = document.getElementById("auth-msg");
  try {
    const data = await api("/api/auth/demo", { method: "POST" });
    onAuth(data);
  } catch (e) { msg.className = "msg err"; msg.textContent = e.message; }
}

function onAuth(data) {
  if (data.role === "owner") {
    alert("Platform owners sign in at /owner");
    return;
  }
  S.token = data.access_token; S.role = data.role;
  S.tenant = data.tenant_name || ""; S.name = data.full_name || "";
  localStorage.setItem("ch_token", S.token);
  localStorage.setItem("ch_role", S.role);
  localStorage.setItem("ch_tenant", S.tenant);
  localStorage.setItem("ch_name", S.name);
  boot();
}

function logout() {
  ["ch_token", "ch_role", "ch_tenant", "ch_name"].forEach(k => localStorage.removeItem(k));
  S.token = null;
  WM.cfg = null; renderWatermark();
  location.reload();
}

/* ---------- Screen watermark ---------- */
const WM = { identity: "", cfg: null, label: "" };

function setWatermarkLabel(label) {
  WM.label = label || "";
  renderWatermark();
}

function watermarkText() {
  const parts = [WM.identity];
  if (WM.cfg && WM.cfg.show_classification && WM.label) parts.push(WM.label);
  if (WM.cfg && WM.cfg.show_timestamp) {
    const d = new Date();
    parts.push(d.toISOString().slice(0, 16).replace("T", " "));
  }
  return parts.filter(Boolean).join("  ·  ");
}

function renderWatermark() {
  const el = document.getElementById("watermark");
  if (!el) return;
  const c = WM.cfg;
  if (!c || !c.enabled || !S.token) { el.className = ""; el.innerHTML = ""; return; }
  const text = esc(watermarkText());
  el.style.opacity = c.opacity;
  el.style.fontSize = c.font_size + "px";
  if (c.placement === "tiled") {
    const stepX = Math.max(220, c.font_size * 16);
    const stepY = Math.max(120, c.font_size * 6);
    let tiles = "";
    for (let y = -40; y < window.innerHeight + 80; y += stepY)
      for (let x = -80; x < window.innerWidth + 80; x += stepX)
        tiles += `<span class="wm-tile" style="left:${x}px;top:${y}px">${text}</span>`;
    el.innerHTML = tiles;
  } else {
    const pos = {
      "center": "top:50%;left:50%;transform:translate(-50%,-50%) rotate(-30deg);text-align:center",
      "top-left": "top:14px;left:16px", "top-right": "top:14px;right:16px",
      "bottom-left": "bottom:14px;left:16px", "bottom-right": "bottom:14px;right:16px",
    }[c.placement] || "top:50%;left:50%;transform:translate(-50%,-50%)";
    el.innerHTML = `<span class="wm-fixed" style="${pos}">${text}</span>`;
  }
  el.className = "on";
}

async function loadWatermark() {
  try {
    const w = await api("/api/auth/watermark");
    WM.identity = w.identity;
    WM.cfg = w.config;
    renderWatermark();
  } catch (e) { /* non-fatal */ }
}

let _wmResize;
window.addEventListener("resize", () => {
  clearTimeout(_wmResize);
  _wmResize = setTimeout(renderWatermark, 200);
});
// Refresh the timestamp every minute so a screenshot always shows the access time.
setInterval(() => { if (WM.cfg && WM.cfg.show_timestamp) renderWatermark(); }, 60000);

/* ---------- Shell ---------- */
function boot() {
  if (!S.token) {
    document.getElementById("auth").classList.remove("hidden");
    document.getElementById("app").classList.add("hidden");
    // /app#register deep-links to signup; /app#demo opens the shared demo workspace
    if (location.hash === "#register") showRegister();
    if (location.hash === "#demo") demoLogin();
    return;
  }
  document.getElementById("auth").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  document.getElementById("who-name").textContent = S.name || "User";
  document.getElementById("who-tenant").textContent = `${S.tenant} · ${S.role}`;
  if (S.role === "admin") document.getElementById("admin-nav").classList.remove("hidden");
  document.querySelectorAll(".nav-item").forEach(btn =>
    btn.onclick = () => nav(btn.dataset.view));
  loadWatermark();
  nav(S.role === "admin" ? "dashboard" : "classify");
}

function nav(view) {
  document.querySelectorAll(".nav-item").forEach(b =>
    b.classList.toggle("active", b.dataset.view === view));
  // Default watermark context per screen; classify results refine it further.
  setWatermarkLabel({ assets: "Asset Inventory", dashboard: "Dashboard",
    classify: "Classifying" }[view] || "");
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

async function loadLabels() {
  if (S.role === "admin") S.labels = await api("/api/admin/labels");
  return S.labels;
}

/* ---------- Views ---------- */
const views = {
  async dashboard() {
    if (S.role !== "admin") return views.classify();
    const d = await api("/api/admin/dashboard");
    const maxCount = Math.max(1, ...d.by_label.map(l => l.count));
    render(`
      <h2>Dashboard</h2>
      <div class="cards">
        <div class="card"><div class="num">${d.assets_total}</div><div class="lbl">Total assets</div></div>
        <div class="card"><div class="num">${d.assets_last_7d}</div><div class="lbl">Classified (7 days)</div></div>
        <div class="card"><div class="num">${d.endpoints}</div><div class="lbl">Endpoints</div></div>
        <div class="card"><div class="num">${d.users}</div><div class="lbl">Users</div></div>
        <div class="card"><div class="num">${d.rules}</div><div class="lbl">Active rules</div></div>
        <div class="card"><div class="num">${esc(d.plan || "—")}</div><div class="lbl">Current plan</div></div>
      </div>
      <div class="panel">
        <h3>Assets by classification</h3>
        <div class="donut-flex">
          <div>${donutSVG(d.by_label, "assets")}</div>
          <div style="flex:1;min-width:240px">
            ${d.by_label.map(l => `
              <div class="bar-row">
                <div class="name">${esc(l.name)}</div>
                <div class="bar-track"><div class="bar-fill" style="width:${(l.count / maxCount) * 100}%;background:${esc(l.color)}"></div></div>
                <div style="width:40px;text-align:right">${l.count}</div>
              </div>`).join("")}
          </div>
        </div>
      </div>
      ${d.plan_limits ? `<div class="panel"><h3>Plan limits</h3>
        <span class="badge badge-outline">Users: ${d.users}/${d.plan_limits.max_users}</span>
        <span class="badge badge-outline">Endpoints: ${d.endpoints}/${d.plan_limits.max_endpoints}</span>
        <span class="badge badge-outline">Assets: ${d.assets_total}/${d.plan_limits.max_assets}</span>
      </div>` : ""}
    `);
  },

  async classify() {
    render(`
      <h2>Classify an asset</h2>
      <div class="panel">
        <div class="row">
          <div><label>Asset name</label><input id="c-name" placeholder="Q3-payroll.xlsx"></div>
          <div><label>Type</label>
            <select id="c-type">
              <option>document</option><option>spreadsheet</option><option>database</option>
              <option>email</option><option>source code</option><option>other</option>
            </select></div>
        </div>
        <label>Content / description (optional — improves accuracy)</label>
        <textarea id="c-content" rows="6" placeholder="Paste content or describe the asset..."></textarea>
        <button onclick="classifyNow()">Classify</button>
        <div id="c-result" style="margin-top:16px"></div>
      </div>
      <div class="panel">
        <h3>Bulk classify from CSV</h3>
        <p class="muted" style="font-size:13px;margin-bottom:10px">
          Columns: <span class="mono">name</span> (required), <span class="mono">asset_type</span>, <span class="mono">content</span>
        </p>
        <input type="file" id="csv-file" accept=".csv">
        <button class="btn-ghost" onclick="uploadCsv()">Upload &amp; classify</button>
      </div>
    `);
  },

  async assets() {
    const list = await api("/api/assets");
    render(`
      <h2>Asset inventory</h2>
      <div class="row" style="margin-bottom:14px">
        <input id="a-q" class="fixed" style="width:240px" placeholder="Search by name...">
        <button class="btn-ghost fixed" onclick="searchAssets()">Search</button>
        <span style="flex:1"></span>
        <button class="btn-ghost fixed" onclick="exportAssets()">Export CSV</button>
      </div>
      <div class="panel">${assetTable(list)}</div>
    `);
  },

  async rules() {
    const [rules, labels] = await Promise.all([api("/api/admin/rules"), loadLabels()]);
    render(`
      <h2>Classification rules</h2>
      <div class="panel">
        <h3>Add rule</h3>
        <div class="row">
          <div><label>Name</label><input id="r-name" placeholder="Customer PII"></div>
          <div><label>Type</label><select id="r-type"><option value="keyword">keyword</option><option value="regex">regex</option></select></div>
          <div><label>Label</label><select id="r-label">${labels.map(l => `<option value="${l.id}">${esc(l.name)}</option>`).join("")}</select></div>
          <div class="fixed" style="width:90px"><label>Priority</label><input id="r-priority" type="number" value="100"></div>
        </div>
        <label>Pattern (keywords comma-separated, or a regex)</label>
        <input id="r-pattern" placeholder="customer list,crm export">
        <button onclick="addRule()">Add rule</button>
      </div>
      <div class="panel">
        <table>
          <tr><th>Priority</th><th>Name</th><th>Type</th><th>Pattern</th><th>Label</th><th>Status</th><th></th></tr>
          ${rules.map(r => {
            const label = labels.find(l => l.id === r.label_id);
            return `<tr>
              <td>${r.priority}</td><td>${esc(r.name)}</td><td>${esc(r.rule_type)}</td>
              <td class="mono" style="max-width:280px;overflow-wrap:anywhere">${esc(r.pattern)}</td>
              <td><span class="badge" style="background:${esc(label?.color || "#6b7280")}">${esc(label?.name || "?")}</span></td>
              <td><span class="badge ${r.enabled ? "pill-green" : "pill-red"}">${r.enabled ? "enabled" : "disabled"}</span></td>
              <td style="white-space:nowrap">
                <button class="btn-sm btn-ghost" onclick="toggleRule(${r.id},${!r.enabled})">${r.enabled ? "Disable" : "Enable"}</button>
                <button class="btn-sm btn-danger" onclick="deleteRule(${r.id})">Delete</button>
              </td></tr>`;
          }).join("")}
        </table>
      </div>
    `);
  },

  async labels() {
    const labels = await loadLabels();
    render(`
      <h2>Classification labels</h2>
      <div class="panel">
        <h3>Add label</h3>
        <div class="row">
          <div><label>Name</label><input id="l-name" placeholder="Top Secret"></div>
          <div class="fixed" style="width:120px"><label>Sensitivity level</label><input id="l-level" type="number" value="4"></div>
          <div class="fixed" style="width:90px"><label>Color</label><input id="l-color" type="color" value="#a855f7" style="height:38px;padding:4px"></div>
          <div><label>Description</label><input id="l-desc" placeholder="Optional"></div>
          <button class="fixed" onclick="addLabel()">Add</button>
        </div>
      </div>
      <div class="panel">
        <table>
          <tr><th>Level</th><th>Label</th><th>Description</th><th></th></tr>
          ${labels.map(l => `<tr>
            <td>${l.level}</td>
            <td><span class="badge" style="background:${esc(l.color)}">${esc(l.name)}</span></td>
            <td class="muted">${esc(l.description)}</td>
            <td><button class="btn-sm btn-danger" onclick="deleteLabel(${l.id})">Delete</button></td>
          </tr>`).join("")}
        </table>
      </div>
    `);
  },

  async users() {
    const users = await api("/api/admin/users");
    render(`
      <h2>Users</h2>
      <div class="panel">
        <h3>Invite user</h3>
        <div class="row">
          <div><label>Email</label><input id="u-email" type="email"></div>
          <div><label>Name</label><input id="u-name"></div>
          <div><label>Temp password</label><input id="u-password" type="text" placeholder="min 8 chars"></div>
          <div class="fixed" style="width:110px"><label>Role</label><select id="u-role"><option>user</option><option>admin</option></select></div>
          <button class="fixed" onclick="addUser()">Create</button>
        </div>
      </div>
      <div class="panel">
        <table>
          <tr><th>Email</th><th>Name</th><th>Role</th><th>Status</th><th>Joined</th><th></th></tr>
          ${users.map(u => `<tr>
            <td>${esc(u.email)}</td><td>${esc(u.full_name)}</td><td>${esc(u.role)}</td>
            <td><span class="badge ${u.is_active ? "pill-green" : "pill-red"}">${u.is_active ? "active" : "disabled"}</span></td>
            <td class="muted">${u.created_at.slice(0, 10)}</td>
            <td><button class="btn-sm btn-ghost" onclick="toggleUser(${u.id})">${u.is_active ? "Disable" : "Enable"}</button></td>
          </tr>`).join("")}
        </table>
      </div>
    `);
  },

  async endpoints() {
    const [builds, endpoints] = await Promise.all([
      api("/api/admin/builds"), api("/api/admin/endpoints")]);
    render(`
      <h2>Endpoints &amp; agent builds</h2>
      <div class="panel">
        <h3>Create endpoint agent build</h3>
        <p class="muted" style="font-size:13px;margin-bottom:12px">
          Generates a downloadable agent package pre-configured with an enrollment token for your tenant.
          Install it on endpoints to auto-scan and classify files.
        </p>
        <div class="row">
          <div class="fixed" style="width:160px"><label>Platform</label>
            <select id="b-platform"><option value="macos">macOS</option><option value="windows">Windows</option></select></div>
          <button class="fixed" onclick="createBuild()">Generate build</button>
        </div>
      </div>
      <div class="panel">
        <h3>Builds</h3>
        <table>
          <tr><th>Platform</th><th>Version</th><th>Enrollment token</th><th>Created</th><th>Downloads</th><th></th></tr>
          ${builds.map(b => `<tr>
            <td>${b.platform === "macos" ? "🍎 macOS" : "🪟 Windows"}</td>
            <td>${esc(b.version)}</td>
            <td class="mono">${esc(b.enrollment_token.slice(0, 18))}…</td>
            <td class="muted">${b.created_at.slice(0, 10)}</td>
            <td>${b.downloads}</td>
            <td><button class="btn-sm" onclick="downloadBuild(${b.id})">Download .zip</button></td>
          </tr>`).join("") || "<tr><td colspan=6 class='muted'>No builds yet</td></tr>"}
        </table>
      </div>
      <div class="panel">
        <h3>Enrolled endpoints</h3>
        <table>
          <tr><th>Hostname</th><th>Platform</th><th>Status</th><th>Enrolled</th><th>Last seen</th></tr>
          ${endpoints.map(e => `<tr>
            <td>${esc(e.hostname)}</td><td>${esc(e.platform)}</td>
            <td><span class="badge pill-green">${esc(e.status)}</span></td>
            <td class="muted">${e.enrolled_at.slice(0, 10)}</td>
            <td class="muted">${e.last_seen ? e.last_seen.replace("T", " ").slice(0, 16) : "never"}</td>
          </tr>`).join("") || "<tr><td colspan=5 class='muted'>No endpoints enrolled yet</td></tr>"}
        </table>
      </div>
    `);
  },

  async apikeys() {
    const sub = await api("/api/billing/subscription");
    const paid = sub.plan && sub.plan.price_monthly > 0 && sub.status === "active";
    if (!paid) {
      render(`
        <h2>API access</h2>
        <div class="panel" style="max-width:560px">
          <h3>🔒 API access is a paid-plan feature</h3>
          <p class="muted" style="font-size:14px;margin-bottom:14px">
            Connect ClassifyHub to your own systems — ticketing tools, DLP pipelines, CI jobs —
            with workspace-scoped API keys. Available on the <strong>Pro</strong> and
            <strong>Enterprise</strong> plans.</p>
          <p class="muted" style="font-size:14px;margin-bottom:16px">
            Read the <a href="/api-docs" target="_blank">API guide</a> to see what you could build.</p>
          <button onclick="nav('billing')">Upgrade plan →</button>
        </div>
      `);
      return;
    }
    const keys = await api("/api/admin/apikeys");
    render(`
      <h2>API access</h2>
      <div id="new-key-box"></div>
      <div class="panel">
        <h3>Create API key</h3>
        <p class="muted" style="font-size:13px;margin-bottom:12px">
          Name the key after the integration that will use it. The full key is shown
          <strong>once</strong> — store it in your secret manager. Full usage instructions:
          <a href="/api-docs" target="_blank">API guide</a>.</p>
        <div class="row">
          <div><label>Key name</label><input id="k-name" placeholder="jira-sync"></div>
          <button class="fixed" onclick="createApiKey()">Create key</button>
        </div>
      </div>
      <div class="panel">
        <h3>Your keys</h3>
        <table>
          <tr><th>Name</th><th>Key</th><th>Created</th><th>Last used</th><th>Status</th><th></th></tr>
          ${keys.map(k => `<tr>
            <td>${esc(k.name)}</td>
            <td class="mono">${esc(k.key_prefix)}</td>
            <td class="muted">${k.created_at.slice(0, 10)}</td>
            <td class="muted">${k.last_used ? k.last_used.replace("T", " ").slice(0, 16) : "never"}</td>
            <td><span class="badge ${k.revoked ? "pill-red" : "pill-green"}">${k.revoked ? "revoked" : "active"}</span></td>
            <td>${k.revoked ? "" : `<button class="btn-sm btn-danger" onclick="revokeApiKey(${k.id})">Revoke</button>`}</td>
          </tr>`).join("") || "<tr><td colspan=6 class='muted'>No keys yet</td></tr>"}
        </table>
      </div>
      <div class="panel">
        <h3>Quick start</h3>
        <pre class="mono" style="background:var(--bg);padding:14px;border-radius:8px;overflow-x:auto;font-size:12px">curl -X POST ${location.origin}/api/v1/classify \\
  -H "X-API-Key: chk_your_key_here" \\
  -H "Content-Type: application/json" \\
  -d '{"name": "contract.pdf", "content": "Confidential — NDA"}'</pre>
      </div>
    `);
  },

  async watermark() {
    const c = await api("/api/admin/watermark");
    const opts = ["tiled", "center", "top-left", "top-right", "bottom-left", "bottom-right"];
    render(`
      <h2>Screen watermark</h2>
      <div class="panel" style="max-width:620px">
        <p class="muted" style="font-size:13.5px;margin-bottom:16px">
          Overlays every workspace screen with the viewer's name, the asset classification and a
          timestamp — deterring and attributing screenshots of sensitive data. Applies to all users
          in your workspace the next time they load the app.</p>
        <div class="slider-row">
          <label>Enabled</label>
          <input type="checkbox" id="wm-enabled" ${c.enabled ? "checked" : ""} style="width:auto;flex:0">
          <span class="val"></span>
        </div>
        <div class="slider-row">
          <label>Opacity</label>
          <input type="range" id="wm-opacity" min="0.03" max="0.6" step="0.01" value="${c.opacity}">
          <span class="val" id="wm-opacity-v">${c.opacity}</span>
        </div>
        <div class="slider-row">
          <label>Text size</label>
          <input type="range" id="wm-size" min="10" max="48" step="1" value="${c.font_size}">
          <span class="val" id="wm-size-v">${c.font_size}px</span>
        </div>
        <label>Placement</label>
        <select id="wm-placement">
          ${opts.map(o => `<option value="${o}" ${c.placement === o ? "selected" : ""}>${o}</option>`).join("")}
        </select>
        <div class="slider-row">
          <label>Show classification</label>
          <input type="checkbox" id="wm-class" ${c.show_classification ? "checked" : ""} style="width:auto;flex:0">
        </div>
        <div class="slider-row">
          <label>Show timestamp</label>
          <input type="checkbox" id="wm-ts" ${c.show_timestamp ? "checked" : ""} style="width:auto;flex:0">
        </div>
        <label>Live preview</label>
        <div class="wm-preview" id="wm-preview"></div>
        <button style="margin-top:16px" onclick="saveWatermark()">Save watermark settings</button>
      </div>
    `);
    ["wm-opacity", "wm-size", "wm-placement", "wm-enabled", "wm-class", "wm-ts"].forEach(id =>
      document.getElementById(id).addEventListener("input", watermarkPreview));
    watermarkPreview();
  },

  async stamp() {
    const p = await api("/api/admin/stamp-policy");
    render(`
      <h2>Document stamping</h2>
      <div class="panel" style="max-width:640px">
        <p class="muted" style="font-size:13.5px;margin-bottom:16px">
          Stamp the classification label into the header or footer of documents (Word &amp; PDF).
          Turn on <strong>mandatory</strong> stamping to require it before sharing — enforced inside Word by
          the ClassifyHub add-in, and by the endpoint stamping tool. Named users can be exempted.</p>
        <div class="slider-row">
          <label>Enabled</label>
          <input type="checkbox" id="sp-enabled" ${p.enabled ? "checked" : ""} style="width:auto;flex:0">
        </div>
        <div class="slider-row">
          <label>Mandatory (block unstamped)</label>
          <input type="checkbox" id="sp-mandatory" ${p.mandatory ? "checked" : ""} style="width:auto;flex:0">
        </div>
        <label>Placement</label>
        <select id="sp-placement">
          <option value="footer" ${p.placement === "footer" ? "selected" : ""}>Footer</option>
          <option value="header" ${p.placement === "header" ? "selected" : ""}>Header</option>
        </select>
        <div class="row">
          <div><label>Font name</label><input id="sp-font" value="${esc(p.font_name)}"></div>
          <div class="fixed" style="width:110px"><label>Font size (pt)</label><input id="sp-size" type="number" value="${p.font_size}"></div>
          <div class="fixed" style="width:90px"><label>Colour</label><input id="sp-color" type="color" value="${esc(p.color)}" style="height:38px;padding:4px"></div>
        </div>
        <label>Stamp text (use <span class="mono">{label}</span> for the classification)</label>
        <input id="sp-template" value="${esc(p.text_template)}">
        <label>Exempt users (emails, one per line — admin-granted exceptions)</label>
        <textarea id="sp-exempt" rows="3" placeholder="ceo@company.com">${esc(p.exempt_emails)}</textarea>
        <div id="sp-preview" style="margin:6px 0 14px;padding:14px;border:1px dashed var(--border);border-radius:8px;text-align:center"></div>
        <button onclick="saveStamp()">Save stamping policy</button>
      </div>
      <div class="panel" style="max-width:640px">
        <h3>Enforce in Microsoft 365 (desktop &amp; web)</h3>
        <p class="muted" style="font-size:13.5px;margin-bottom:12px">
          One Office add-in covers Word, Excel, PowerPoint and Outlook on <strong>desktop, Mac and
          the web (Office 365 online)</strong>. Outlook <strong>blocks sending an unclassified email</strong>.
          Deploy these manifests org-wide via <em>Microsoft 365 admin center → Integrated apps</em>
          (or sideload to test).</p>
        <table>
          <tr><th>App</th><th>Manifest URL</th></tr>
          <tr><td>Word / Excel / PowerPoint (desktop + web)</td>
            <td class="mono"><a href="${location.origin}/office-addin/manifest-office.xml" target="_blank">${location.origin}/office-addin/manifest-office.xml</a></td></tr>
          <tr><td>Outlook — desktop + web (send enforcement)</td>
            <td class="mono"><a href="${location.origin}/office-addin/manifest-outlook.xml" target="_blank">${location.origin}/office-addin/manifest-outlook.xml</a></td></tr>
        </table>
      </div>
      <div class="panel" style="max-width:640px">
        <h3>Add-in token</h3>
        <p class="muted" style="font-size:13px;margin-bottom:10px">
          Paste this into the Office or Google Workspace add-in's connection settings so it can
          auto-classify documents against your rules. It identifies you for this session — treat it
          like a password.</p>
        <div class="row">
          <input class="mono" id="addin-token" readonly value="${esc(S.token || "")}">
          <button class="fixed btn-ghost" onclick="navigator.clipboard.writeText(document.getElementById('addin-token').value).then(()=>flash('Token copied'))">Copy</button>
        </div>
      </div>
      <div class="panel" style="max-width:640px">
        <h3>Enforce in Google Workspace</h3>
        <p class="muted" style="font-size:13.5px;margin-bottom:10px">
          A Google Workspace add-on stamps Google Docs, Sheets, Slides and Gmail (subject + body at
          compose). Deploy the <span class="mono">google-workspace/</span> Apps Script project from the
          repository, or publish it privately to your domain via the Google Workspace Marketplace SDK.</p>
        <p class="muted" style="font-size:12.5px">
          Note: Google gives add-ons no cancellable save/send event, so on Google it is stamp-on-demand
          + policy + audit (no hard send-block — that is a Google platform limit). Hard DLP on Google is
          set at the Workspace admin / Drive DLP layer.</p>
      </div>
      <div class="panel" style="max-width:640px">
        <h3>Coverage summary</h3>
        <table>
          <tr><th>Platform</th><th>Stamp</th><th>Force before save/send</th></tr>
          <tr><td>Outlook (desktop + web)</td><td>✅ subject</td><td>✅ blocks send</td></tr>
          <tr><td>Word / Excel / PowerPoint (desktop + web)</td><td>✅ header/footer</td><td>⚠️ warn only*</td></tr>
          <tr><td>Google Docs / Sheets / Slides</td><td>✅ header/footer/banner</td><td>⚠️ stamp-on-demand</td></tr>
          <tr><td>Gmail</td><td>✅ subject + body</td><td>⚠️ stamp-on-demand</td></tr>
          <tr><td>PDF / text / other files</td><td>✅ endpoint agent</td><td>after-the-fact</td></tr>
        </table>
        <p class="muted" style="font-size:12px;margin-top:8px">
          * A true Save-block inside Word/Excel/PowerPoint needs the Windows COM/VSTO add-in (roadmap).
          Only Outlook exposes a cancellable send event across vendors.</p>
      </div>
    `);
    ["sp-font", "sp-size", "sp-color", "sp-template"].forEach(id =>
      document.getElementById(id).addEventListener("input", stampPreview));
    stampPreview();
  },

  async billing() {
    const [plans, sub, payments] = await Promise.all([
      api("/api/billing/plans"), api("/api/billing/subscription"), api("/api/billing/payments")]);
    render(`
      <h2>Billing</h2>
      <div class="panel">
        <h3>Current plan: <span class="badge" style="background:var(--accent)">${esc(sub.plan?.name || "None")}</span></h3>
      </div>
      <div class="cards">
        ${plans.map(p => `
          <div class="card">
            <div class="num">$${p.price_monthly}<span class="muted" style="font-size:13px">/mo</span></div>
            <div class="lbl" style="font-weight:600;color:var(--text)">${esc(p.name)}</div>
            <div class="lbl">${p.max_users} users · ${p.max_endpoints} endpoints<br>${p.max_assets.toLocaleString()} assets</div>
            ${sub.plan?.id === p.id
              ? '<div style="margin-top:10px"><span class="badge pill-green">current</span></div>'
              : `<button class="btn-sm" style="margin-top:10px" onclick="choosePlan(${p.id},${p.price_monthly})">Choose</button>`}
          </div>`).join("")}
      </div>
      <div id="checkout" class="panel hidden">
        <h3>Checkout</h3>
        <div class="row">
          <div><label>Card number</label><input id="pay-card" placeholder="4242 4242 4242 4242"></div>
          <div class="fixed" style="width:100px"><label>Expiry</label><input id="pay-exp" placeholder="12/27"></div>
          <div class="fixed" style="width:80px"><label>CVC</label><input id="pay-cvc" placeholder="123"></div>
          <button class="fixed" onclick="confirmPlan()">Pay &amp; subscribe</button>
        </div>
      </div>
      <div class="panel">
        <h3>Payment history</h3>
        <table>
          <tr><th>Date</th><th>Plan</th><th>Amount</th><th>Status</th><th>Reference</th></tr>
          ${payments.map(p => `<tr>
            <td class="muted">${p.created_at.slice(0, 10)}</td><td>${esc(p.plan || "—")}</td>
            <td>$${p.amount} ${esc(p.currency)}</td>
            <td><span class="badge pill-green">${esc(p.status)}</span></td>
            <td class="mono">${esc(p.ref.slice(0, 20))}…</td>
          </tr>`).join("") || "<tr><td colspan=5 class='muted'>No payments yet</td></tr>"}
        </table>
      </div>
    `);
  },

  async audit() {
    const logs = await api("/api/admin/audit");
    render(`
      <h2>Audit log</h2>
      <div class="panel">
        <table>
          <tr><th>Time</th><th>Action</th><th>Detail</th></tr>
          ${logs.map(l => `<tr>
            <td class="muted">${l.created_at.replace("T", " ").slice(0, 19)}</td>
            <td class="mono">${esc(l.action)}</td><td>${esc(l.detail)}</td>
          </tr>`).join("")}
        </table>
      </div>
    `);
  },
};

/* ---------- Actions ---------- */
function assetTable(list) {
  return `<table>
    <tr><th>Name</th><th>Type</th><th>Classification</th><th>Matched rules</th><th>Source</th><th>When</th><th></th></tr>
    ${list.map(a => `<tr>
      <td style="max-width:280px;overflow-wrap:anywhere">${esc(a.name)}</td>
      <td>${esc(a.asset_type)}</td>
      <td>${a.label ? `<span class="badge" style="background:${esc(a.label.color)}">${esc(a.label.name)}</span>` : "—"}</td>
      <td class="muted" style="max-width:220px;overflow-wrap:anywhere">${esc(a.matched_rules)}</td>
      <td><span class="badge badge-outline">${esc(a.source)}</span></td>
      <td class="muted">${a.classified_at.replace("T", " ").slice(0, 16)}</td>
      <td><button class="btn-sm btn-danger" onclick="deleteAsset(${a.id})">✕</button></td>
    </tr>`).join("") || "<tr><td colspan=7 class='muted'>No assets yet — classify something!</td></tr>"}
  </table>`;
}

async function classifyNow() {
  try {
    const a = await api("/api/assets/classify", {
      method: "POST",
      body: {
        name: document.getElementById("c-name").value.trim(),
        asset_type: document.getElementById("c-type").value,
        content: document.getElementById("c-content").value,
      },
    });
    setWatermarkLabel(a.label?.name || "Unclassified");
    document.getElementById("c-result").innerHTML = `
      <div class="panel" style="margin:0;background:var(--panel-2)">
        Result: <span class="badge" style="background:${esc(a.label?.color || "#6b7280")}">${esc(a.label?.name || "Unclassified")}</span>
        ${a.matched_rules ? `<div class="muted" style="margin-top:8px;font-size:13px">Matched rules: ${esc(a.matched_rules)}</div>` : ""}
      </div>`;
  } catch (e) { flash(e.message, "err"); }
}

async function uploadCsv() {
  const file = document.getElementById("csv-file").files[0];
  if (!file) return flash("Choose a CSV file first", "err");
  const fd = new FormData();
  fd.append("file", file);
  try {
    const r = await api("/api/assets/bulk-csv", { method: "POST", body: fd });
    flash(`Classified ${r.created} assets from CSV`);
    nav("assets");
  } catch (e) { flash(e.message, "err"); }
}

async function searchAssets() {
  const q = document.getElementById("a-q").value.trim();
  const list = await api("/api/assets?q=" + encodeURIComponent(q));
  document.querySelector("#view .panel").innerHTML = assetTable(list);
}

async function exportAssets() {
  const resp = await api("/api/assets/export");
  const blob = await resp.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "assets.csv";
  a.click();
}

async function deleteAsset(id) {
  await api("/api/assets/" + id, { method: "DELETE" });
  nav("assets");
}

async function addRule() {
  try {
    await api("/api/admin/rules", {
      method: "POST",
      body: {
        name: document.getElementById("r-name").value.trim(),
        rule_type: document.getElementById("r-type").value,
        pattern: document.getElementById("r-pattern").value,
        label_id: parseInt(document.getElementById("r-label").value),
        priority: parseInt(document.getElementById("r-priority").value) || 100,
      },
    });
    flash("Rule added"); nav("rules");
  } catch (e) { flash(e.message, "err"); }
}

async function toggleRule(id, enabled) {
  await api("/api/admin/rules/" + id, { method: "PATCH", body: { enabled } });
  nav("rules");
}

async function deleteRule(id) {
  if (!confirm("Delete this rule?")) return;
  await api("/api/admin/rules/" + id, { method: "DELETE" });
  nav("rules");
}

async function addLabel() {
  try {
    await api("/api/admin/labels", {
      method: "POST",
      body: {
        name: document.getElementById("l-name").value.trim(),
        level: parseInt(document.getElementById("l-level").value) || 0,
        color: document.getElementById("l-color").value,
        description: document.getElementById("l-desc").value,
      },
    });
    flash("Label added"); nav("labels");
  } catch (e) { flash(e.message, "err"); }
}

async function deleteLabel(id) {
  if (!confirm("Delete this label?")) return;
  try {
    await api("/api/admin/labels/" + id, { method: "DELETE" });
    nav("labels");
  } catch (e) { flash(e.message, "err"); }
}

async function addUser() {
  try {
    await api("/api/admin/users", {
      method: "POST",
      body: {
        email: document.getElementById("u-email").value.trim(),
        full_name: document.getElementById("u-name").value.trim(),
        password: document.getElementById("u-password").value,
        role: document.getElementById("u-role").value,
      },
    });
    flash("User created"); nav("users");
  } catch (e) { flash(e.message, "err"); }
}

async function toggleUser(id) {
  try {
    await api(`/api/admin/users/${id}/toggle`, { method: "PATCH" });
    nav("users");
  } catch (e) { flash(e.message, "err"); }
}

async function createBuild() {
  try {
    await api("/api/admin/builds", {
      method: "POST",
      body: { platform: document.getElementById("b-platform").value },
    });
    flash("Build generated"); nav("endpoints");
  } catch (e) { flash(e.message, "err"); }
}

async function downloadBuild(id) {
  const resp = await api(`/api/admin/builds/${id}/download`);
  const blob = await resp.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = (resp.headers.get("content-disposition") || "").split("filename=")[1] || "agent.zip";
  a.click();
  nav("endpoints");
}

function readWatermarkForm() {
  return {
    enabled: document.getElementById("wm-enabled").checked,
    opacity: parseFloat(document.getElementById("wm-opacity").value),
    font_size: parseInt(document.getElementById("wm-size").value),
    placement: document.getElementById("wm-placement").value,
    show_classification: document.getElementById("wm-class").checked,
    show_timestamp: document.getElementById("wm-ts").checked,
  };
}

function watermarkPreview() {
  const c = readWatermarkForm();
  document.getElementById("wm-opacity-v").textContent = c.opacity;
  document.getElementById("wm-size-v").textContent = c.font_size + "px";
  const box = document.getElementById("wm-preview");
  const sample = [`${esc(S.name || "User")}`,
    c.show_classification ? "Confidential" : "",
    c.show_timestamp ? new Date().toISOString().slice(0, 16).replace("T", " ") : ""]
    .filter(Boolean).join("  ·  ");
  if (!c.enabled) { box.innerHTML = '<div class="muted" style="padding:80px 0;text-align:center">Watermark disabled</div>'; return; }
  const color = document.body.classList.contains("light") ? "#0f172a" : "#e2e8f0";
  let inner = "";
  if (c.placement === "tiled") {
    for (let y = -10; y < 200; y += Math.max(36, c.font_size * 2.4))
      for (let x = -40; x < 600; x += Math.max(180, c.font_size * 11))
        inner += `<span style="position:absolute;left:${x}px;top:${y}px;transform:rotate(-30deg);white-space:nowrap;font-weight:600">${sample}</span>`;
  } else {
    const pos = { center: "top:50%;left:50%;transform:translate(-50%,-50%) rotate(-30deg)",
      "top-left": "top:8px;left:10px", "top-right": "top:8px;right:10px",
      "bottom-left": "bottom:8px;left:10px", "bottom-right": "bottom:8px;right:10px" }[c.placement];
    inner = `<span style="position:absolute;${pos};white-space:nowrap;font-weight:600">${sample}</span>`;
  }
  box.innerHTML = `<div style="position:absolute;inset:0;opacity:${c.opacity};font-size:${c.font_size}px;color:${color}">${inner}</div>`;
}

async function saveWatermark() {
  try {
    const cfg = await api("/api/admin/watermark", { method: "PUT", body: readWatermarkForm() });
    WM.cfg = cfg; renderWatermark();
    flash("Watermark settings saved");
  } catch (e) { flash(e.message, "err"); }
}

function stampPreview() {
  const box = document.getElementById("sp-preview");
  if (!box) return;
  const text = (document.getElementById("sp-template").value || "CLASSIFICATION: {label}")
    .replace("{label}", "Confidential");
  box.innerHTML = `<span style="font-family:${esc(document.getElementById("sp-font").value)};
    font-size:${parseInt(document.getElementById("sp-size").value) || 10}pt;
    color:${esc(document.getElementById("sp-color").value)};font-weight:700">${esc(text)}</span>`;
}

async function saveStamp() {
  try {
    await api("/api/admin/stamp-policy", {
      method: "PUT",
      body: {
        enabled: document.getElementById("sp-enabled").checked,
        mandatory: document.getElementById("sp-mandatory").checked,
        placement: document.getElementById("sp-placement").value,
        font_name: document.getElementById("sp-font").value.trim() || "Arial",
        font_size: parseInt(document.getElementById("sp-size").value) || 10,
        color: document.getElementById("sp-color").value,
        text_template: document.getElementById("sp-template").value.trim() || "CLASSIFICATION: {label}",
        exempt_emails: document.getElementById("sp-exempt").value.trim(),
      },
    });
    flash("Stamping policy saved");
  } catch (e) { flash(e.message, "err"); }
}

async function createApiKey() {
  try {
    const k = await api("/api/admin/apikeys", {
      method: "POST",
      body: { name: document.getElementById("k-name").value.trim() },
    });
    document.getElementById("new-key-box").innerHTML = `
      <div class="panel" style="border-color:var(--green)">
        <h3>✅ Key created — copy it now, it won't be shown again</h3>
        <div class="row">
          <input class="mono" id="full-key" readonly value="${esc(k.key)}">
          <button class="fixed btn-ghost" onclick="navigator.clipboard.writeText(document.getElementById('full-key').value).then(()=>flash('Key copied to clipboard'))">Copy</button>
        </div>
      </div>`;
    const keysPanel = document.querySelectorAll("#view .panel")[2];
    if (keysPanel) {
      const fresh = await api("/api/admin/apikeys");
      keysPanel.querySelector("table").outerHTML = `<table>
        <tr><th>Name</th><th>Key</th><th>Created</th><th>Last used</th><th>Status</th><th></th></tr>
        ${fresh.map(x => `<tr>
          <td>${esc(x.name)}</td><td class="mono">${esc(x.key_prefix)}</td>
          <td class="muted">${x.created_at.slice(0, 10)}</td>
          <td class="muted">${x.last_used ? x.last_used.replace("T", " ").slice(0, 16) : "never"}</td>
          <td><span class="badge ${x.revoked ? "pill-red" : "pill-green"}">${x.revoked ? "revoked" : "active"}</span></td>
          <td>${x.revoked ? "" : `<button class="btn-sm btn-danger" onclick="revokeApiKey(${x.id})">Revoke</button>`}</td>
        </tr>`).join("")}</table>`;
    }
  } catch (e) { flash(e.message, "err"); }
}

async function revokeApiKey(id) {
  if (!confirm("Revoke this key? Integrations using it will stop working immediately.")) return;
  try {
    await api(`/api/admin/apikeys/${id}/revoke`, { method: "PATCH" });
    nav("apikeys");
  } catch (e) { flash(e.message, "err"); }
}

let pendingPlan = null;
function choosePlan(id, price) {
  pendingPlan = id;
  if (price === 0) return confirmPlan();
  document.getElementById("checkout").classList.remove("hidden");
}

async function confirmPlan() {
  try {
    await api("/api/billing/subscribe", {
      method: "POST",
      body: {
        plan_id: pendingPlan,
        card_number: document.getElementById("pay-card")?.value || "",
        card_exp: document.getElementById("pay-exp")?.value || "",
        card_cvc: document.getElementById("pay-cvc")?.value || "",
      },
    });
    flash("Subscription updated"); nav("billing");
  } catch (e) { flash(e.message, "err"); }
}

window.addEventListener("hashchange", () => {
  if (!S.token && location.hash === "#register") showRegister();
});

boot();
