(function () {
  const COURSE_PATH_PREFIXES = ["/learn/", "/specializations/", "/professional-certificates/", "/projects/"];
  const REJECT_PHRASES = [
    "this course costs",
    "preview this course",
    "start free trial",
    "coursera plus",
    "subscribe"
  ];
  const PAYMENT_CONTEXT_NEAR_DOLLAR = [
    "cost",
    "costs",
    "per month",
    "month",
    "subscribe",
    "free trial",
    "trial"
  ];
  const MAX_CONTAINER_LINKS = 40;
  const MAX_CONTAINER_COURSE_LINKS = 6;
  const MAX_CONTAINER_DEPTH = 10;

  const freeBadgeCache = new WeakMap();
  const previewBadgeCache = new WeakMap();

  function normalizeSpaces(text) {
    return (text || "").replace(/\s+/g, " ").trim();
  }

  function toLowerNormalized(text) {
    return normalizeSpaces(text).toLowerCase();
  }

  function isTrackingParam(key) {
    const lk = key.toLowerCase();
    return lk.startsWith("utm_") || ["fbclid", "gclid", "ref", "referral", "trk"].includes(lk);
  }

  function normalizeUrl(rawUrl) {
    try {
      const u = new URL(rawUrl, location.origin);
      if (!/^https?:$/.test(u.protocol)) {
        return null;
      }
      const host = u.hostname.toLowerCase().replace(/^www\./, "");
      if (host !== "coursera.org") {
        return null;
      }

      const kept = [];
      for (const [k, v] of u.searchParams.entries()) {
        if (!isTrackingParam(k)) {
          kept.push([k, v]);
        }
      }
      u.search = "";
      for (const [k, v] of kept) {
        u.searchParams.append(k, v);
      }
      u.hash = "";
      u.protocol = "https:";
      u.hostname = host;
      u.pathname = u.pathname.replace(/\/{2,}/g, "/");
      if (u.pathname.length > 1 && u.pathname.endsWith("/")) {
        u.pathname = u.pathname.slice(0, -1);
      }
      return u.toString();
    } catch (_err) {
      return null;
    }
  }

  function isCourseUrl(url) {
    try {
      const u = new URL(url);
      const host = u.hostname.toLowerCase().replace(/^www\./, "");
      if (host !== "coursera.org") {
        return false;
      }
      return COURSE_PATH_PREFIXES.some((prefix) => u.pathname.startsWith(prefix));
    } catch (_err) {
      return false;
    }
  }

  function dollarPaymentSignal(textLower) {
    const re = /\$[\d.,]+/g;
    let match = re.exec(textLower);
    while (match) {
      const start = Math.max(match.index - 50, 0);
      const end = Math.min(match.index + match[0].length + 50, textLower.length);
      const windowText = textLower.slice(start, end);
      if (PAYMENT_CONTEXT_NEAR_DOLLAR.some((term) => windowText.includes(term))) {
        return true;
      }
      match = re.exec(textLower);
    }
    return false;
  }

  function elementIsVisible(el) {
    if (!el) {
      return false;
    }
    const style = window.getComputedStyle(el);
    if (!style || style.display === "none" || style.visibility === "hidden") {
      return false;
    }
    return true;
  }

  function isExactToken(text, token) {
    return normalizeSpaces(text).toLowerCase() === token.toLowerCase();
  }

  function hasBadgeToken(container, token) {
    if (!container) {
      return false;
    }
    const cache = token.toLowerCase() === "free" ? freeBadgeCache : previewBadgeCache;
    if (cache.has(container)) {
      return cache.get(container);
    }

    const candidates = container.querySelectorAll("span,div,p,button,strong,b,a,[aria-label]");

    let found = false;
    for (const el of candidates) {
      if (!elementIsVisible(el)) {
        continue;
      }
      const text = normalizeSpaces(el.textContent || "");
      const aria = normalizeSpaces(el.getAttribute("aria-label") || "");
      if (!isExactToken(text, token) && !isExactToken(aria, token)) {
        continue;
      }

      const parentAnchor = el.closest("a[href]");
      if (parentAnchor) {
        const parentHref = normalizeUrl(parentAnchor.getAttribute("href") || "");
        if (!parentHref || !isCourseUrl(parentHref)) {
          continue;
        }
      }

      found = true;
      break;
    }

    cache.set(container, found);
    return found;
  }

  function getCandidateContainers(anchor) {
    const candidates = [];
    let node = anchor;
    for (let depth = 0; depth < MAX_CONTAINER_DEPTH && node && node.parentElement; depth += 1) {
      node = node.parentElement;
      if (!node || node === document.body) {
        break;
      }

      const linkCount = node.querySelectorAll("a[href]").length;
      if (linkCount === 0 || linkCount > MAX_CONTAINER_LINKS) {
        continue;
      }

      const courseLinkCount = node.querySelectorAll(
        "a[href*='/learn/'],a[href*='/specializations/'],a[href*='/professional-certificates/'],a[href*='/projects/']"
      ).length;
      if (courseLinkCount > MAX_CONTAINER_COURSE_LINKS) {
        continue;
      }

      const textLength = normalizeSpaces(node.innerText || "").length;
      if (textLength < 30) {
        continue;
      }
      candidates.push(node);
    }
    return candidates;
  }

  function pickBestContainer(candidates) {
    if (!candidates || candidates.length === 0) {
      return null;
    }

    let best = candidates[0];
    let bestScore = -99999;
    for (const node of candidates) {
      const courseLinkCount = node.querySelectorAll(
        "a[href*='/learn/'],a[href*='/specializations/'],a[href*='/professional-certificates/'],a[href*='/projects/']"
      ).length;
      const textLength = normalizeSpaces(node.innerText || "").length;
      const hasCardHint = node.matches(
        "li,article,[data-testid*='card'],[class*='card'],[class*='Card'],[role='listitem']"
      );
      const hasMedia = !!node.querySelector("img,picture,video");
      const hasFree = hasBadgeToken(node, "free");
      const hasPreview = hasBadgeToken(node, "preview");

      let score = 0;
      if (courseLinkCount === 1) {
        score += 6;
      } else if (courseLinkCount <= 3) {
        score += 3;
      }
      if (hasCardHint) {
        score += 2;
      }
      if (hasMedia) {
        score += 1;
      }
      if (hasFree || hasPreview) {
        score += 5;
      }
      if (textLength > 2500) {
        score -= 3;
      }
      if (score > bestScore) {
        best = node;
        bestScore = score;
      }
    }

    return best;
  }

  function hasBadgeInCandidates(candidates, token) {
    for (const node of candidates) {
      if (hasBadgeToken(node, token)) {
        return true;
      }
    }
    return false;
  }

  function labelFromAnchorOrContainer(anchor, container) {
    const direct = normalizeSpaces(anchor.textContent || "");
    if (direct) {
      return direct;
    }
    if (container) {
      const heading = container.querySelector("h1,h2,h3,h4,strong");
      if (heading) {
        const h = normalizeSpaces(heading.textContent || "");
        if (h) {
          return h;
        }
      }
      const firstTextLink = container.querySelector(
        "a[href*='/learn/'],a[href*='/specializations/'],a[href*='/professional-certificates/'],a[href*='/projects/']"
      );
      if (firstTextLink) {
        const t = normalizeSpaces(firstTextLink.textContent || "");
        if (t) {
          return t;
        }
      }
    }
    return "";
  }

  function classifyText(rawText, options) {
    const opts = options || {};
    const textLower = toLowerNormalized(rawText);
    const rejectHits = REJECT_PHRASES.filter((phrase) => textLower.includes(phrase));
    if (opts.hasPreviewBadge) {
      rejectHits.push("preview badge");
    }
    const dollarHit = dollarPaymentSignal(textLower);
    if (rejectHits.length > 0 || dollarHit) {
      const reasons = [];
      for (const hit of rejectHits) {
        reasons.push("reject phrase: '" + hit + "'");
      }
      if (dollarHit) {
        reasons.push("payment pricing near '$' detected");
      }
      return {
        classification: "PAID_OR_PREVIEW",
        reason: reasons.join("; "),
        likelyFreeListing: false
      };
    }

    if (textLower.includes("full course, no certificate")) {
      return {
        classification: "TRULY_FREE",
        reason: "matched 'Full Course, No Certificate' and no reject phrases",
        likelyFreeListing: false
      };
    }

    const hasEnrollFree = textLower.includes("enroll for free");
    const hasNoCert = textLower.includes("no certificate");
    if (hasEnrollFree && hasNoCert) {
      return {
        classification: "TRULY_FREE",
        reason: "matched 'Enroll for free' + 'No Certificate' and no reject phrases",
        likelyFreeListing: false
      };
    }

    if (opts.hasFreeBadge) {
      return {
        classification: "TRULY_FREE",
        reason: "listing card has exact 'Free' badge and no reject phrases",
        likelyFreeListing: false
      };
    }

    return {
      classification: "UNKNOWN",
      reason: "insufficient signals for truly-free or paid/preview",
      likelyFreeListing: false
    };
  }

  function scanPage() {
    const pageText = normalizeSpaces(document.body ? document.body.innerText : "");
    const pageClass = classifyText(pageText, {});
    const map = new Map();

    const links = document.querySelectorAll("a[href]");
    for (const anchor of links) {
      const normalized = normalizeUrl(anchor.getAttribute("href") || "");
      if (!normalized || !isCourseUrl(normalized)) {
        continue;
      }
      const candidates = getCandidateContainers(anchor);
      const container = pickBestContainer(candidates) || anchor.parentElement || anchor;
      const contextText = normalizeSpaces((container && container.innerText) || anchor.innerText || "");
      const contextClass = classifyText(contextText, {
        hasFreeBadge: hasBadgeInCandidates(candidates, "free"),
        hasPreviewBadge: hasBadgeInCandidates(candidates, "preview")
      });
      const item = {
        url: normalized,
        label: labelFromAnchorOrContainer(anchor, container),
        classification: contextClass.classification,
        reason: contextClass.reason
      };

      if (!map.has(normalized)) {
        map.set(normalized, item);
        continue;
      }

      const prev = map.get(normalized);
      const rank = { "PAID_OR_PREVIEW": 3, "TRULY_FREE": 2, "UNKNOWN": 1 };
      if (rank[item.classification] > rank[prev.classification]) {
        map.set(normalized, item);
      }
    }

    const pageUrl = normalizeUrl(location.href) || location.href;
    const canonical = document.querySelector("link[rel='canonical']");
    const canonicalUrl = canonical ? normalizeUrl(canonical.getAttribute("href") || "") : null;
    if (canonicalUrl && isCourseUrl(canonicalUrl)) {
      const existing = map.get(canonicalUrl);
      if (!existing) {
        map.set(canonicalUrl, {
          url: canonicalUrl,
          label: normalizeSpaces(document.title || ""),
          classification: pageClass.classification,
          reason: pageClass.reason
        });
      } else if (pageClass.classification === "TRULY_FREE" || pageClass.classification === "PAID_OR_PREVIEW") {
        existing.classification = pageClass.classification;
        existing.reason = pageClass.reason;
      }
    }

    const all = Array.from(map.values()).sort((a, b) => a.url.localeCompare(b.url));
    const trulyFree = all.filter((x) => x.classification === "TRULY_FREE");
    const paid = all.filter((x) => x.classification === "PAID_OR_PREVIEW");
    const unknown = all.filter((x) => x.classification === "UNKNOWN");

    return {
      pageUrl: pageUrl,
      pageTitle: normalizeSpaces(document.title || ""),
      pageClassification: pageClass.classification,
      pageReason: pageClass.reason,
      counts: {
        totalCourseLinks: all.length,
        trulyFree: trulyFree.length,
        paidOrPreview: paid.length,
        unknown: unknown.length
      },
      trulyFree: trulyFree,
      paidOrPreview: paid,
      unknown: unknown
    };
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "SCAN_PAGE") {
      return;
    }
    try {
      const result = scanPage();
      sendResponse({ ok: true, result: result });
    } catch (err) {
      sendResponse({ ok: false, error: String(err) });
    }
    return true;
  });
})();
