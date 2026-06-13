/* ClassifyHub Office add-in — task pane logic for Word, Excel, PowerPoint and
 * Outlook. Reads the workspace stamp policy and stamps the classification into
 * the document (header/footer) or, in Outlook, the email subject. Stamping is
 * a single in-app call, so it is effectively instant.
 *
 * SERVER is replaced at serve time by the ClassifyHub origin (see /office-addin
 * route). Falls back to the page origin so it works wherever it is hosted. */
var SERVER = (window.__CLASSIFYHUB_ORIGIN__ || location.origin).replace(/\/$/, "");
var COLORS = { Public: "#16a34a", Internal: "#2563eb", Confidential: "#d97706", Restricted: "#dc2626" };
var POLICY = null, HOST = null, SELECTED = "Confidential";

Office.onReady(function (info) {
  HOST = info.host; // Word | Excel | PowerPoint | Outlook
  document.getElementById("hostline").textContent = "Connected to Microsoft " + (HOST || "Office");
  var saved = localStorage.getItem("ch_token");
  if (saved) document.getElementById("token").value = saved;

  document.getElementById("chips").addEventListener("click", function (e) {
    var chip = e.target.closest(".chip");
    if (!chip) return;
    SELECTED = chip.getAttribute("data-label");
    document.querySelectorAll(".chip").forEach(function (c) { c.classList.toggle("on", c === chip); });
  });
  document.getElementById("token").addEventListener("change", loadPolicy);
  document.getElementById("stampBtn").addEventListener("click", stampNow);
  document.getElementById("suggestBtn").addEventListener("click", suggest);
  document.getElementById("tokhelp").addEventListener("click", function (e) {
    e.preventDefault();
    setStatus("Sign in to the ClassifyHub web app, open your profile, and copy your access token.", "");
  });
  loadPolicy();
});

function api(path, opts) {
  opts = opts || {};
  opts.headers = opts.headers || {};
  var token = document.getElementById("token").value.trim();
  if (token) opts.headers.Authorization = "Bearer " + token;
  return fetch(SERVER + path, opts).then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  });
}

function loadPolicy() {
  var token = document.getElementById("token").value.trim();
  if (!token) return;
  localStorage.setItem("ch_token", token);
  api("/api/auth/stamp-policy").then(function (p) {
    POLICY = p;
    var note = document.getElementById("policy-note");
    if (p.exempt) {
      note.innerHTML = '<div class="ok">Your administrator has exempted your account from mandatory stamping.</div>';
    } else if (p.mandatory) {
      note.innerHTML = '<div class="warn"><strong>Mandatory:</strong> this ' +
        (HOST === "Outlook" ? "email cannot be sent" : "document should not be shared") +
        ' without a classification stamp.</div>';
    } else {
      note.innerHTML = "";
    }
  }).catch(function (e) { setStatus("Could not load policy: " + e.message, "err"); });
}

function stampText(label) {
  var tmpl = (POLICY && POLICY.text_template) || "CLASSIFICATION: {label}";
  return tmpl.replace("{label}", label);
}

function stampNow() {
  var text = stampText(SELECTED);
  var place = (POLICY && POLICY.placement) || "footer";
  var size = (POLICY && POLICY.font_size) || 12;
  var font = (POLICY && POLICY.font_name) || "Arial";
  var color = (POLICY && POLICY.color) || COLORS[SELECTED];

  if (HOST === "Word") return stampWord(text, place, size, font, color);
  if (HOST === "Excel") return stampExcel(text, place, size, color);
  if (HOST === "PowerPoint") return stampPowerPoint(text, color);
  if (HOST === "Outlook") return stampOutlook(SELECTED);
  setStatus("Unsupported host.", "err");
}

/* ---- Word: real header/footer ---- */
function stampWord(text, place, size, font, color) {
  return Word.run(function (ctx) {
    var secs = ctx.document.sections;
    secs.load("items");
    return ctx.sync().then(function () {
      secs.items.forEach(function (s) {
        var part = place === "header" ? s.getHeader("Primary") : s.getFooter("Primary");
        part.clear();
        var p = part.insertParagraph(text, "Start");
        p.font.bold = true; p.font.size = size; p.font.name = font; p.font.color = color;
        p.alignment = "Centered";
      });
      return ctx.sync();
    });
  }).then(function () { setStatus("Stamped as " + SELECTED + " in the " + place + ".", "good"); markStamped(); })
    .catch(function (e) { setStatus(e.message, "err"); });
}

