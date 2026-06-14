/**
 * ClassifyHub — Google Workspace add-on.
 *
 * Stamps a classification into Google Docs (header/footer), Sheets (banner row),
 * Slides (per-slide banner) and Gmail (subject + body, at compose time). One
 * Apps Script project serves all four via the Workspace add-on model.
 *
 * Honest scope: Google exposes no cancellable "save" or "send" event to add-ons
 * (Docs auto-saves; Gmail has no send-interception API). So this stamps on
 * demand and can warn, but cannot hard-block like the Outlook OnMessageSend
 * handler in the Office add-in. Enforcement for Google is policy + audit.
 *
 * Config: set Script Properties CLASSIFYHUB_URL and CLASSIFYHUB_TOKEN to pull
 * the workspace stamp policy (text template, placement). Without them, sensible
 * defaults are used.
 */

var LABELS = [
  { name: 'Public',       color: '#16a34a' },
  { name: 'Internal',     color: '#2563eb' },
  { name: 'Confidential', color: '#d97706' },
  { name: 'Restricted',   color: '#dc2626' }
];

var DEFAULT_URL = 'https://classify1-chi.vercel.app';

/** Per-user settings (ClassifyHub URL + access token) stored in UserProperties. */
function settings() {
  var p = PropertiesService.getUserProperties();
  return {
    url: (p.getProperty('CLASSIFYHUB_URL') || DEFAULT_URL).replace(/\/$/, ''),
    token: p.getProperty('CLASSIFYHUB_TOKEN') || ''
  };
}

/** Reads the workspace stamp policy from ClassifyHub, with safe fallbacks. */
function policy() {
  var s = settings();
  var def = { placement: 'footer', text_template: 'CLASSIFICATION: {label}' };
  if (!s.token) return def;
  try {
    var resp = UrlFetchApp.fetch(s.url + '/api/auth/stamp-policy', {
      headers: { Authorization: 'Bearer ' + s.token }, muteHttpExceptions: true
    });
    if (resp.getResponseCode() === 200) {
      var p = JSON.parse(resp.getContentText());
      return { placement: p.placement || 'footer', text_template: p.text_template || def.text_template };
    }
  } catch (e) {}
  return def;
}

/** Classifies text against the tenant's ClassifyHub rules (no storage). */
function classifyByRules(name, content) {
  var s = settings();
  if (!s.token) return null;
  try {
    var resp = UrlFetchApp.fetch(s.url + '/api/assets/classify-preview', {
      method: 'post', contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + s.token },
      payload: JSON.stringify({ name: name || 'document', content: (content || '').slice(0, 60000) }),
      muteHttpExceptions: true
    });
    if (resp.getResponseCode() === 200) {
      var r = JSON.parse(resp.getContentText());
      return r.label ? { name: r.label.name, color: r.label.color, rules: r.matched_rules } : null;
    }
  } catch (e) {}
  return null;
}

function stampText(label) {
  return policy().text_template.replace('{label}', label);
}

/** Home card shown in Docs/Sheets/Slides side panel. */
function onHomepage(e) {
  var s = settings();
  var builder = CardService.newCardBuilder()
    .setHeader(CardService.newCardHeader().setTitle('ClassifyHub'));

  // Auto-classify (uses the rules configured in the ClassifyHub admin console).
  var auto = CardService.newCardSection().setHeader('Auto-classify from content');
  if (s.token) {
    auto.addWidget(CardService.newTextButton()
      .setText('Suggest &amp; stamp per ClassifyHub rules')
      .setTextButtonStyle(CardService.TextButtonStyle.FILLED)
      .setBackgroundColor('#4f46e5')
      .setOnClickAction(CardService.newAction().setFunctionName('autoClassify')));
  } else {
    auto.addWidget(CardService.newTextParagraph().setText(
      '<font color="#b91c1c">Connect to ClassifyHub below to enable rule-based auto-classification.</font>'));
  }
  builder.addSection(auto);

  // Manual override.
  var manual = CardService.newCardSection().setHeader('Or stamp manually');
  LABELS.forEach(function (l) {
    manual.addWidget(CardService.newTextButton()
      .setText(l.name)
      .setTextButtonStyle(CardService.TextButtonStyle.FILLED)
      .setBackgroundColor(l.color)
      .setOnClickAction(CardService.newAction()
        .setFunctionName('stampActive')
        .setParameters({ label: l.name, color: l.color })));
  });
  builder.addSection(manual);

  // Connection settings.
  var conn = CardService.newCardSection().setHeader('ClassifyHub connection').setCollapsible(true);
  conn.addWidget(CardService.newTextInput().setFieldName('url').setTitle('ClassifyHub URL')
    .setValue(s.url));
  conn.addWidget(CardService.newTextInput().setFieldName('token').setTitle('Access token')
    .setValue(s.token ? '••••••• (saved)' : ''));
  conn.addWidget(CardService.newTextParagraph().setText(
    '<font color="#64748b">Get the token from the ClassifyHub web app: Admin Console → Document Stamping → "Add-in token".</font>'));
  conn.addWidget(CardService.newTextButton().setText('Save connection')
    .setOnClickAction(CardService.newAction().setFunctionName('saveSettings')));
  builder.addSection(conn);

  return builder.build();
}

