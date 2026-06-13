# ClassifyHub Office add-in — classification stamping & send enforcement

One Office.js add-in that covers **Word, Excel, PowerPoint and Outlook**. It
reads your workspace stamp policy (Admin Console → Document Stamping) and stamps
the classification into the document; in Outlook it can **block sending** an
unclassified email.

The deployable copies are served by the ClassifyHub server:

- Task pane / commands: `https://YOUR-APP-URL/static/office-addin/…`
- Manifests (origin pre-filled):
  - Word/Excel/PowerPoint → `https://YOUR-APP-URL/office-addin/manifest-office.xml`
  - Outlook → `https://YOUR-APP-URL/office-addin/manifest-outlook.xml`

(The files here at the repo root are the originals; the served versions live in
`server/static/office-addin/`.)

## What each app enforces — honestly

| App | Stamp where | Force before save/send? |
|---|---|---|
| **Outlook** | `[CLASSIFICATION]` in the subject | **Yes.** `OnMessageSend` blocks Send until classified (Smart Alerts). |
| **Word** | real header/footer | Stamps on click; warns when policy is mandatory. Office.js cannot hard-cancel Save. |
| **Excel** | header/footer of every sheet | same as Word |
| **PowerPoint** | banner line on the slide | same as Word |
| **PDF / text / other** | handled by the **endpoint agent**, not this add-in | Stamped on detection (after save). |

Why Word/Excel/PowerPoint can't hard-block Save: the Office.js JavaScript API
has no "cancel save" event. Only Outlook exposes a cancellable send event. A
true save-block for the desktop Office apps requires a **COM/VSTO add-in**
(Windows-only, installed via Group Policy) — that's the roadmap item. For the
large majority of compliance needs, in-app stamping + mandatory-policy warnings +
Outlook send-blocking + agent stamping of everything else is sufficient.

## Deploy (org-wide, non-removable by users)

1. **Microsoft 365 admin center → Settings → Integrated apps → Upload custom apps.**
2. Upload by URL: paste the manifest URL above (one for Office, one for Outlook).
3. Assign to users/groups; choose "fixed" deployment so users can't remove it.
   Same managed-deployment model as the endpoint agent.

To test on one machine first, **sideload** the manifest (Office → Insert → My
Add-ins → Upload My Add-in) — no admin center needed.

## How a user uses it

1. Open the add-in (Home tab → ClassifyHub) — it shows the four levels.
2. Click **Suggest from content** to auto-detect a level from the document text
   (uses the same classifier as the platform), or pick one.
3. Click **Stamp document**. Done — it's in the header/footer (or, in Outlook,
   the subject). On a mandatory policy, Outlook won't send until this is done.

First run asks for a workspace access token (paste once from the web app); it's
cached locally so users don't re-enter it.
