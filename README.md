# ClassifyHub — Information Asset Auto-Classification (Micro SaaS)

A full multi-tenant micro-SaaS platform that automatically classifies
information assets (documents, files, databases, emails) into sensitivity
levels such as **Public / Internal / Confidential / Restricted** using a
configurable rule engine (keywords + regex).

## What's included

| Layer | URL | Who | Features |
|---|---|---|---|
| Tenant app | `/` | Tenant users | Classify single assets, bulk CSV classification, asset inventory, search, CSV export |
| Tenant admin console | `/` (admin role) | Tenant admins | Dashboard, classification **rules & labels configuration**, tenant user management, **endpoint agent builds for macOS & Windows**, enrolled endpoints, billing/plan upgrade, audit log |
| Platform owner console | `/owner` | Application owner | Platform stats, all **tenants** (suspend/reactivate), all **registered users**, all **payments**, plan management, **payment gateway configuration** (Stripe/Razorpay/PayPal keys) |
| Endpoint agent | downloadable zip | Endpoints | Cross-platform Python agent: enrolls with a tenant token, pulls the tenant's rules, scans configured paths, classifies locally, reports assets back |

## Architecture

```
server/                 FastAPI + SQLAlchemy + SQLite, JWT auth
  app/
    main.py             app wiring, static hosting
    models.py           Tenant, User, Label, Rule, Asset, Endpoint,
                        AgentBuild, Plan, Subscription, Payment,
                        PaymentGatewayConfig, AuditLog
    classification.py   rule engine + per-tenant default rules/labels
    routers/
      auth.py           tenant signup (creates tenant + admin), login
      assets.py         classify, bulk CSV, inventory, export
      tenant_admin.py   rules/labels/users CRUD, agent builds, endpoints
      agent_api.py      agent enroll / rules / report (X-Agent-Key auth)
      billing.py        plans, subscription, mock checkout, payments
      owner.py          platform stats, tenants, users, payments, gateway
  static/               vanilla-JS SPA (tenant app + owner console)
agent/
  agent.py              stdlib-only endpoint agent (macOS & Windows)
  installers/           install_macos.sh (LaunchAgent), install_windows.ps1 (Scheduled Task)
```

Every tenant's data (labels, rules, assets, users, endpoints, payments) is
isolated by `tenant_id` on every query. Suspended tenants are blocked at
login, API and agent level.

## Quick start

```bash
cd server
pip install -r requirements.txt
python run.py            # serves http://localhost:8000
```

- **Tenant app**: open `http://localhost:8000/` and "Create an account" —
  signup creates your tenant with default labels/rules and a Free plan, and
  makes you the tenant admin.
- **Owner console**: open `http://localhost:8000/owner` and sign in with
  `owner@classifyhub.app` / `owner-admin-123` (override via
  `CLASSIFYHUB_OWNER_EMAIL` / `CLASSIFYHUB_OWNER_PASSWORD`).
- **API docs**: `http://localhost:8000/docs`

### Endpoint agents (macOS / Windows)

1. Admin console → *Endpoints & Builds* → pick platform → **Generate build**
   → **Download .zip**. The zip is pre-configured with your server URL and a
   tenant-scoped enrollment token.
2. On the endpoint:
   - macOS: `bash install.sh` (registers a LaunchAgent)
   - Windows: `powershell -ExecutionPolicy Bypass -File install.ps1`
     (registers a Scheduled Task)
   - or run once: `python3 agent.py`
3. The agent enrolls, pulls your tenant's rules, scans `~/Documents`,
   `~/Desktop`, `~/Downloads` (configurable in `config.json`) and reports
   classified assets, which appear in the asset inventory with source
   `agent`.

### Plans & payments

Free / Pro / Enterprise plans enforce user, endpoint and asset quotas.
Checkout is a mock implementation that records payments — swap
`routers/billing.py:subscribe` for a real gateway using the keys the owner
stores under *Payment Gateway* in the owner console.

## Configuration (environment variables)

| Variable | Default |
|---|---|
| `CLASSIFYHUB_SECRET_KEY` | `dev-secret-change-in-production` |
| `CLASSIFYHUB_DATABASE_URL` | `sqlite:///./classifyhub.db` |
| `CLASSIFYHUB_OWNER_EMAIL` | `owner@classifyhub.app` |
| `CLASSIFYHUB_OWNER_PASSWORD` | `owner-admin-123` |
| `CLASSIFYHUB_TOKEN_TTL_MIN` | `480` |
