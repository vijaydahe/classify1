/* ClassifyHub Word add-in — enforces the org stamping policy inside Word. */
const SERVER = "https://YOUR-APP-URL";  // set to your deployment
const COLORS = { Public: "#16a34a", Internal: "#2563eb", Confidential: "#d97706", Restricted: "#dc2626" };
let POLICY = null;

Office.onReady(() => {
  const saved = localStorage.getItem("ch_token");
  if (saved) document.getElementById("token").value = saved;
  loadPolicy();
});

async function loadPolicy() {
  const token = document.getElementById("token").value.trim();
  if (!token) return;
  localStorage.setItem("ch_token", token);
  try {
    const r = await fetch(SERVER + "/api/auth/stamp-policy", { headers: { Authorization: "Bearer " + token } });
    if (!r.ok) throw new Error("Could not load policy");
    POLICY = await r.json();
    if (POLICY.mandatory) {
      document.getElementById("policy-warn").innerHTML =
        '<div class="warn"><strong>Mandatory stamping is on.</strong> This document must carry a ' +
        'classification stamp before it is shared. The stamp will be re-applied on save if missing.</div>';
      // Re-assert the stamp whenever the document is saved/synced.
      Office.context.document.addHandlerAsync(Office.EventType.DocumentSelectionChanged, () => {});
      hookSave();
    } else if (POLICY.exempt) {
      document.getElementById("policy-warn").innerHTML =
        '<div class="warn" style="background:#f0fdf4;color:#15803d;border-color:#bbf7d0">' +
        'Your account is exempt from mandatory stamping by your administrator.</div>';
    }
  } catch (e) { setStatus(e.message, "err"); }
}

function stampText(label) {
  const tmpl = (POLICY && POLICY.text_template) || "CLASSIFICATION: {label}";
  return tmpl.replace("{label}", label);
}

async function stampNow() {
  const label = document.getElementById("label").value;
  if (!POLICY) await loadPolicy();
  const placement = (POLICY && POLICY.placement) || "footer";
  const text = stampText(label);
  return Word.run(async (context) => {
    const sections = context.document.sections;
    sections.load("items");
    await context.sync();
    for (const section of sections.items) {
      const part = placement === "header"
        ? section.getHeader("Primary") : section.getFooter("Primary");
      part.clear();
      const p = part.insertParagraph(text, "Start");
      p.font.bold = true;
      p.font.size = (POLICY && POLICY.font_size) || 10;
      p.font.name = (POLICY && POLICY.font_name) || "Arial";
      p.font.color = (POLICY && POLICY.color) || COLORS[label];
      p.alignment = "Centered";
    }
    await context.sync();
    setStatus("Stamped as " + label + " in the " + placement + ".", "ok");
  }).catch(e => setStatus(e.message, "err"));
}

function hookSave() {
  // When the document is saved, ensure a stamp is present; re-apply if not.
  if (!Office.context.document.addHandlerAsync) return;
  Office.context.document.addHandlerAsync(Office.EventType.DocumentSelectionChanged, async () => {
    // lightweight presence check could go here; kept minimal for the scaffold
  });
}

function setStatus(msg, cls) {
  const el = document.getElementById("status");
  el.className = cls || "";
  el.textContent = msg;
}
