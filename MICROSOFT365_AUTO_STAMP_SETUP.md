# Automatic, server-side stamping for Microsoft 365 / OneDrive

The no-user-intervention path for Microsoft 365: ClassifyHub's backend scans a
user's OneDrive via Microsoft Graph, classifies each Word document by your
rules, and stamps it — automatically, hourly and on demand. Set up once with an
Entra (Azure AD) **app registration** and admin consent.

## 1. Register an app in Microsoft Entra

1. <https://entra.microsoft.com> → **Applications → App registrations → New
   registration**. Name it `ClassifyHub Stamper`. Single tenant. Register.
2. Copy the **Application (client) ID** and **Directory (tenant) ID** from the
   overview page.
3. **Certificates & secrets → New client secret** → copy the secret **Value**
   (shown once).

## 2. Grant application permissions + admin consent

1. **API permissions → Add a permission → Microsoft Graph → Application
   permissions** → add **`Files.ReadWrite.All`** (and `User.Read.All` to resolve
   users).
2. Click **Grant admin consent for <your org>**. (Application permissions need a
   Global/Privileged Role admin to consent — done once.)

## 3. Connect it in ClassifyHub

1. Web app → **Admin Console → Document Stamping → Automatic stamping —
   Microsoft 365 / OneDrive**.
2. Enter the **Directory (tenant) ID**, **Application (client) ID**, the
   **client secret**, and a **user@yourdomain.com** whose OneDrive to scan.
3. Tick **Enabled**, **Save**, then **Scan & stamp now**.

The status line shows the result. After that it rescans automatically every hour.

## How it behaves

- Each `.docx` is downloaded, classified, stamped in its footer with
  `CLASSIFICATION: <label>` (or your template), and uploaded back via Graph.
- Already-stamped files are skipped (tracked by item id).
- Covers **Word documents** to start; Excel/PowerPoint are the next addition.
- To cover more than one user, add their UPNs (multi-user scanning is the next
  iteration; today it scans the single configured user's OneDrive — point it at
  a shared/records drive, or rotate the user).

## Scheduling

The hourly run is the same Vercel Cron as Google (`/api/cron/gdrive-scan`),
which now scans both Google and Microsoft tenants. Set `CRON_SECRET` in Vercel.
