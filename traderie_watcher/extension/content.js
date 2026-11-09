(() => {
  "use strict";

  // Traderie's DOM can change. Keep selectors centralized and fail closed:
  // only elements matching these listing-like structures are considered.
  const CARD_SELECTORS = [
    ".listing-card",
    '[data-testid*="listing"]',
    '[class*="listing-card"]',
    '[class*="ListingCard"]'
  ];
  const MAX_CARDS_PER_SCAN = 100;
  const MAX_TEXT_LENGTH = 4000;
  const sentFingerprints = new Set();
  let scanTimer = null;
  let lastPageContext = "";

  const isVisible = element => {
    if (!(element instanceof Element)) return false;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" &&
      style.visibility !== "hidden" &&
      Number(style.opacity || 1) > 0 &&
      rect.width > 0 && rect.height > 0 &&
      rect.bottom > 0 && rect.top < window.innerHeight;
  };

  const clean = value => (value || "").replace(/\s+/g, " ").trim().slice(0, MAX_TEXT_LENGTH);

  function getPageContext() {
    const params = new URLSearchParams(location.search);
    const searchInput = document.querySelector(
      'input[type="search"], input[placeholder*="Search" i], input[aria-label*="Search" i]'
    );
    return {
      page_type: /\/items?\//i.test(location.pathname) ? "item_or_listing" :
        (params.size ? "search_or_filtered" : "traderie_page"),
      pathname: location.pathname,
      query: clean(params.toString()),
      search_text: clean(searchInput?.value || ""),
      title: clean(document.title)
    };
  }

  function findListingCards() {
    const found = new Set();
    for (const selector of CARD_SELECTORS) {
      document.querySelectorAll(selector).forEach(element => {
        if (found.size < MAX_CARDS_PER_SCAN && isVisible(element)) found.add(element);
      });
    }
    return [...found];
  }

  function extractListing(card) {
    const text = clean(card.innerText || card.textContent);
    if (text.length < 8) return null;

    const link = card.matches("a[href]") ? card : card.querySelector("a[href]");
    const href = link?.href && /^https:\/\/(www\.)?traderie\.com\//i.test(link.href)
      ? new URL(link.href).pathname + new URL(link.href).search
      : null;
    const heading = card.querySelector("h1,h2,h3,h4,[class*=" + '"title"' + " i],[class*=" + '"name"' + " i]");
    const title = clean(heading?.innerText || link?.innerText || "").slice(0, 300);

    // Capture a displayed asking price as text only; do not infer trade value.
    const priceMatch = text.match(/(?:\b(?:price|asking)\s*[:：]?\s*)?\b\d+(?:[.,]\d+)?\s*(?:ist|rune[s]?|ber|jah|sur|ohm|lo|vex|gul|mal|ist|um|pul|lem|ko|fal|io|lum|hel|dol|shael|amn|sol|ral|ort|thul|tir|nef|eth|el)\b/i);
    return {
      listing_key: href || null,
      listing_path: href,
      title,
      asking_price_text: priceMatch ? clean(priceMatch[0]) : null,
      visible_text: text,
      extraction_method: "visible_dom_heuristic_v1"
    };
  }

  function send(payload) {
    chrome.runtime.sendMessage({ type: "TRADERIE_OBSERVATION", payload }, () => {
      // Ignore transport errors while the local collector is not running.
      void chrome.runtime.lastError;
    });
  }

  function scan() {
    scanTimer = null;
    const context = getPageContext();
    const contextFingerprint = JSON.stringify(context);
    if (contextFingerprint !== lastPageContext) {
      lastPageContext = contextFingerprint;
      send({ observation_type: "page_context", page_context: context });
    }

    for (const card of findListingCards()) {
      const listing = extractListing(card);
      if (!listing) continue;
      const fingerprint = JSON.stringify({
        path: listing.listing_path,
        title: listing.title,
        price: listing.asking_price_text,
        text: listing.visible_text
      });
      if (sentFingerprints.has(fingerprint)) continue;
      sentFingerprints.add(fingerprint);
      send({
        observation_type: "listing_snapshot",
        page_context: context,
        listing
      });
    }

    // Bound memory use during long browsing sessions.
    if (sentFingerprints.size > 5000) sentFingerprints.clear();
  }

  function scheduleScan() {
    if (scanTimer !== null) clearTimeout(scanTimer);
    scanTimer = setTimeout(scan, 800);
  }

  // Observe only rendered DOM changes and user-driven scrolling. No clicks,
  // keyboard input, navigation, form changes, or automatic "load more".
  const observer = new MutationObserver(scheduleScan);
  observer.observe(document.documentElement, {
    subtree: true,
    childList: true,
    characterData: true
  });
  window.addEventListener("scroll", scheduleScan, { passive: true });
  window.addEventListener("popstate", scheduleScan);
  scheduleScan();
})();
