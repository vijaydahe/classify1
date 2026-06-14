# Automatic email stamping — how it actually works

Email is **not** a file in a Drive, so the auto-stamp scanners (which download,
edit, and re-upload documents) don't apply. Stamping email automatically is a
**mail-flow** problem, and the platforms give you exactly two real mechanisms.
Be clear with your security team about which you're using.

## 1. Outgoing mail — disclaimer / footer via a mail-flow rule (recommended)

Every message sent by your domain gets a classification footer appended by the
mail server itself. This is automatic, org-wide, and needs no user action — but
it is a **fixed** footer per rule, not per-message content classification.

**Google Workspace** (Admin console → Apps → Google Workspace → Gmail →
*Compliance* → **Append footer**): add a footer such as
`CLASSIFICATION: INTERNAL — handle per company policy`. You can scope rules to
OUs. For different labels, use **Content compliance** rules that match keywords
(e.g. body contains "salary" → add a Confidential footer).

**Microsoft 365** (Exchange admin center → Mail flow → **Rules** →
*Apply disclaimer*): same idea; condition rules on recipients, keywords, or
sensitivity to append the right classification text.

ClassifyHub's classification rules are the natural source for the keyword
conditions — export them from Admin Console → Classification Rules and translate
each into a content-compliance/transport rule.

## 2. Per-message classification at compose — the Outlook add-in (already built)

For true *per-email* classification chosen from your scheme, with a hard
**block on sending an unclassified message**, deploy the ClassifyHub Outlook
add-in (`office-addin/manifest-outlook.xml`). Its `OnMessageSend` handler is the
only place any vendor can stop a send until the user classifies — Microsoft
allows it, Google does not. This covers Outlook desktop + web.

Gmail has **no** send-interception API, so per-message classification in Gmail is
add-on-assisted (the Google Workspace add-on adds the label at compose) but
cannot be hard-blocked — use the mail-flow footer (option 1) for guaranteed
coverage there.

## Summary

| Goal | Google Workspace | Microsoft 365 |
|---|---|---|
| Automatic footer on every outgoing mail | Gmail compliance/append-footer rule | Exchange transport disclaimer rule |
| Keyword-driven classification footer | Gmail content-compliance rule | Exchange rule with conditions |
| Per-message label + **block unclassified send** | Workspace add-on (no hard block) | **Outlook add-in OnMessageSend (hard block)** |

There is no API that lets a third-party app silently re-write the body of every
email the way it can re-write a document — so for email, mail-flow rules are the
correct automatic mechanism, and the Outlook add-in is the correct enforcement
mechanism. This is a platform reality, the same for every classification vendor.
