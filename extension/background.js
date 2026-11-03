// video-factcheck: clicking the extension icon in the toolbar opens the
// fact-check panel on the current YouTube tab. Same logic as the button under
// the video (open or expand, start the check if the video was not checked yet).
"use strict";

// first-run onboarding (decisions 5 and 10, docs/decisions-screens.md):
// welcome.html opens only on first install, updates stay silent
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.tabs.create({ url: chrome.runtime.getURL("welcome.html") });
  }
});

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab || typeof tab.id !== "number") return;
  // tab.url is available thanks to host_permissions on youtube.com
  if (tab.url && !tab.url.includes("youtube.com/watch")) return;
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "vfc-open-panel" });
  } catch {
    // content script does not answer (page still loading or not YouTube), stay quiet
  }
});