/** Persists the ClassifyHub URL + token entered in the connection section. */
function saveSettings(e) {
  var f = e.formInput || {};
  var p = PropertiesService.getUserProperties();
  if (f.url) p.setProperty('CLASSIFYHUB_URL', f.url.trim());
  if (f.token && f.token.indexOf('•') === -1) p.setProperty('CLASSIFYHUB_TOKEN', f.token.trim());
  return CardService.newActionResponseBuilder()
    .setNotification(CardService.newNotification().setText('ClassifyHub connection saved.'))
    .setNavigation(CardService.newNavigation().updateCard(onHomepage(e)))
    .build();
}

/** Reads the active document's text, classifies it by rules, and stamps it. */
function autoClassify(e) {
  var host = (e.commonEventObject && e.commonEventObject.hostApp) || detectHost();
  var text = readActiveText(host);
  if (!text) return notify('No readable text found to classify.');
  var name = activeName(host);
  var label = classifyByRules(name, text);
  if (!label) return notify('Could not auto-classify (check the ClassifyHub connection / token).');
  var msg;
  if (host === 'docs') msg = stampDoc(label.name, label.color);
  else if (host === 'sheets') msg = stampSheet(label.name, label.color);
  else if (host === 'slides') msg = stampSlides(label.name, label.color);
  else return notify('Open a Doc, Sheet, or Slides to auto-classify.');
  return notify('Auto-classified as ' + label.name +
    (label.rules ? ' (' + label.rules + ')' : '') + '. ' + msg);
}

/** Pulls visible text from the active Doc/Sheet/Slides. */
function readActiveText(host) {
  try {
    if (host === 'docs') return DocumentApp.getActiveDocument().getBody().getText();
    if (host === 'sheets') {
      var vals = SpreadsheetApp.getActiveSpreadsheet().getSheets().map(function (sh) {
        return sh.getDataRange().getValues().map(function (row) { return row.join(' '); }).join(' ');
      });
      return vals.join(' ');
    }
    if (host === 'slides') {
      return SlidesApp.getActivePresentation().getSlides().map(function (sl) {
        return sl.getShapes().map(function (sh) {
          try { return sh.getText().asString(); } catch (e2) { return ''; }
        }).join(' ');
      }).join(' ');
    }
  } catch (e) {}
  return '';
}

function activeName(host) {
  try {
    if (host === 'docs') return DocumentApp.getActiveDocument().getName();
    if (host === 'sheets') return SpreadsheetApp.getActiveSpreadsheet().getName();
    if (host === 'slides') return SlidesApp.getActivePresentation().getName();
  } catch (e) {}
  return 'document';
}

/** Routes a stamp action to the right host. */
function stampActive(e) {
  var label = e.parameters.label, color = e.parameters.color;
  var host = (e.commonEventObject && e.commonEventObject.hostApp) || detectHost();
  var msg;
  if (host === 'docs') msg = stampDoc(label, color);
  else if (host === 'sheets') msg = stampSheet(label, color);
  else if (host === 'slides') msg = stampSlides(label, color);
  else msg = 'Open a Google Doc, Sheet, or Slides to stamp.';
  return notify(msg);
}

