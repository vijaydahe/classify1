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

/** Reads the workspace stamp policy from ClassifyHub, with safe fallbacks. */
function policy() {
  var props = PropertiesService.getScriptProperties();
  var url = props.getProperty('CLASSIFYHUB_URL');
  var token = props.getProperty('CLASSIFYHUB_TOKEN');
  var def = { placement: 'footer', text_template: 'CLASSIFICATION: {label}' };
  if (!url || !token) return def;
  try {
    var resp = UrlFetchApp.fetch(url.replace(/\/$/, '') + '/api/auth/stamp-policy', {
      headers: { Authorization: 'Bearer ' + token }, muteHttpExceptions: true
    });
    if (resp.getResponseCode() === 200) {
      var p = JSON.parse(resp.getContentText());
      return { placement: p.placement || 'footer', text_template: p.text_template || def.text_template };
    }
  } catch (e) {}
  return def;
}

function stampText(label) {
  return policy().text_template.replace('{label}', label);
}

/** Home card shown in Docs/Sheets/Slides side panel. */
function onHomepage(e) {
  var host = (e && e.hostApp) || '';
  var section = CardService.newCardSection()
    .setHeader('Stamp this ' + (host === 'gmail' ? 'email' : 'document') + ' classification');
  LABELS.forEach(function (l) {
    section.addWidget(CardService.newTextButton()
      .setText(l.name)
      .setTextButtonStyle(CardService.TextButtonStyle.FILLED)
      .setBackgroundColor(l.color)
      .setOnClickAction(CardService.newAction()
        .setFunctionName('stampActive')
        .setParameters({ label: l.name, color: l.color })));
  });
  section.addWidget(CardService.newTextParagraph().setText(
    '<font color="#64748b">Stamps the classification into this document. ' +
    'Google does not allow blocking save, so follow your organization policy.</font>'));
  return CardService.newCardBuilder()
    .setHeader(CardService.newCardHeader().setTitle('ClassifyHub'))
    .addSection(section).build();
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
