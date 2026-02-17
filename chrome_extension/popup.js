const scanBtn = document.getElementById("scanBtn");
const openBtn = document.getElementById("openBtn");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

let lastScan = null;

function setStatus(text) {
  statusEl.textContent = text;
}

function renderResults(items) {
  resultsEl.innerHTML = "";
  if (!items || items.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No free courses detected on this page.";
    resultsEl.appendChild(li);
    return;
  }

  for (const item of items) {
    const li = document.createElement("li");

    const a = document.createElement("a");
    a.href = item.url;
    a.target = "_blank";
    a.rel = "noreferrer";
    a.textContent = item.label || item.url;
    li.appendChild(a);

    const small = document.createElement("span");
    small.className = "small";
    small.textContent = item.url;
    li.appendChild(small);

    if (item.reason) {
      const reason = document.createElement("span");
      reason.className = "small";
      reason.textContent = "Reason: " + item.reason;
      li.appendChild(reason);
    }

    resultsEl.appendChild(li);
  }
}

function pickOpenTargets(scanResult) {
  if (!scanResult) {
    return [];
  }
  const trulyFree = scanResult.trulyFree || [];
  return trulyFree.map((x) => x.url);
}

function uniqueUrls(urls) {
  return [...new Set(urls)];
}

function openUrls(urls) {
  for (const url of uniqueUrls(urls)) {
    chrome.tabs.create({ url: url });
  }
}

scanBtn.addEventListener("click", () => {
  setStatus("Scanning...");
  openBtn.disabled = true;
  chrome.runtime.sendMessage({ type: "SCAN_ACTIVE_TAB" }, (resp) => {
    if (chrome.runtime.lastError) {
      setStatus(
        "Error: " +
          (chrome.runtime.lastError.message || "scan failed") +
          " (Tip: open a Coursera tab first.)"
      );
      renderResults([]);
      return;
    }
    if (!resp || !resp.ok) {
      setStatus("Error: " + ((resp && resp.error) || "scan failed"));
      renderResults([]);
      return;
    }

    lastScan = resp.result;
    const free = lastScan.trulyFree || [];

    if (free.length > 0) {
      setStatus("Found " + free.length + " TRULY_FREE course(s).");
      renderResults(free);
      openBtn.disabled = false;
      openBtn.textContent = "Direct Me To Free Courses";
      return;
    }

    const unknownCount =
      lastScan && lastScan.counts && typeof lastScan.counts.unknown === "number"
        ? lastScan.counts.unknown
        : 0;
    setStatus(
      "No strict TRULY_FREE matches on this page. Unknown course links: " +
        unknownCount +
        "."
    );
    renderResults([]);
    openBtn.disabled = true;
    openBtn.textContent = "Direct Me To Free Courses";
  });
});

openBtn.addEventListener("click", () => {
  const targets = pickOpenTargets(lastScan);
  if (targets.length === 0) {
    setStatus("No URLs to open. Run scan first.");
    return;
  }
  openUrls(targets);
  setStatus("Opened " + targets.length + " course tab(s).");
});