function detectHost() {
  try { if (DocumentApp.getActiveDocument()) return 'docs'; } catch (e) {}
  try { if (SpreadsheetApp.getActiveSpreadsheet()) return 'sheets'; } catch (e) {}
  try { if (SlidesApp.getActivePresentation()) return 'slides'; } catch (e) {}
  return '';
}

/** Google Docs — real header or footer. */
function stampDoc(label, color) {
  var doc = DocumentApp.getActiveDocument();
  var text = stampText(label);
  var place = policy().placement;
  var section = place === 'header'
    ? (doc.getHeader() || doc.addHeader())
    : (doc.getFooter() || doc.addFooter());
  // Replace a prior stamp paragraph if present.
  var paras = section.getParagraphs();
  for (var i = 0; i < paras.length; i++) {
    if (paras[i].getText().indexOf('CLASSIFICATION:') === 0) { paras[i].removeFromParent(); }
  }
  var p = section.appendParagraph(text);
  p.setAlignment(DocumentApp.HorizontalAlignment.CENTER);
  p.editAsText().setBold(true).setForegroundColor(color);
  return 'Stamped as ' + label + ' in the ' + place + '.';
}

/** Google Sheets — a frozen banner row at the top of every sheet. */
function stampSheet(label, color) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var text = stampText(label);
  ss.getSheets().forEach(function (sh) {
    var a1 = sh.getRange(1, 1);
    var isBanner = String(a1.getValue()).indexOf('CLASSIFICATION:') === 0;
    if (!isBanner) { sh.insertRowBefore(1); sh.setFrozenRows(1); a1 = sh.getRange(1, 1); }
    a1.setValue(text).setFontWeight('bold').setFontColor(color);
  });
  return 'Stamped as ' + label + ' on all sheets.';
}

/** Google Slides — a footer banner text box on every slide. */
function stampSlides(label, color) {
  var pres = SlidesApp.getActivePresentation();
  var text = stampText(label);
  var w = pres.getPageWidth(), h = pres.getPageHeight();
  pres.getSlides().forEach(function (slide) {
    // Remove a previous stamp (text boxes tagged via alt-title).
    slide.getShapes().forEach(function (sh) {
      if (sh.getTitle && sh.getTitle() === 'classifyhub-stamp') sh.remove();
    });
    var box = slide.insertTextBox(text, 12, h - 28, w - 24, 22);
    box.setTitle('classifyhub-stamp');
    var style = box.getText().getTextStyle();
    style.setBold(true).setForegroundColor(color).setFontSize(10);
  });
  return 'Stamped as ' + label + ' on all slides.';
}

/* ---------------- Gmail (compose time) ---------------- */

function onGmailCompose(e) {
  var section = CardService.newCardSection().setHeader('Classify this email');
  LABELS.forEach(function (l) {
    section.addWidget(CardService.newTextButton()
      .setText(l.name)
      .setTextButtonStyle(CardService.TextButtonStyle.FILLED)
      .setBackgroundColor(l.color)
      .setOnClickAction(CardService.newAction()
        .setFunctionName('applyGmail')
        .setParameters({ label: l.name })));
  });
  section.addWidget(CardService.newTextParagraph().setText(
    '<font color="#64748b">Adds the classification to the subject and a banner ' +
    'to the top of the email body.</font>'));
  return CardService.newCardBuilder()
    .setHeader(CardService.newCardHeader().setTitle('ClassifyHub'))
    .addSection(section).build();
}

function applyGmail(e) {
  var label = e.parameters.label;
  var tag = '[' + label.toUpperCase() + '] ';
  var banner = stampText(label) + '\n\n';
  var subjectAction = CardService.newUpdateDraftSubjectAction().addUpdateSubject(tag);
  var bodyAction = CardService.newUpdateDraftBodyAction()
    .addUpdateContent(banner, CardService.ContentType.PLAIN_TEXT)
    .setUpdateType(CardService.UpdateDraftBodyType.IN_PLACE_INSERT);
  return CardService.newUpdateDraftActionResponseBuilder()
    .setUpdateDraftSubjectAction(subjectAction)
    .setUpdateDraftBodyAction(bodyAction)
    .build();
}

/* ---------------- helpers ---------------- */

function notify(message) {
  return CardService.newActionResponseBuilder()
    .setNotification(CardService.newNotification().setText(message))
    .build();
}