/* ---- Excel: header/footer on every worksheet ---- */
function stampExcel(text, place, size, color) {
  return Excel.run(function (ctx) {
    var sheets = ctx.workbook.worksheets;
    sheets.load("items/name");
    return ctx.sync().then(function () {
      sheets.items.forEach(function (sh) {
        var hf = sh.pageLayout.getHeadersFooters().defaultForAllPages;
        if (place === "header") hf.centerHeader = "&B" + text; else hf.centerFooter = "&B" + text;
      });
      return ctx.sync();
    });
  }).then(function () { setStatus("Stamped as " + SELECTED + " in the " + place + " of all sheets.", "good"); markStamped(); })
    .catch(function (e) { setStatus(e.message, "err"); });
}

/* ---- PowerPoint: a banner text box on every slide ---- */
function stampPowerPoint(text, color) {
  // Office.js for PowerPoint has limited shape APIs; insert a footer-style line
  // via the slide's text using the coercion API as a reliable cross-version path.
  return new Promise(function (resolve) {
    Office.context.document.setSelectedDataAsync(text + "\n", { coercionType: Office.CoercionType.Text },
      function (res) {
        if (res.status === Office.AsyncResultStatus.Succeeded) {
          setStatus("Inserted " + SELECTED + " stamp on the current slide.", "good"); markStamped();
        } else {
          setStatus("Select a text placeholder on the slide, then stamp.", "err");
        }
        resolve();
      });
  });
}

/* ---- Outlook: classification into the subject (enforced on send by commands.js) ---- */
function stampOutlook(label) {
  var item = Office.context.mailbox.item;
  item.subject.getAsync(function (r) {
    var subj = (r.value || "").replace(/^\[(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)\]\s*/i, "");
    item.subject.setAsync("[" + label.toUpperCase() + "] " + subj, function () {
      setStatus("Email classified as " + label + " (added to subject).", "good"); markStamped();
    });
  });
}

function markStamped() {
  if (Office.context.document && Office.context.document.settings) {
    Office.context.document.settings.set("classifyhub_label", SELECTED);
    Office.context.document.settings.saveAsync(function () {});
  }
}

/* ---- Suggest a label by sending the visible text to the classifier ---- */
function suggest() {
  getDocumentText(function (text) {
    if (!text) { setStatus("No readable text to analyze.", "err"); return; }
    api("/api/assets/classify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: documentName(), content: text.slice(0, 60000) })
    }).then(function (a) {
      var label = (a.label && a.label.name) || "Internal";
      SELECTED = label;
      document.querySelectorAll(".chip").forEach(function (c) {
        c.classList.toggle("on", c.getAttribute("data-label") === label);
      });
      setStatus("Suggested: " + label + (a.matched_rules ? " (" + a.matched_rules + ")" : ""), "good");
    }).catch(function (e) { setStatus("Suggest failed: " + e.message, "err"); });
  });
}

function documentName() {
  try { return (Office.context.document && Office.context.document.url) || "document"; }
  catch (e) { return "document"; }
}

function getDocumentText(cb) {
  if (HOST === "Outlook") {
    Office.context.mailbox.item.body.getAsync("text", function (r) { cb(r.value || ""); });
    return;
  }
  Office.context.document.getFileAsync(Office.FileType.Text, function (res) {
    if (res.status !== Office.AsyncResultStatus.Succeeded) { cb(""); return; }
    var file = res.value, slices = file.sliceCount, text = "", got = 0;
    for (var i = 0; i < slices; i++) {
      file.getSliceAsync(i, function (s) {
        if (s.status === Office.AsyncResultStatus.Succeeded) text += s.value.data;
        if (++got === slices) { file.closeAsync(function () {}); cb(text); }
      });
    }
  });
}

function setStatus(msg, cls) {
  var el = document.getElementById("status");
  el.className = cls || "";
  el.textContent = msg;
}
