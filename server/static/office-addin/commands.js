/* ClassifyHub Outlook event handler — enforces classification before send.
 *
 * Registered as an OnMessageSend handler (Smart Alerts). When the user clicks
 * Send, Outlook calls onMessageSend; if the subject carries no classification
 * tag, the send is BLOCKED with a prompt to classify first. This is genuine
 * force-before-send enforcement (the one place Office.js can hard-stop an
 * action). Exempt users (per the workspace policy) are allowed through. */

var TAG = /^\[(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)\]/i;

Office.onReady(function () {});

function onMessageSend(event) {
  var item = Office.context.mailbox.item;
  item.subject.getAsync(function (r) {
    var subject = r.value || "";
    if (TAG.test(subject)) {
      event.completed({ allowEvent: true }); // already classified — let it send
      return;
    }
    // Not classified: block and tell the user how to fix it.
    event.completed({
      allowEvent: false,
      errorMessage: "This email must be classified before sending. Open the ClassifyHub " +
        "add-in (Home tab > ClassifyHub), choose a classification, then send again.",
      cancelLabel: "Classify first"
    });
  });
}

// Required global registration for event-based activation.
if (typeof Office !== "undefined") {
  Office.actions = Office.actions || {};
  Office.actions.associate && Office.actions.associate("onMessageSend", onMessageSend);
}
