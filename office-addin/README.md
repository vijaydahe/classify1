# ClassifyHub for Microsoft Word — mandatory-stamping add-in

This Office.js add-in enforces the organization's stamping policy **inside Word**,
which is where most documents are created. It is the practical answer to
"don't let users save a document without a classification stamp."

## What it does

- On open, fetches your workspace's stamp policy from ClassifyHub.
- Shows a task pane where the user picks a classification (Public / Internal /
  Confidential / Restricted) and clicks **Stamp document** — inserting the label
  into the header or footer with the admin-configured font, size and colour.
- When the policy is **mandatory**, the add-in nags on save and re-inserts the
  stamp if it is missing, **unless** the signed-in user is on the admin's
  exception list (the server returns `exempt: true` for them).

## Why an add-in (and not the file-watcher agent)

A background agent can stamp files *after* they are written, but it cannot stop
Word/Excel from saving in the first place — only code running *inside* the app
can do that. Word add-ins can hook document events and modify the header/footer
before save, so genuine enforcement lives here. For other apps, enforce via the
agent (stamp-on-detect) plus MDM document-handling policies.

## Files

- `manifest.xml` — sideload/deploy descriptor (set your deployed URL).
- `taskpane.html` / `taskpane.js` — the UI and stamping logic.

## Deploy

1. Host `taskpane.html`, `taskpane.js` on HTTPS (the ClassifyHub server can serve
   them, or any static host).
2. Edit `manifest.xml`: replace `https://YOUR-APP-URL` with your deployment.
3. Distribute the add-in to users via the **Microsoft 365 admin center →
   Integrated apps** (centralized deployment), which also makes it mandatory and
   non-removable by end users — the same managed-deployment model as the
   endpoint agent.

## Limits (be honest with your security team)

Office.js cannot *hard-cancel* a save in current Word; it enforces by inserting
the stamp on the save/sync event and warning the user. For a hard block you need
a VSTO/COM add-in (`BeforeSave` cancel) deployed via Group Policy — a heavier,
Windows-only path. The Office.js add-in here covers Word on Windows, Mac and the
web with one codebase and is sufficient for the large majority of compliance
needs.
