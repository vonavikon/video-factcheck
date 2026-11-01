// video-factcheck: clicking the extension toolbar icon opens the fact-check
// panel on the current YouTube tab — the same logic as the button under the video
// (open/expand, and start a check if the video has not been checked yet).
"use strict";

// first-run onboarding (decisions #5/#10):
// welcome.html opens only on first install; on update — silent
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.tabs.create({ url: chrome.runtime.getURL("welcome.html") });
  }
});

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab || typeof tab.id !== "number") return;
  // url is available thanks to host_permissions on youtube.com
  if (tab.url && !tab.url.includes("youtube.com/watch")) return;
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "vfc-open-panel" });
  } catch {
    // the content script does not answer (page still loading or not YouTube) — silent
  }
});
