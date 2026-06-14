# ClassifyHub — Google Workspace add-on

Stamps classification into **Google Docs, Sheets, Slides and Gmail**, the
counterpart to the Office add-in. One Apps Script project, deployed as a
Google Workspace Add-on.

## What it does

| App | Stamp where |
|---|---|
| Docs | real header or footer (per policy) |
| Sheets | frozen banner row at the top of every sheet |
| Slides | footer banner text box on every slide |
| Gmail | `[CLASSIFICATION]` in the subject + a banner line in the body (at compose) |

Users open the side panel (or, in Gmail, the compose add-on), and either:

- **Auto-classify** — "Suggest & stamp per ClassifyHub rules" reads the document
  text, classifies it against the **rules you configured in the ClassifyHub
  admin console**, and stamps the result. Requires connecting the add-on (below).
- **Manual** — click one of the four levels to stamp it directly.

## Connect the add-on (enables auto-classify)

In the side panel, expand **ClassifyHub connection**, paste your **add-in token**
— copy it from the ClassifyHub web app under *Admin Console → Document Stamping →
Add-in token* — and **Save**. The URL defaults to the live deployment. The token
identifies you for the session; auto-classification calls the read-only
`/api/assets/classify-preview` endpoint (no asset is stored, no quota used).

## Honest enforcement note

Google **does not give add-ons a cancellable save or send event** — Docs
auto-saves continuously, and Gmail has no send-interception API. So unlike the
Office/Outlook add-in (which truly blocks an unclassified send), the Google
add-on is **stamp-on-demand + policy + audit**, not a hard block. This is a
Google platform limit that applies to every classification vendor, not a
ClassifyHub shortcut. (Hard DLP enforcement on Google is done at the Workspace
admin / Drive DLP layer, not in an add-on.)

## Deploy

1. Create an Apps Script project at <https://script.google.com> (or `clasp create`).
2. Add `Code.gs` and set the manifest to `appsscript.json` (View → Show manifest).
3. In `appsscript.json`, replace `YOUR-APP-URL` in `logoUrl` with your deployment.
4. (Optional) Script Properties: set `CLASSIFYHUB_URL` and `CLASSIFYHUB_TOKEN`
   to pull your workspace stamp policy (text template + placement). Without
   them, it uses `CLASSIFICATION: {label}` in the footer.
5. **Deploy → Test deployments** to try it, then **Deploy → New deployment →
   Add-on**. For org-wide rollout, publish privately to your domain via the
   Google Workspace Marketplace SDK (Admin-installed, non-removable by users —
   the same managed model as the Office add-in and endpoint agent).

## Files

- `Code.gs` — all add-on logic (Docs/Sheets/Slides/Gmail).
- `appsscript.json` — manifest: scopes + Workspace add-on triggers.
