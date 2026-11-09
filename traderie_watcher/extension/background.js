const API_URL = "http://127.0.0.1:8765/observations";

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "TRADERIE_OBSERVATION") return false;

  // Only accept observations from Traderie tabs; never forward arbitrary page data.
  const url = sender.tab?.url || "";
  if (!/^https:\/\/(www\.)?traderie\.com\//i.test(url)) {
    sendResponse({ ok: false, error: "Untrusted sender URL" });
    return false;
  }

  fetch(API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...message.payload,
      source_url: url,
      captured_at: new Date().toISOString()
    })
  })
    .then(async response => {
      if (!response.ok) throw new Error(`Local collector returned HTTP ${response.status}`);
      sendResponse({ ok: true });
    })
    .catch(error => sendResponse({ ok: false, error: String(error) }));

  return true;
});
