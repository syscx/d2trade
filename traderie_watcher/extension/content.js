(() => {
  "use strict";

  // Verified against a live Traderie listing DOM supplied during testing.
  // Keep the exact site selectors first; the fallback selectors remain
  // conservative so unrelated page sections are not recorded as listings.
  const CARD_SELECTORS = [
    ".offer-listing-item",
    ".listing-card",
    '[data-testid*="listing"]',
    '[class*="listing-card"]',
    '[class*="ListingCard"]'
  ];
  const TITLE_SELECTOR = "a.listing-name.selling-listing";
  const MAX_CARDS_PER_SCAN = 100;
  const MAX_TEXT_LENGTH = 4000;
  const sentFingerprints = new Set();
  let scanTimer = null;
  let lastPageContext = "";

  const clean = value => (value || "").replace(/\s+/g, " ").trim().slice(0, MAX_TEXT_LENGTH);

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

    // The verified title link is a safe anchor for finding its known card.
    document.querySelectorAll(TITLE_SELECTOR).forEach(link => {
      const card = link.closest(".offer-listing-item");
      if (card && found.size < MAX_CARDS_PER_SCAN && isVisible(card)) found.add(card);
    });
    return [...found];
  }

  function getTradeSides(card, title) {
    const lines = (card.innerText || "")
      .split(/\r?\n/)
      .map(line => line.trim())
      .filter(Boolean);
    const theyIndex = lines.findIndex(line => /^they give$/i.test(line));
    const iIndex = lines.findIndex(line => /^i give$/i.test(line));
    const ageIndex = lines.findIndex(line => /^\d+\s+(?:seconds?|minutes?|hours?|days?|weeks?)\s+ago$/i.test(line));

    if (theyIndex < 0 && iIndex < 0) {
      return { they_give_text: null, i_give_text: null };
    }

    // On Traderie, the "They Give" side is represented by the listing title.
    // Its following lines are game/ladder/platform metadata, not extra items.
    const end = ageIndex >= 0 ? ageIndex : lines.length;
    const giveLines = iIndex >= 0
      ? lines.slice(iIndex + 1, end)
      : [];
    const cleanGive = giveLines
      .filter(line => !/^high rune value\s*:/i.test(line))
      .filter(line => !/^\d+\s+(?:seconds?|minutes?|hours?|days?|weeks?)\s+ago$/i.test(line));

    return {
      they_give_text: theyIndex >= 0 ? (title || null) : null,
      i_give_text: iIndex >= 0 ? clean(cleanGive.join(" | ")) || null : null
    };
  }

  function extractListing(card) {
    const text = clean(card.innerText || card.textContent);
    if (text.length < 8) return null;

    const titleLink = card.querySelector(TITLE_SELECTOR);
    const link = titleLink || card.querySelector("a[href*='/listing/']");
    const url = link?.href ? new URL(link.href) : null;
    const href = url && url.protocol === "https:" &&
      ["traderie.com", "www.traderie.com"].includes(url.hostname)
      ? url.pathname + url.search
      : null;

    let title = "";
    if (titleLink) {
      const titleClone = titleLink.cloneNode(true);
      titleClone.querySelectorAll(".listing-container").forEach(node => node.remove());
      title = clean(titleClone.innerText || titleClone.textContent);
    } else if (link) {
      title = clean(link.innerText || link.textContent);
    }

    const tradeSides = getTradeSides(card, title);
    return {
      listing_key: href,
      listing_path: href,
      title: title.slice(0, 300),
      listing_type: tradeSides.they_give_text || tradeSides.i_give_text ? "barter_offer" : "unknown",
      asking_price_text: null,
      ...tradeSides,
      visible_text: text,
      extraction_method: "verified_offer_listing_item_v2"
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
      if (!listing || !listing.listing_path) continue;
      const fingerprint = JSON.stringify({
        path: listing.listing_path,
        title: listing.title,
        they: listing.they_give_text,
        i: listing.i_give_text,
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
