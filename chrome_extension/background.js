function isCourseraUrl(rawUrl) {
  try {
    const u = new URL(rawUrl || "");
    const host = u.hostname.toLowerCase().replace(/^www\./, "");
    return host === "coursera.org";
  } catch (_err) {
    return false;
  }
}

function sendScanMessage(tabId, sendResponse) {
  chrome.tabs.sendMessage(tabId, { type: "SCAN_PAGE" }, (resp) => {
    if (chrome.runtime.lastError) {
      sendResponse({
        ok: false,
        error: chrome.runtime.lastError.message || "Failed to scan active tab."
      });
      return;
    }
    sendResponse(resp || { ok: false, error: "No response from content script." });
  });
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== "SCAN_ACTIVE_TAB") {
    return;
  }

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs && tabs[0];
    if (!tab || typeof tab.id !== "number") {
      sendResponse({ ok: false, error: "No active tab found." });
      return;
    }

    if (!isCourseraUrl(tab.url || "")) {
      sendResponse({
        ok: false,
        error: "Active tab is not a Coursera page. Open https://www.coursera.org and try again."
      });
      return;
    }

    chrome.scripting.executeScript(
      {
        target: { tabId: tab.id },
        files: ["content.js"]
      },
      () => {
        if (chrome.runtime.lastError) {
          sendResponse({
            ok: false,
            error: chrome.runtime.lastError.message || "Failed to attach scanner to the current tab."
          });
          return;
        }
        sendScanMessage(tab.id, sendResponse);
      }
    );
  });

  return true;
});
