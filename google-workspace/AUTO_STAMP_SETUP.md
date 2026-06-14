# Automatic, server-side stamping for Google Workspace

This is the **no-user-intervention** path: ClassifyHub's backend scans your
domain's Google Docs, classifies each by your rules, and stamps it — with no
add-on, no user action. It works because a **service account with domain-wide
delegation** can act across your whole domain.

You set this up **once** in the Google Cloud + Workspace admin consoles; after
that it runs automatically (hourly) and on-demand from ClassifyHub.

## 1. Create a service account + key

1. Go to <https://console.cloud.google.com> → create (or pick) a project.
2. **APIs & Services → Enable APIs** → enable **Google Drive API** and
   **Google Docs API**.
3. **IAM & Admin → Service Accounts → Create service account**. Name it
   `classifyhub-stamper`. No project roles are needed.
4. Open the service account → **Keys → Add key → Create new key → JSON**.
   A JSON file downloads — this is what you paste into ClassifyHub.
5. On the service account details page, copy its **Unique ID (Client ID)** and
   note its email (`...@...iam.gserviceaccount.com`).

## 2. Authorize domain-wide delegation (Workspace admin console)

1. <https://admin.google.com> → **Security → Access and data control → API
   controls → Manage Domain Wide Delegation**.
2. **Add new**. Client ID = the service account's **Unique ID** from step 1.5.
3. OAuth scopes (comma-separated) — covers Docs, Sheets and Slides:
   ```
   https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/presentations
   ```
4. **Authorize.**

> Domain-wide delegation lets the service account act as users in your domain —
> grant only the two scopes above, which are read Drive + edit Docs.

## 3. Connect it in ClassifyHub

1. ClassifyHub web app → **Admin Console → Document Stamping → Automatic
   stamping — Google Workspace**.
2. Paste the **JSON key** from step 1.4.
3. **Admin user to act as**: an admin email in your domain (e.g.
   `you@yourdomain.com`) — the service account impersonates this user to reach
   Drive.
4. Tick **Enabled**, **Save**, then **Scan & stamp now** to run immediately.

The status line shows the result (e.g. "scanned 12 new docs, stamped 9"). After
that it rescans automatically every hour.

## How it behaves

- Each Google Doc is classified against your rules and gets a bold, coloured
  `CLASSIFICATION: <label>` line at the top (or your configured text template).
- Already-stamped docs are skipped (tracked by file id), so re-scans are cheap.
- Currently covers **Google Docs**; Sheets and Slides are the next addition.

## Scheduling note (self-hosting)

The hourly run is a Vercel Cron hitting `/api/cron/gdrive-scan`, authorized by
the `CRON_SECRET` environment variable (Vercel sends it as a Bearer token). Set
`CRON_SECRET` in your Vercel project. To trigger manually:

```
curl -H "Authorization: Bearer $CRON_SECRET" https://YOUR-APP-URL/api/cron/gdrive-scan
```
