// video-factcheck: клик по иконке расширения в тулбаре открывает панель
// факт-чека на текущей вкладке YouTube — та же логика, что у кнопки под видео
// (открыть/развернуть, запустить, если видео ещё не проверялось).
"use strict";

// онбординг первого запуска (решение №5/№10,:
// welcome.html открывается только при первой установке; при обновлении — тихо
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.tabs.create({ url: chrome.runtime.getURL("welcome.html") });
  }
});

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab || typeof tab.id !== "number") return;
  // url доступен благодаря host_permissions на youtube.com
  if (tab.url && !tab.url.includes("youtube.com/watch")) return;
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "vfc-open-panel" });
  } catch {
    // контент-скрипт не отвечает (страница ещё грузится или не YouTube) — тихо
  }
});
