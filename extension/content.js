// video-factcheck: панель факт-чека поверх YouTube.
// Тонкий клиент: статус прогона и вердикты, синхронизированные с плеером.
// Логика — на сервере vfc (127.0.0.1:8765); визуальные правила — design/
// (tokens.json + ревью: «мягкие объекты,
// жёсткие связи»).
"use strict";

// API: cloud по умолчанию; для локальной разработки — vfc_api_base в chrome.storage.local
let API = "http://127.0.0.1:8765";  // cloud вернём с HTTPS (mixed-content блокирует HTTP с HTTPS-страниц)
const API_KEY = "";  // ключ X-API-Key твоего сервера (VFC_API_KEY); для 127.0.0.1 не нужен
(async () => { try { const st = await chrome.storage.local.get("vfc_api_base"); if (st.vfc_api_base) API = st.vfc_api_base; } catch {} })();

// Сборочный режим (решение №6: в публичной сборке секции
// пакетов кредитов и email-мока не рендерятся в поповере — кнопки без чека нарушают
// политику CWS; баланс и «как это работает» остаются. Дев-режим включает ключ
// vfc_dev в chrome.storage.local (его же читает options.html) — тогда всё как раньше.
const PUBLIC_BUILD = true;
let devMode = false;
(async () => {
  try { const st = await chrome.storage.local.get("vfc_dev"); devMode = !!st.vfc_dev; } catch {}
  if (panel) applyBuildMode();  // панель могла создаться до чтения флага — докорректируем
})();
function isPublicBuild() { return PUBLIC_BUILD && !devMode; }
function applyBuildMode() {
  if (!panel) return;
  const pub = isPublicBuild();
  panel.auth.classList.toggle("hidden", pub);        // секция email-мока (v0) — только в дев-режиме
  panel.creditsSec.classList.toggle("hidden", pub);  // секция пакетов кредитов — прячем до боевых платёжек
}
const VERDICT_CLASS = { "правда": "v-true", "ложно": "v-false", "странно": "v-strange" };
const VERDICT_COLOR = { "правда": "#7bd88f", "ложно": "#ff8a80", "странно": "#ffd666" };
const CONF_DOTS = { "высокая": 3, "средняя": 2, "низкая": 1 };
// цвет шкалы уверенности (фикс 6): уровень красит заполненные сегменты и подпись
const CONF_COLOR = { "высокая": "#7bd88f", "средняя": "#ffd666", "низкая": "#ff8a80" };
const PROFILE_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"' +
  ' stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<circle cx="12" cy="8" r="3.6"/><path d="M5.5 20c.9-3.1 3.5-4.8 6.5-4.8s5.6 1.7 6.5 4.8"/></svg>';
// знак на свёрнутом кружке — цветной кадр с галочкой (логотип, design/logo, вариант D)
const MINI_ICON =
  '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">' +
  '<rect x="4.1" y="6.4" width="15.8" height="11.2" rx="3" fill="none" stroke="#2F6FED" stroke-width="2.6"/>' +
  '<path d="M8.6 12 L10.9 14.3 L15.7 8.6" fill="none" stroke="#2F6FED" stroke-width="2.6"' +
  ' stroke-linecap="round" stroke-linejoin="round"/></svg>';
// цвета сегментов стек-полосы: сплошные, как на таймлайне (design/tokens.json → stack_bar)
const BAR_COLOR = { "правда": "#2f9e4f", "ложно": "#e5484d", "странно": "#d9b02f", "не проверено": "#9aa0a6" };

// UI-строки панели. Язык выбирается один раз на старте (uiLang с кэшем) и при
// SPA-навигации не пересчитывается. Ключи вердиктов («правда»/«ложно»/«странно»)
// и уверенности («высокая»…) — данные бэкенда: VERDICT_CLASS/VERDICT_COLOR
// остаются на русских значениях, переводится только вывод (verdictLabel/confLabel).
const I18N = {
  ru: {
    panelAria: "Факт-чек видео",
    headTitle: "Факт-чек",
    btnRun: "Проверить видео",
    btnChecking: "Проверяю…",
    openResult: "Открыть результат",
    idle: "Нажми «Проверить видео», чтобы начать",
    readingSubs: "Читаю субтитры со страницы",
    starting: "запускаю проверку",
    phaseTranscript: "скачиваю субтитры",
    phaseClaims: "ищу утверждения: {progress}",
    phaseVerdict: "проверяю утверждения: {progress} · {time} · {skip}",
    phaseFallback: "идёт проверка",
    skipWait: "не ждать",
    skipped: "Проверка продолжается в фоне, результат появится на панели",
    done: "Готово · правда {t} · ложно {f} · странно {s}",
    vTrue: "правда", vFalse: "ложно", vStrange: "странно", vNone: "не проверено",
    cntNone: "без вердикта",
    countsTitle: "проверено {checked} из {total} утверждений",
    confTitle: "уверенность: {level}",
    conf: { "высокая": "высокая", "средняя": "средняя", "низкая": "низкая" },
    more: "ещё {n}",
    jumpTitle: "перейти к {t}",
    splitHead: "Проверки не совпали:",
    splitFirst: "Первая:",
    splitSecond: "Вторая:",
    srcLabel: "Источник: {domain}",
    srcOpen: "↗ Открыть полностью",
    filterTitle: "показать только «{v}»",
    filterReset: "показать все вердикты",
    filterEmpty: "нет карточек этого вердикта",
    tabText: "Текст",
    tabFacts: "Факты",
    moreFrags: "ещё {n} фрагментов",
    dlTitle: "Скачать .md",
    catLabel: "категория",
    mdMin: "мин",
    mdSummary: "Итог",
    mdClaims: "Утверждения",
    mdSources: "Источники",
    errServer: "Сервер факт-чека не отвечает. Проверь интернет или обнови расширение",
    errUpdate: "Обнови расширение: chrome://extensions → ↻",
    errNoSubs: "В видео нет субтитров, проверить его не получится",
    balanceLine: "свободно сегодня: {free} · кредиты: {credits}",
    uncheckedHint: "лимит проверки этого прогона; нажми «Проверить видео» ещё раз для новых вердиктов",
    errSubsLimited: "YouTube ограничил загрузку субтитров. Запусти проверку кнопкой на странице видео: она читает субтитры прямо со страницы",
    errLive: "Прямые эфиры не проверяем: субтитры появляются только после окончания эфира",
    errShorts: "Shorts не поддерживаются. Открой видео в обычном плеере youtube.com/watch",
    errNoVideo: "Это не страница видео — открой видео на YouTube",
    errSubsNotRead: "Субтитры не прочитаны со страницы. Открой DevTools (F12) → Console → [VFC:transcript] для причины",
    errRestart: "Сервер перезапустился, проверка прервалась. Нажми кнопку ещё раз",
    errPlaylist: "Это плейлист, открой конкретное видео",
    errOther: "Проверка не удалась: {text}. Попробуй ещё раз",
    errOtherEmpty: "Проверка не удалась. Попробуй ещё раз",
    errNoRun: "проверка не найдена",
    resume: "Проверка этого видео уже идёт, продолжаю",
    noClaims: "Проверяемых утверждений не нашлось",
    noClaimsHint: "похоже, в видео нет фактов для проверки: музыка, клип или чистое мнение",
    empty: "вердикты появятся здесь",
    foldCollapse: "Свернуть",
    foldExpand: "Развернуть",
    miniExpandAria: "Развернуть панель",
    miniHideAria: "Скрыть панель",
    btnCloseTitle: "Закрыть",
    ariaClaim: "утверждение",
    ariaConfidence: "уверенность",
    profileAria: "Личный кабинет",
    emailLabel: "Email",
    emailPlaceholder: "you@example.com",
    emailInvalid: "Введите корректный email",
    btnSignIn: "Войти",
    btnSignOut: "Выйти",
    mockNote: "вход сохранится в этой сборке, синхронизация позже",
    installIdLabel: "ID установки",
    freeToday: "бесплатных проверок сегодня",
    creditsCount: "кредитов на счету",
    creditsTitle: "Кредиты",
    creditsExpl: "1 кредит = 1 машинная проверка утверждения через веб-поиск. Совпадения с готовыми факт-чеками бесплатны. Каждый день начисляется 10 бесплатных машинных проверок.",
    plausHead: "научные данные: маловероятно —",
    plausHeadSup: "научные данные: подтверждают —",
    sonarPref: "по интернет-источникам:",
    kindSci: "наука",
    kindSciFull: "научная статья",
    kindOrg: "официальный",
    vlangLabel: "язык проверки",
    vlangAuto: "как в браузере",
    vlangHint: "язык обоснований; применяется к новым проверкам",
    packAria: "начислить {n} проверок",
    toastTopup: "Начислено {n} проверок",
    howItWorks: "Как это работает",
    how1: "кредит тратится только на машинную проверку утверждения",
    how2: "проверки, уже сделанные людьми, бесплатны",
    how3: "субтитры и разбор бесплатны",
    srvChecking: "проверяю сервер",
    srvOk: "сервер на связи",
    srvFail: "сервер не отвечает",
    miniDoneAria: "Результат готов — развернуть панель",
    balanceEmpty: "Дневной лимит бесплатных проверок исчерпан. Он обновится завтра",
    balanceResetIn: "до обновления {time}",
    howLink: "как это работает",
    quotaBanner: "Свободные проверки на сегодня закончились. Не проверенные утверждения останутся без вердикта до завтра",
    warnParallel: "Уже идёт проверка другого видео",
    warnParallelText: "Новая проверка пойдёт параллельно и тоже расходует дневной лимит. Запустить всё равно?",
    btnForceRun: "Всё равно проверить",
    btnCancel: "Отмена",
  },
  en: {
    panelAria: "Video fact-check",
    headTitle: "Fact-check",
    btnRun: "Check video",
    btnChecking: "Checking…",
    openResult: "Open results",
    idle: 'Click "Check video" to start',
    readingSubs: "Reading subtitles from the page",
    starting: "starting the check",
    phaseTranscript: "Downloading subtitles",
    phaseClaims: "Finding claims: {progress}",
    phaseVerdict: "Checking claims: {progress} · {time} · {skip}",
    phaseFallback: "Checking",
    skipWait: "skip waiting",
    skipped: "The check continues in the background, the result will appear in the panel",
    done: "Done · true {t} · false {f} · unclear {s}",
    vTrue: "true", vFalse: "false", vStrange: "unclear", vNone: "unchecked",
    cntNone: "no verdict",
    countsTitle: "{checked} of {total} claims checked",
    confTitle: "confidence: {level}",
    conf: { "высокая": "high", "средняя": "medium", "низкая": "low" },
    more: "{n} more",
    jumpTitle: "jump to {t}",
    splitHead: "Checks did not agree:",
    splitFirst: "First:",
    splitSecond: "Second:",
    srcLabel: "Source: {domain}",
    srcOpen: "↗ Open source",
    filterTitle: "show only \"{v}\"",
    filterReset: "show all verdicts",
    filterEmpty: "no cards with this verdict",
    tabText: "Text",
    tabFacts: "Facts",
    moreFrags: "{n} more fragments",
    dlTitle: "Download .md",
    catLabel: "category",
    mdMin: "min",
    mdSummary: "Summary",
    mdClaims: "Claims",
    mdSources: "Sources",
    errServer: "The fact-check server is not responding. Check your internet or update the extension",
    errUpdate: "Update the extension: chrome://extensions → ↻",
    errNoSubs: "This video has no subtitles, so it cannot be checked",
    balanceLine: "free today: {free} · credits: {credits}",
    uncheckedHint: "check limit for this run; click \"Check video\" again for more verdicts",
    errSubsLimited: "YouTube limited subtitles downloads. Update the extension: it reads subtitles right from the page",
    errLive: "Live streams aren't checked: captions only appear after the stream ends",
    errShorts: "Shorts aren't supported. Open the video at youtube.com/watch",
    errNoVideo: "This isn't a video page — open a video on YouTube",
    errSubsNotRead: "Couldn't read captions from the page. Open DevTools (F12) → Console → [VFC:transcript] for the reason",
    errRestart: "The server restarted and the check was interrupted. Click the button again",
    errPlaylist: "This is a playlist, open a specific video",
    errOther: "Check failed: {text}. Try again",
    errOtherEmpty: "Check failed. Try again",
    errNoRun: "run not found",
    resume: "This video is already being checked, resuming",
    noClaims: "No checkable claims found",
    noClaimsHint: "the video seems to have no facts to check: music, a clip, or pure opinion",
    empty: "verdicts will appear here",
    foldCollapse: "Collapse",
    foldExpand: "Expand",
    miniExpandAria: "Expand panel",
    miniHideAria: "Hide panel",
    btnCloseTitle: "Close",
    ariaClaim: "claim",
    ariaConfidence: "confidence",
    profileAria: "Account",
    emailLabel: "Email",
    emailPlaceholder: "you@example.com",
    emailInvalid: "Enter a valid email",
    btnSignIn: "Sign in",
    btnSignOut: "Sign out",
    mockNote: "the sign-in is saved in this build, sync comes later",
    installIdLabel: "Install ID",
    freeToday: "free checks today",
    creditsCount: "credits on balance",
    creditsTitle: "Credits",
    creditsExpl: "1 credit = 1 AI claim check via web search. Matches with existing human fact-checks are free. You get 10 free AI checks every day.",
    plausHead: "science says: unlikely —",
    plausHeadSup: "science says: supports —",
    sonarPref: "web sources say:",
    kindSci: "journal",
    kindSciFull: "peer-reviewed",
    kindOrg: "official",
    vlangLabel: "check language",
    vlangAuto: "follow browser",
    vlangHint: "language of explanations; applies to new checks",
    packAria: "add {n} checks",
    toastTopup: "Credited {n} checks",
    howItWorks: "How it works",
    how1: "a credit is spent only on the machine check of a claim",
    how2: "checks already done by people are free",
    how3: "subtitles and the breakdown are free",
    srvChecking: "checking the server",
    srvOk: "server is up",
    srvFail: "server is not responding",
    miniDoneAria: "Result ready — expand the panel",
    balanceEmpty: "The daily limit of free checks is used up. It resets tomorrow",
    balanceResetIn: "resets in {time}",
    howLink: "how it works",
    quotaBanner: "Free checks for today are over. Unchecked claims will stay without a verdict until tomorrow",
    warnParallel: "Another video is already being checked",
    warnParallelText: "The new check will run in parallel and also uses the daily limit. Start anyway?",
    btnForceRun: "Check anyway",
    btnCancel: "Cancel",
  },
};

let langCache = null;
function uiLang() {
  // язык панели: html[lang] YouTube главнее языка браузера
  if (langCache) return langCache;
  const html = (document.documentElement.lang || "").toLowerCase();
  const nav = (navigator.language || "").toLowerCase();
  langCache = html.startsWith("ru") ? "ru"
            : html.startsWith("en") ? "en"
            : nav.startsWith("ru") ? "ru"
            : nav.startsWith("en") ? "en" : "ru";
  return langCache;
}
function tr(key, vars) {
  let s = I18N[uiLang()][key] || "";
  if (vars) for (const k in vars) s = s.replaceAll(`{${k}}`, String(vars[k]));
  return s;
}
function verdictLabel(v) {
  const L = I18N[uiLang()];
  return v === "правда" ? L.vTrue : v === "ложно" ? L.vFalse : v === "странно" ? L.vStrange : L.vNone;
}
function confLabel(level) {
  return I18N[uiLang()].conf[level] || escapeHtml(level);
}

// состояние панели; все сбросы (startCheck, SPA-навигация) идут через freshState,
// чтобы новые поля ленты не терялись при частичном перечислении
function freshState(videoId) {
  return {
    runId: null, videoId: videoId || null, claims: [], pollTimer: null,
    seen: new Set(), userScrolled: false, startedAt: null, expanded: new Set(),
    done: false,  // прогон завершён (done или восстановленная история) — кнопка не перезапускает
    filter: null,  // активный фильтр ленты: null | "правда" | "ложно" | "странно" | "не проверено"
    transcript: null,  // субтитры из grabTranscript; null → yt-dlp-фолбэк, лента без текста
    feedMode: "text",  // режим ленты (фича A): "text" — транскрипт+факты, "facts" — только карточки
    unfolded: new Set(),  // 30-сек группы транскрипта, раскрытые кликом по «··· ещё N»
  };
}
let panel, feed, state = freshState(null);

// режимы панели (паттерн conspect): "hidden" — панели нет совсем, "mini" — кружок,
// "full" — окно. По умолчанию панели нет: запуск только кнопкой под видео
let panelMode = "hidden";
let timeHooked = null;  // элемент видео с уже повешенным timeupdate (анти-дубль)
let bootPromise = null; // чтение истории/прогона при заходе на видео; клик ждёт его (анти-race, Сл-11)
let navEpoch = 0;       // поколение SPA-страницы: растёт на смене URL; асинхронные цепочки
                        // сверяют эпоху после await и не пишут в чужое состояние (ревью P1-1)

function setPanelMode(m) {
  if (!panel || m === panelMode) return;
  if (m !== "mini") setMiniDone(false);  // разворачивание/скрытие гасит бейдж «результат готов»
  if (m === "hidden") {
    // короткий фейд, потом display:none — выход быстрее входа, но не в ноль кадров.
    // guard: панель могли успеть открыть снова — тогда закрывать нельзя (гонка ×/открыть)
    panel.root.classList.add("hiding");
    setTimeout(() => {
      if (!panel || panelMode !== "hidden") return;
      panel.root.classList.remove("hiding");
      panel.root.classList.add("closed");
    }, 130);
  } else {
    panel.root.classList.remove("closed", "hiding");
    panel.root.classList.toggle("mini", m === "mini");
  }
  panelMode = m;
  panel.fold.setAttribute("aria-expanded", String(m === "full"));
  syncMiniBusy();
}
function syncMiniBusy() {
  // кружок пульсирует, пока идёт прогон (cpulse у conspect)
  if (!panel || !panel.mini) return;
  panel.mini.classList.toggle("busy", !!(panel.run && panel.run.disabled));
}
function setMiniDone(on) {
  // бейдж «результат готов» на свёрнутом кружке (mini-circle-done-state): зелёная
  // галочка поверх, когда фоновый прогон завершился; клик по кружку разворачивает
  if (!panel || !panel.mini) return;
  panel.mini.classList.toggle("done", !!on);
  const label = on ? tr("miniDoneAria") : tr("miniExpandAria");
  panel.mini.setAttribute("aria-label", label);
  panel.mini.setAttribute("title", label);
}

function getVideoId() {
  if (!location.pathname.startsWith("/watch")) return null;
  return new URL(location.href).searchParams.get("v");
}
function getVideoEl() {
  return document.querySelector("video.html5-main-video");
}

const CSS = `
  :host { all: initial; }
  * { box-sizing: border-box; }
  .panel {
    position: fixed; top: 72px; right: 16px; width: 340px; max-height: calc(100vh - 96px);
    background: #16181d; color: #e8e8e8;
    font: 13px/1.45 Roboto, "Segoe UI", system-ui, sans-serif;
    border: 1px solid #2c2f36; border-radius: 12px;
    display: flex; flex-direction: column; z-index: 99999;
    box-shadow: 0 4px 16px rgba(0,0,0,.4);
    transform-origin: top right;
    animation: panel-in .16s ease-out both;
    interpolate-size: allow-keywords;  /* Chrome 129+: height:auto анимируется честно */
    transition: width .28s cubic-bezier(.2,.8,.3,1), height .28s cubic-bezier(.2,.8,.3,1),
      border-radius .28s cubic-bezier(.2,.8,.3,1);
  }
  /* содержимое живёт в обёртке с клипом: сама панель не обрезает, поэтому ×
     свёрнутого кружка торчит за радиус (паттерн cp-x у conspect) */
  .panel-in {
    position: relative; display: flex; flex-direction: column; min-height: 0; min-width: 0;
    overflow: hidden; border-radius: inherit;
    transform-origin: top right;
    /* появление — после расширения, с лёгким ростом масштаба: строки не перестраиваются на глазах */
    transition: opacity .16s ease .12s, transform .2s cubic-bezier(.2,.8,.3,1) .1s;
  }
  @keyframes panel-in { from { transform: translateX(24px); } }
  /* режимы панели (паттерн conspect): closed — панели нет совсем, mini — кружок.
     Морф той же панели чистым CSS: width 340→52 и height auto→52 (interpolate-size
     убрал мёртвую зону max-height — раньше высота стояла, потом рывком догоняла),
     border-radius только в px (12→26): процентный радиус на промежуточном
     не-квадратном боксе давал эллипс. JS-замеров высоты нет — инлайновые
     фиксаторы застревали (баг v0.6.1); в старых Chrome height встаёт мгновенно,
     width/radius едут — деградация без застреваний */
  .panel.closed { display: none; }
  .panel.hiding { opacity: 0; transition: opacity .12s ease; }
  .panel.mini { width: 52px; height: 52px; border-radius: 26px; }
  .panel.mini .panel-in {
    opacity: 0; visibility: hidden; pointer-events: none;
    transform: scale(.97);
    transition: opacity .09s ease, transform .09s ease, visibility 0s .09s;  /* исчезновение — быстро и сразу */
  }
  .mini-circle {
    position: absolute; inset: 0; display: grid; place-items: center;
    opacity: 0; visibility: hidden; pointer-events: none;
    transition: opacity .16s ease .08s, visibility 0s .24s;
    cursor: pointer; background: #16181d; border-radius: 50%;
    border: 1px solid #3d3d3d;
  }
  .panel.mini .mini-circle {
    opacity: 1; visibility: visible; pointer-events: auto;
    transition: opacity .16s ease .08s;
  }
  .mini-circle:focus-visible { outline: 2px solid #3ea6ff; outline-offset: 2px; }
  .mini-ico { display: inline-flex; color: #e8e8e8; }
  .mini-circle.busy .mini-ico { color: #ffd66e; }
  /* пульс — только когда круг реально виден (не в full-режиме впустую) */
  .panel.mini .mini-circle.busy { animation: mini-pulse 1.8s ease-in-out infinite; }
  @keyframes mini-pulse {
    0%, 100% { box-shadow: 0 0 0 4px rgba(245,166,35,.10), 0 0 18px rgba(245,166,35,.25); }
    50% { box-shadow: 0 0 0 6px rgba(245,166,35,.16), 0 0 22px rgba(245,166,35,.4); }
  }
  /* × на свёрнутом кружке: виден при ховере, скрывает панель целиком (cp-x у conspect).
     24px — минимальная цель WCAG SC 2.5.8 */
  .mini-x {
    position: absolute; top: -8px; right: -8px; width: 24px; height: 24px; padding: 0;
    display: grid; place-items: center; border-radius: 50%;
    border: 1px solid rgba(226,92,92,.6); background: #191113; color: #e25c5c;
    font: 600 12px/1 Roboto, sans-serif; cursor: pointer; opacity: 0; z-index: 2;
    transition: opacity .15s, background-color .15s, color .15s;
  }
  .mini-circle:hover .mini-x, .mini-x:focus-visible { opacity: 1; }
  .mini-x:hover { background: #e25c5c; color: #16090b; border-color: #e25c5c; }
  /* бейдж «результат готов» (mini-circle-done-state): фоновый прогон завершился
     при свёрнутой панели — зелёная галочка поверх кружка; клик разворачивает результат */
  .mini-done {
    position: absolute; right: -3px; bottom: -3px; width: 18px; height: 18px; border-radius: 50%;
    background: #2f9e4f; color: #0f1512; font: 700 11px/18px Roboto, "Segoe UI", system-ui, sans-serif;
    text-align: center; display: none; box-shadow: 0 0 0 2px #16181d; pointer-events: none;
  }
  .mini-circle.done .mini-done { display: block; }
  .head, .status, .counts, .feed { background: #16181d; }
  .head { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-bottom: 1px solid #2c2f36; }
  .tt { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
  .head b { font-size: 15px; font-weight: 600; letter-spacing: .01em; line-height: 1.2; }
  .sub { display: flex; align-items: center; gap: 5px; font-size: 11px; color: #9aa0a6; line-height: 1.2; }
  .sub.up { color: #7bd88f; } .sub.up .dot { background: #7bd88f; }
  .sub .dot { width: 5px; height: 5px; border-radius: 50%; background: #9aa0a6; flex: none; }
  .sub.down { color: #ff8a80; } .sub.down .dot { background: #ff8a80; }
  .head .spacer { flex: 1; }
  button.run {
    position: relative; background: #cc2b24; border: none; color: #fff; padding: 6px 14px; border-radius: 999px;
    font: 600 12px Roboto, "Segoe UI", system-ui, sans-serif; cursor: pointer;
    transition: filter .12s, transform .12s;
  }
  button.run:hover:not(:disabled) { filter: brightness(1.12); }
  button.run:active:not(:disabled) { transform: scale(.97); }
  button.run:disabled { background: #5a3a38; cursor: default; }
  /* тонкий прогресс-ободок идущего прогона: конус по счётчику i/N, без данных — пульс */
  button.run.ringed::after, button.run.pulse::after {
    content: ""; position: absolute; inset: -3px; border-radius: 999px; padding: 2px;
    pointer-events: none;
    background: conic-gradient(rgba(255,255,255,.9) calc(var(--p, 0) * 1%), rgba(255,255,255,.18) 0);
    -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    -webkit-mask-composite: xor;
            mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
            mask-composite: exclude;
  }
  button.run.pulse::after {
    background: none; box-shadow: inset 0 0 0 2px rgba(255,255,255,.4);
    animation: run-pulse 1.2s ease-in-out infinite;
  }
  @keyframes run-pulse { 0%, 100% { opacity: .35; } 50% { opacity: 1; } }
  button.fold { background: none; border: none; color: #9aa0a6; padding: 2px 8px; font-size: 15px; cursor: pointer; border-radius: 8px;
    transition: color .12s, background-color .12s; }  /* единый темп hover со всеми кнопками панели */
  button.fold:hover { color: #e8e8e8; background: #1a1d23; }
  button.fold.close { font-size: 16px; }
  button.fold.close:hover { color: #ff8a80; }
  button.profile { background: none; border: none; color: #9aa0a6; width: 28px; height: 28px; padding: 0;
    display: inline-flex; align-items: center; justify-content: center; cursor: pointer; border-radius: 8px;
    transition: color .12s, background-color .12s; }
  button.profile:hover { color: #e8e8e8; background: #1a1d23; }
  button.profile svg { display: block; }
  .status { position: relative; padding: 8px 12px; color: #9aa0a6; font-size: 12px; border-bottom: 1px solid #2c2f36; min-height: 33px; display: flex; align-items: center; gap: 8px; }
  .phasebar { position: absolute; left: 0; right: 0; bottom: -1px; height: 2px; background: #22252b; border-radius: 0 0 0 11px; overflow: hidden; }
  .phasebar i { display: block; height: 100%; background: #3ea6ff; transition: width .6s ease; }
  .status.err { color: #ff8a80; }
  .spin { width: 11px; height: 11px; border-radius: 50%; border: 2px solid #2c2f36; border-top-color: #9aa0a6; animation: spin .9s linear infinite; flex: none; }
  @keyframes spin { to { transform: rotate(360deg); } }
  /* стек-полоса «полоса правды видео»: доли вердиктов + подписи-цифры под ней;
     сегменты и подписи — фильтры ленты (фикс 9): активный подсвечен, прочие гаснут */
  .counts { padding: 9px 12px 8px; font-size: 11px; border-bottom: 1px solid #2c2f36; }
  .stackbar { display: flex; height: 6px; border-radius: 3px; overflow: hidden; }
  .stackbar i { display: block; height: 100%; min-width: 2px; }
  .stackbar i.flt { cursor: pointer; }
  .stackbar.filtered i:not(.active) { opacity: .35; }
  .stacknums { display: flex; justify-content: space-between; gap: 8px; margin-top: 6px; }
  .sn { display: inline-flex; align-items: center; gap: 5px; color: #9aa0a6; white-space: nowrap;
        font-variant-numeric: tabular-nums; background: none; border: none; padding: 3px 6px; margin: -3px -2px;
        font: 400 11px Roboto, "Segoe UI", system-ui, sans-serif; cursor: pointer; border-radius: 7px;
        transition: background-color .12s; }
  .sn i { width: 6px; height: 6px; border-radius: 2px; flex: none; }
  .sn b { color: #dfe3e8; font-weight: 500; }
  .sn:hover:not(.zero):not(:disabled) { background: #1a1d23; }
  .sn.zero, .sn:disabled { cursor: default; opacity: .6; }
  .sn.active { background: #22262e; color: #dfe3e8; }
  .sn.active b { color: #fff; }
  /* баннер «свободные проверки кончились» (решение №9): жёлтая пара v-strange,
     без кнопки «Продолжить с кредитов» до боевых платёжек */
  .quota {
    margin: 8px 12px 0; padding: 7px 10px; border-radius: 8px;
    background: #3a331a; border: 1px solid #575032; color: #ffd666;
    font-size: 11.5px; line-height: 1.45;
  }
  .feed { overflow-y: auto; flex: 1; padding: 4px 0; scrollbar-width: thin; scrollbar-color: #2c2f36 transparent; }
  .feed::-webkit-scrollbar { width: 8px; }
  .feed::-webkit-scrollbar-thumb { background: #2c2f36; border-radius: 4px; }
  .card { padding: 8px 12px; border-bottom: 1px solid #22252b; cursor: default; }
  .card.expandable { cursor: pointer; }
  .card .statebg { border-radius: 8px; margin: 0 3px; padding: 8px 9px; transition: background-color .12s; position: relative; }
  .card:hover .statebg { background: #1a1d23; }
  /* левая рейка цветом вердикта у каждой карточки; текущая — шире и с фоном */
  .card .statebg::before {
    content: ""; position: absolute; left: -3px; top: 6px; bottom: 6px; width: 2px;
    border-radius: 1px; background: var(--rail, #9aa0a6);
  }
  .card.skel .statebg::before { content: none; }
  .card.now .statebg { background: #22262e; }
  .card.now .statebg::before { width: 3px; }
  /* раскрытая карточка (фикс 8): больше воздуха, фон глубже, рейка 4px */
  .card.expanded .statebg { background: #1d2027; padding: 14px 9px; }
  .card.expanded .statebg::before { width: 4px; }
  .card.new .statebg { animation: arrive .18s ease-out; }
  @keyframes arrive { from { opacity: 0; transform: translateY(6px); } }
  .row1 { display: flex; gap: 7px; align-items: center; }
  /* таймкод — span с перемоткой плеера на месте, без перехода по href (фикс 3) */
  .ts { color: #3ea6ff; font-size: 12px; font-family: "Roboto Mono", "Cascadia Mono", Consolas, monospace;
        font-variant-numeric: tabular-nums; cursor: pointer; text-decoration: none; white-space: nowrap;
        display: inline-flex; align-items: center; justify-content: flex-end; width: 46px;
        min-height: 32px; margin: -10px 0; }
  .ts:hover { text-decoration: underline; }
  .badge { font-size: 11px; font-weight: 700; padding: 1px 9px; border-radius: 999px; white-space: nowrap; min-width: 64px; text-align: center; }
  .v-true { background: #1d3a24; color: #7bd88f; } .v-false { background: #3d1a18; color: #ff8a80; }
  .v-strange { background: #3a331a; color: #ffd666; } .v-none { background: #26292f; color: #9aa0a6; }
  /* шкала уверенности (фикс 6): три сегмента 18×4 с зазором 2, под ними
     подпись уровня 10px цветом уровня; цвет задаётся инлайном на .conf */
  .conf { display: inline-flex; flex-direction: column; align-items: flex-end; gap: 3px; margin-left: auto; }
  .conf .segs { display: inline-flex; gap: 2px; }
  .conf i { width: 18px; height: 4px; border-radius: 2px; background: #2c2f36; display: inline-block; }
  .conf i.on { background: currentColor; }
  .conf .lvl { font-size: 10px; line-height: 1; color: currentColor; white-space: nowrap; }
  .claim { margin: 4px 0 2px; color: #dfe3e8; font-size: 13px; }
  .claim.clamp { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .why { color: #9aa0a6; font-size: 12px; margin: 2px 0; }
  /* научные данные (этап 2.5): синий левый след — наука, не вердикт */
  .plaus { margin: 3px 0 2px; padding: 4px 8px; border-left: 2px solid #2F6FED;
    background: #1c1f26; border-radius: 0 8px 8px 0; font-size: 11.5px; line-height: 1.45; }
  .plaus-head { color: #7f9bf3; font-weight: 600; }
  .plaus-why { color: #9aa0a6; }
  .plaus-src { color: #3ea6ff; text-decoration: none; margin-left: 4px; }
  .plaus-src:hover { text-decoration: underline; }
  /* расхождение проходов (фикс 7): вывод каждого прохода отдельной строкой */
  .why.split .sphead { color: #ffd666; }
  .why.split .spline { margin-top: 2px; }
  .why.split .spline b { font-weight: 600; }
  .srcs { margin-top: 4px; font-size: 11px; }
  .srcs a { color: #3ea6ff; text-decoration: none; margin-right: 8px; transition: color .12s; }
  .srcs a:hover { text-decoration: underline; }
  .srcs .more { color: #9aa0a6; cursor: pointer; }
  /* вес источника (шаг 1 дилеммы): наука — синяя пара plaus-блока,
     официальные организации — зелёная пара v-true */
  .srckind { display: inline-block; font-size: 9px; font-weight: 700; line-height: 1;
    padding: 2px 5px; border-radius: 999px; margin-right: 4px; vertical-align: 1px;
    white-space: nowrap; text-transform: uppercase; letter-spacing: .02em; }
  .srckind.sci { background: #17233a; color: #7ab3ff; }
  .srckind.org { background: #1d3a24; color: #7bd88f; }
  /* префикс обоснования sonar при конфликте с наукой */
  .sonar-tag { color: #7c828a; }
  /* источники раскрытой карточки (фикс 8): каждый — отдельный блок с полной цитатой */
  .srcbox { margin-top: 8px; padding: 8px 10px; background: #16181d; border: 1px solid #2c2f36; border-radius: 8px; }
  .srcbox + .srcbox { margin-top: 6px; }
  .srcbox-head { font-size: 11px; color: #9aa0a6; }
  .srcbox-quote { margin-top: 4px; font-size: 12px; color: #dfe3e8; line-height: 1.5; }
  .srcbox-open { display: inline-block; margin-top: 6px; font-size: 11px; color: #3ea6ff; text-decoration: none; }
  .srcbox-open:hover { text-decoration: underline; }
  .srcs a:focus-visible, .ts:focus-visible, button.run:focus-visible, button.fold:focus-visible,
  button.profile:focus-visible, button.mini:focus-visible, button.pack:focus-visible, button.how:focus-visible,
  .sn:focus-visible:not(:disabled), .srcbox-open:focus-visible, .bal-empty a:focus-visible,
  .ftab:focus-visible, .tmore:focus-visible, button.dl:focus-visible {
    outline: 2px solid #3ea6ff; outline-offset: 2px; border-radius: 4px; }
  .pop input:focus-visible { outline: 2px solid #3ea6ff; outline-offset: 1px; }
  .empty { color: #9aa0a6; padding: 20px 14px; text-align: center; font-size: 12px; line-height: 1.6; }
  .empty b { color: #dfe3e8; font-weight: 500; }
  /* ссылка «как это работает» на экране «лимит исчерпан»: кнопка-ссылка по центру */
  .empty .how { display: inline-block; width: auto; padding: 8px 0 0; }
  /* idle: мини-легенда вердиктов + строка баланса */
  .idlebox { padding: 18px 14px 14px; text-align: center; }
  .legend { display: flex; justify-content: center; gap: 14px; margin-bottom: 8px; }
  .lg { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: #9aa0a6; }
  .lg i { width: 7px; height: 7px; border-radius: 50%; flex: none; }
  .idlebal { font-size: 12px; color: #7c828a; min-height: 16px; font-variant-numeric: tabular-nums; }
  /* неблокирующее предупреждение о параллельном прогоне (решение №3) */
  .warnbox { padding: 16px 14px; }
  .warntext { color: #dfe3e8; font-size: 12.5px; line-height: 1.5; margin-bottom: 10px; }
  .warnbtns { display: flex; gap: 6px; }
  /* кабинет-поповер в shadow DOM */
  .pop { position: absolute; top: 52px; right: 10px; width: 264px; background: #1a1d23;
    border: 1px solid #2c2f36; border-radius: 10px; box-shadow: -4px 4px 14px rgba(0,0,0,.4);
    padding: 4px 0 5px; z-index: 5; animation: pop-in .14s ease-out both; }
  @keyframes pop-in { from { opacity: 0; transform: translateY(-4px); } }
  .pop-sec { padding: 8px 12px; }
  .pop-sec + .pop-sec { border-top: 1px solid #22252b; }
  .signin { display: flex; gap: 6px; }
  .pop input { flex: 1; min-width: 0; background: #22262e; border: 1px solid #2c2f36; border-radius: 8px;
    color: #e8e8e8; font: 12px Roboto, "Segoe UI", system-ui, sans-serif; padding: 5px 8px; }
  .pop input::placeholder { color: #7c828a; }
  button.mini { background: #2c2f36; border: none; color: #e8e8e8; border-radius: 999px;
    font: 600 11px Roboto, "Segoe UI", system-ui, sans-serif; padding: 5px 12px; cursor: pointer;
    transition: background-color .12s; }
  button.mini:hover { background: #3a3e46; }
  .mocknote { margin-top: 6px; font-size: 11px; color: #868c94; line-height: 1.4; }
  .who { display: flex; align-items: center; gap: 8px; }
  .who .em { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    color: #dfe3e8; font-size: 12px; }
  .autherr { margin-top: 6px; font-size: 11px; color: #ff8a80; }
  .meta .row { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; padding: 2px 0; align-items: center; }
  .meta .row span { color: #9aa0a6; }
  .meta .row b { color: #dfe3e8; font-weight: 500; font-variant-numeric: tabular-nums; }
  #vfc-vlang { background: #22262e; color: #dfe3e8; border: 1px solid #2c2f36; border-radius: 8px;
    font: 500 12px Roboto, "Segoe UI", system-ui, sans-serif; padding: 3px 6px; cursor: pointer; }
  .vlanghint { color: #868c94; font-size: 10.5px; margin-top: 4px; }
  /* нулевой баланс в поповере (решение №2): та же подсказка + ссылка на пояснение */
  .bal-empty { margin-top: 7px; font-size: 11px; color: #ffd666; line-height: 1.45; }
  .bal-empty a { color: #3ea6ff; text-decoration: none; cursor: pointer; }
  .bal-empty a:hover { text-decoration: underline; }
  .ptitle { font-size: 12px; font-weight: 600; margin-bottom: 7px; color: #e8e8e8; }
  .cexpl { color: #9aa0a6; font-size: 11.5px; line-height: 1.45; margin: -3px 0 9px; }
  .packs { display: flex; gap: 6px; }
  button.pack { flex: 1; background: #22262e; border: 1px solid #2c2f36; color: #dfe3e8; border-radius: 8px;
    font: 500 12px Roboto, "Segoe UI", system-ui, sans-serif; font-variant-numeric: tabular-nums;
    padding: 6px 0; cursor: pointer; transition: background-color .12s, border-color .12s; }
  button.pack:hover:not(:disabled) { background: #2a2e36; border-color: #3a3e46; }
  button.pack:disabled { opacity: .55; cursor: default; }
  .topuperr { margin-top: 7px; font-size: 11px; color: #ff8a80; line-height: 1.4; }
  button.how { display: block; width: 100%; text-align: left; background: none; border: none;
    color: #3ea6ff; font: 400 12px Roboto, "Segoe UI", system-ui, sans-serif; padding: 7px 12px 3px; cursor: pointer; }
  button.how:hover { text-decoration: underline; }
  .howbody { padding: 2px 12px 4px; }
  .howbody p { margin: 3px 0; font-size: 11px; color: #9aa0a6; line-height: 1.45; }
  .toast { position: absolute; left: 12px; right: 12px; bottom: 12px; background: #22262e;
    border: 1px solid #2c2f36; border-radius: 8px; padding: 7px 10px; font-size: 12px; color: #dfe3e8;
    opacity: 0; transform: translateY(4px); pointer-events: none; z-index: 6;
    transition: opacity .16s ease-out, transform .16s ease-out; }
  .toast.show { opacity: 1; transform: none; }
  .skel .statebg { animation: sk-pulse 1.2s ease-in-out infinite; }
  @keyframes sk-pulse { 0%, 100% { opacity: .5; } 50% { opacity: .8; } }
  .sk { display: block; background: #22252b; border-radius: 8px; }
  .sk-badge { width: 64px; height: 16px; border-radius: 999px; }
  .sk-line { width: 78%; height: 12px; margin-top: 8px; }
  .sk-line.short { width: 55%; margin: 5px 0 2px; }
  /* переключатель «Текст / Факты» (фича A): между счётчиками и лентой */
  .feedtabs { display: flex; gap: 4px; padding: 6px 12px 5px; background: #16181d; border-bottom: 1px solid #2c2f36; }
  .ftab { background: none; border: none; color: #9aa0a6; padding: 3px 12px; border-radius: 999px;
    font: 500 12px Roboto, "Segoe UI", system-ui, sans-serif; cursor: pointer;
    transition: color .12s, background-color .12s; }
  .ftab:hover { color: #e8e8e8; background: #1a1d23; }
  .ftab.active { background: #22262e; color: #dfe3e8; }
  /* лента транскрипта (фича A): строки «[M:SS] текст» компактнее карточек */
  .tgroup { padding: 5px 0 1px; }
  .tgroup + .tgroup { margin-top: 4px; border-top: 1px solid #1e2126; }
  /* единая сетка с карточками: таймкод в колонке 46px на вертикали 24px — той же,
     что у карточек фактов (.card 12 + statebg 3+9); правое выравнивание держит
     стену таймкодов, текст строк и бейдж карточек начинаются на одной вертикали */
  .tline { display: flex; align-items: baseline; gap: 7px; padding: 1px 12px 1px 24px; }
  .tline .ts { flex: none; min-height: 0; margin: 0; font-size: 11px; }
  .tline .ttext { color: #9aa0a6; font-size: 12px; line-height: 1.45; min-width: 0; }
  .tmore { padding: 6px 12px 6px 24px; color: #7c828a; font-size: 11px; cursor: pointer; user-select: none; transition: color .12s; }
  .tmore:hover { color: #dfe3e8; }
  /* карточка-конспект непроверенного (фича C): дословная цитата + категория */
  .tquote { margin: 4px 0 2px; color: #9aa0a6; font-size: 12px; line-height: 1.5; }
  .tcat { margin-top: 2px; color: #7c828a; font-size: 11px; }
  /* «Скачать .md» (фича B): в шапке рядом с фолдом */
  button.dl { background: none; border: none; color: #9aa0a6; padding: 2px 8px; font-size: 16px;
    cursor: pointer; border-radius: 8px; }
  button.dl:hover { color: #e8e8e8; background: #1a1d23; }
  .hidden { display: none !important; }
  /* карта вердиктов на таймлайне (design/timeline-segments.component.md) */
  .vfc-segments { position: absolute; left: 0; right: 0; top: 50%; height: 4px;
    transform: translateY(-50%); pointer-events: none; z-index: 30; }
  .vfc-segments i { position: absolute; top: 0; height: 100%; min-width: 4px;
    border-radius: 3px; opacity: .9; }
  @media (prefers-reduced-motion: reduce) {
    .panel, .card.new .statebg, .skel .statebg, .pop { animation: none; }
    .panel, .panel-in, .mini-circle { transition-duration: .001s; transition-delay: 0s; }
    .spin { animation-duration: 2.4s; }
    .panel.mini .mini-circle.busy { animation-duration: 3.6s; }
    button.run { transition: none; }
    button.run.pulse::after { animation: none; opacity: .6; }
    .toast { transition: none; }
  }
  @media (max-width: 1120px) { .panel { width: 300px; } }
`;

function idleMarkup() {
  // idle-состояние ленты: мини-легенда вердиктов + строка баланса (заполнит showBalance)
  const L = I18N[uiLang()];
  const dot = (v, label) => `<span class="lg"><i style="background:${VERDICT_COLOR[v]}"></i>${label}</span>`;
  return `<div class="idlebox"><div class="legend">` +
    dot("правда", L.vTrue) + dot("ложно", L.vFalse) + dot("странно", L.vStrange) +
    `</div><div class="idlebal" id="vfc-idlebal"></div></div>`;
}

function ensurePanel(force) {
  const onWatch = !!getVideoId();
  const existing = document.getElementById("vfc-host");
  if (!onWatch && !force) {
    if (existing) existing.remove();  // автоматически панель живёт только на страницах видео;
    panel = null;                     // force (иконка тулбара) открывает её везде: на /shorts
    return;                           // и вне видео честный отказ покажет startCheck (Сл-9)
  }
  if (panel && existing) return;
  if (existing) existing.remove();
  const host = document.createElement("div");
  host.id = "vfc-host";
  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `
  <style>${CSS}</style>
  <div class="panel closed" id="vfc-panel" role="complementary" aria-label="${tr("panelAria")}">
   <div class="panel-in">
    <div class="head">
      <div class="tt"><b>${tr("headTitle")} <span style="font-weight:400;font-size:10px;color:#7c828a">v0.9.1</span></b><span class="sub" id="vfc-srv"><i class="dot"></i>${tr("srvChecking")}</span></div>
      <span class="spacer"></span>
      <button class="run" id="vfc-run">${tr("btnRun")}</button>
      <button class="profile" id="vfc-profile" title="${tr("profileAria")}" aria-label="${tr("profileAria")}" aria-haspopup="dialog" aria-expanded="false" aria-controls="vfc-pop">${PROFILE_ICON}</button>
      <button class="dl hidden" id="vfc-dl" title="${tr("dlTitle")}" aria-label="${tr("dlTitle")}">↓</button>
      <button class="fold" id="vfc-fold" title="${tr("foldCollapse")}" aria-label="${tr("foldCollapse")}" aria-expanded="true">−</button>
      <button class="fold close" id="vfc-close" title="${tr("btnCloseTitle")}" aria-label="${tr("btnCloseTitle")}">×</button>
    </div>
    <div class="pop hidden" id="vfc-pop" role="dialog" aria-modal="false" aria-label="${tr("profileAria")}" tabindex="-1">
      <div class="pop-sec" id="vfc-auth"></div>
      <div class="pop-sec meta">
        <div class="row"><span>${tr("installIdLabel")}</span><b id="vfc-iid"></b></div>
        <div class="row"><span>${tr("freeToday")}</span><b id="vfc-free"></b></div>
        <div class="row"><span>${tr("creditsCount")}</span><b id="vfc-credits"></b></div>
        <div class="row"><span>${tr("vlangLabel")}</span>
          <select id="vfc-vlang" aria-label="${tr("vlangLabel")}">
            <option value="auto">${tr("vlangAuto")}</option>
            <option value="ru">Русский</option>
            <option value="en">English</option>
          </select>
        </div>
        <div class="vlanghint">${tr("vlangHint")}</div>
        <div class="bal-empty hidden" id="vfc-bal-empty"></div>
      </div>
      <div class="pop-sec" id="vfc-credits-sec">
        <div class="ptitle">${tr("creditsTitle")}</div>
        <div class="cexpl">${tr("creditsExpl")}</div>
        <div class="packs">
          <button class="pack" type="button" data-n="100" title="${tr("packAria", { n: 100 })}">+100</button>
          <button class="pack" type="button" data-n="500" title="${tr("packAria", { n: 500 })}">+500</button>
          <button class="pack" type="button" data-n="2000" title="${tr("packAria", { n: 2000 })}">+2000</button>
        </div>
        <div class="topuperr hidden" id="vfc-topup-err"></div>
      </div>
      <button class="how" type="button" id="vfc-how" aria-expanded="false" aria-controls="vfc-howbody">${tr("howItWorks")}</button>
      <div class="howbody hidden" id="vfc-howbody">
        <p>${tr("how1")}</p><p>${tr("how2")}</p><p>${tr("how3")}</p>
      </div>
    </div>
    <div class="status" id="vfc-status" role="status" aria-live="polite">${tr("idle")}</div>
    <div class="counts hidden" id="vfc-counts"></div>
    <div class="quota hidden" id="vfc-quota" role="status"></div>
    <div class="feedtabs hidden" id="vfc-feedtabs">
      <button class="ftab active" type="button" data-m="text" aria-pressed="true">${tr("tabText")}</button>
      <button class="ftab" type="button" data-m="facts" aria-pressed="false">${tr("tabFacts")}</button>
    </div>
    <div class="feed" id="vfc-feed">${idleMarkup()}</div>
    <div class="toast" id="vfc-toast" role="status"></div>
   </div>
    <div class="mini-circle" id="vfc-mini" role="button" tabindex="0" aria-label="${tr("miniExpandAria")}" title="${tr("miniExpandAria")}">
      <span class="mini-ico" aria-hidden="true">${MINI_ICON}</span>
      <span class="mini-done" aria-hidden="true">✓</span>
      <button class="mini-x" id="vfc-minix" type="button" title="${tr("miniHideAria")}" aria-label="${tr("miniHideAria")}">×</button>
    </div>
  </div>`;
  panel = {
    host, root: shadow.querySelector("#vfc-panel"),
    status: shadow.querySelector("#vfc-status"),
    counts: shadow.querySelector("#vfc-counts"),
    feed: shadow.querySelector("#vfc-feed"),
    feedtabs: shadow.querySelector("#vfc-feedtabs"),
    run: shadow.querySelector("#vfc-run"),
    dl: shadow.querySelector("#vfc-dl"),
    fold: shadow.querySelector("#vfc-fold"),
    close: shadow.querySelector("#vfc-close"),
    mini: shadow.querySelector("#vfc-mini"),
    minix: shadow.querySelector("#vfc-minix"),
    srv: shadow.querySelector("#vfc-srv"),
    profile: shadow.querySelector("#vfc-profile"),
    pop: shadow.querySelector("#vfc-pop"),
    auth: shadow.querySelector("#vfc-auth"),
    creditsSec: shadow.querySelector("#vfc-credits-sec"),
    balEmpty: shadow.querySelector("#vfc-bal-empty"),
    quota: shadow.querySelector("#vfc-quota"),
    iid: shadow.querySelector("#vfc-iid"),
    vlang: shadow.querySelector("#vfc-vlang"),
    how: shadow.querySelector("#vfc-how"),
    howbody: shadow.querySelector("#vfc-howbody"),
    topupErr: shadow.querySelector("#vfc-topup-err"),
    packs: Array.from(shadow.querySelectorAll(".pack")),
    toast: shadow.querySelector("#vfc-toast"),
  };
  panel.run.addEventListener("click", () => startCheck());  // без force: событие не должно его подменять
  panel.dl.addEventListener("click", downloadMarkdown);  // фича B: выгрузка протокола
  // «Текст / Факты» (фича A): переключение перерисовывает ленту в текущем режиме
  panel.feedtabs.querySelectorAll(".ftab").forEach((b) => b.addEventListener("click", () => {
    if (state.feedMode === b.dataset.m) return;
    state.feedMode = b.dataset.m;
    syncFeedTabs();
    renderCurrent({ claims: state.claims });
  }));
  panel.profile.addEventListener("click", () => togglePop());
  panel.how.addEventListener("click", () => {
    const closed = panel.howbody.classList.toggle("hidden");
    panel.how.setAttribute("aria-expanded", String(!closed));
  });
  panel.packs.forEach((b) => b.addEventListener("click", () => doTopup(parseInt(b.dataset.n, 10))));
  // подсказка о нулевом балансе в поповере: ссылка раскрывает «как это работает»
  panel.balEmpty.addEventListener("click", (e) => {
    if (!e.target.closest("a")) return;
    e.preventDefault();
    panel.howbody.classList.remove("hidden");
    panel.how.setAttribute("aria-expanded", "true");
  });
  applyBuildMode();  // PUBLIC_BUILD: публичная сборка прячет мок и пакеты (решение №6)
  // язык проверки (язык обоснований вердиктов): авто = локаль браузера; хранится
  // в chrome.storage, применяется к новым прогонам
  panel.vlang.addEventListener("change", async () => {
    try { await chrome.storage.local.set({ vfc_verdict_lang: panel.vlang.value }); } catch {}
  });
  bindPopDismissals();
  panel.fold.addEventListener("click", () => setPanelMode(panelMode === "mini" ? "full" : "mini"));
  panel.close.addEventListener("click", () => setPanelMode("hidden"));
  // кружок: клик — развернуть, × при ховере — скрыть панель целиком (паттерн conspect)
  panel.mini.addEventListener("click", () => setPanelMode("full"));
  panel.mini.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPanelMode("full"); }
  });
  panel.minix.addEventListener("click", (e) => { e.stopPropagation(); setPanelMode("hidden"); });
  panel.feed.addEventListener("scroll", () => {
    const f = panel.feed;
    state.userScrolled = f.scrollTop + f.clientHeight < f.scrollHeight - 40;
  });
  document.body.appendChild(host);
  const video = getVideoEl();
  // timeupdate вешается один раз на элемент видео: пересоздание панели дублей не плодит
  if (video && timeHooked !== video) {
    video.addEventListener("timeupdate", onTimeUpdate);
    timeHooked = video;
  }
  // панель по умолчанию скрыта; авто-открытие — только если на видео живёт
  // незавершённый прогон (вернулся к проверке), готовая история панель не открывает.
  // bootPromise держит чтение: быстрый клик по кнопке ждёт его, чтобы guard
  // «уже проверено» решал по восстановленным данным, а не по пустому state (Сл-11)
  bootPromise = resumeStoredRun().then((resumed) => {
    if (resumed) { setPanelMode("full"); return; }
    return restoreHistory(getVideoId());
  });
  syncFeedTabs();  // транскрипт мог остаться в state (YouTube стёр панель среди видео)
  syncDlButton();
  showBalance();  // заодно ставит микро-подпись статуса сервера в шапке
}

function fmtTS(sec) {
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}
function seekTo(sec) {
  // перемотка плеера на месте, без перехода по ссылке и перезагрузки (фикс 3)
  const video = getVideoEl();
  if (!video || !isFinite(sec) || sec < 0) return false;
  video.currentTime = sec;
  return true;
}
function fmtElapsed(ms) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// --- Стриминг транскрипта (фича A): подготовка cues ---

function dedupCues(cues) {
  // роллинг-повторы автосубтитров: текст N равен N-1 → пропустить;
  // N-1 содержится в N → взять N (строка «доросла» до полной)
  const out = [];
  for (const c of cues) {
    const prev = out[out.length - 1];
    if (prev) {
      if (c.text === prev.text) continue;
      if (prev.text.length && c.text.includes(prev.text)) { out[out.length - 1] = c; continue; }
    }
    out.push(c);
  }
  return out;
}

function groupCues(dc) {
  // группы по ~30 сек: bucket = floor(start/30); в cues — индексы строк в dc
  const groups = [];
  for (let k = 0; k < dc.length; k++) {
    const b = Math.floor((dc[k].start || 0) / 30);
    const g = groups[groups.length - 1];
    if (g && g.bucket === b) g.cues.push(k);
    else groups.push({ bucket: b, cues: [k] });
  }
  return groups;
}

function nearestCueIndex(cues, t) {
  // бинарный поиск: последний cue с start <= t; t раньше первого cue → 0
  let lo = 0, hi = cues.length - 1, res = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if ((cues[mid].start || 0) <= t) { res = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return res;
}

function moreFragsLabel(n) {
  // «··· ещё N фрагментов» с русским склонением; en — шаблоном I18N
  if (uiLang() !== "ru") return tr("moreFrags", { n });
  const a = n % 10, b = n % 100;
  const w = (a === 1 && b !== 11) ? "фрагмент"
    : (a >= 2 && a <= 4 && (b < 12 || b > 14)) ? "фрагмента" : "фрагментов";
  return `ещё ${n} ${w}`;
}

function onTimeUpdate() {
  if (!state.claims.length || !panel) return;
  const video = getVideoEl();
  if (!video) return;
  const t = video.currentTime;
  let idx = -1;
  for (let i = 0; i < state.claims.length; i++) {
    if (state.claims[i].t_start <= t && t <= state.claims[i].t_start + 30) { idx = i; break; }
  }
  const cards = panel.feed.querySelectorAll(".card");
  cards.forEach((c) => c.classList.remove("now"));
  if (idx >= 0) {
    // карточки ищутся по data-i (индекс в state.claims): фильтр ленты (фикс 9)
    // прячет часть карточек, порядковый номер в DOM больше не совпадает с idx
    const cur = panel.feed.querySelector(`.card[data-i="${idx}"]`);
    if (cur) {
      cur.classList.add("now");
      const v = state.claims[idx].verdict;
      cur.style.setProperty("--rail", VERDICT_COLOR[v] || "#9aa0a6");
      if (!state.userScrolled) {
        const smooth = !matchMedia("(prefers-reduced-motion: reduce)").matches;
        cur.scrollIntoView({ block: "nearest", behavior: smooth ? "smooth" : "auto" });
      }
    }
  }
}

function requestPlayerData() {
  // мост из MAIN-мира (page-bridge.js): субтитровые треки + метаданные видео
  return new Promise((resolve) => {
    let done = false;
    const handler = (e) => {
      done = true;
      window.removeEventListener("vfc-player-data", handler);
      resolve(e.detail || null);
    };
    window.addEventListener("vfc-player-data", handler);
    window.dispatchEvent(new CustomEvent("vfc-request-data"));
    setTimeout(() => { if (!done) { window.removeEventListener("vfc-player-data", handler); resolve(null); } }, 800);
  });
}

async function fetchTimedText(tracks, vd, vid, dbg) {
  // прямой timed_text: самые точные тайминги; с октября 2026 YouTube чаще всего
  // отдаёт пустой 200, но на части видео/языков ещё жив — всегда пробуем первым
  const pick = tracks.find((t) => /^ru/.test(t.languageCode || ""))
            || tracks.find((t) => /^en/.test(t.languageCode || ""))
            || tracks[0];
  if (!pick) return null;
  let bu = null;
  try { bu = new URL(pick.baseUrl); } catch { dbg("baseUrl невалиден"); return null; }
  if (!/(^|\.)youtube\.com$/.test(bu.hostname)) { dbg("не youtube.com: " + bu.hostname); return null; }
  bu.searchParams.set("fmt", "json3");
  dbg("качаю timed_text: " + bu.pathname);
  const r = await fetch(bu.toString(), { credentials: "same-origin" });
  if (!r.ok) { dbg("timed_text HTTP " + r.status); return null; }
  const j = await r.json().catch(() => null);
  const cues = j ? (j.events || [])
    .filter((e) => e.segs)
    .map((e) => ({
      start: (e.tStartMs || 0) / 1000,
      end: (e.tStartMs + (e.dDurationMs || 3000)) / 1000,
      text: e.segs.map((s) => s.utf8 || "").join("").replace(/\s+/g, " ").trim(),
    }))
    .filter((c) => c.text) : [];
  dbg("timed_text cues: " + cues.length);
  if (!cues.length) return null;
  return {
    video_id: vd.videoId || vid,
    title: vd.title || document.title.replace(" - YouTube", ""),
    duration: parseFloat(vd.lengthSeconds || 0),
    lang: (pick.languageCode || "en").slice(0, 2),
    sub_kind: "client",
    cues,
  };
}

async function grabTranscript() {
  // Каскад чтения субтитров (октябрь 2026: YouTube закрыл прямой timed_text —
  // пустой 200 по baseUrl, а get_transcript требует proof-of-origin токен браузера):
  //   0) MAIN-мост (page-bridge.js): captionTracks + videoDetails живой страницы,
  //      без скачивания 1.5 МБ HTML (ревью P1-3: мост был мёртвым грузом)
  //   1) timed_text json3 по трекам моста — вдруг на этом видео ещё работает
  //   2) DOM-панель «Расшифровка»: программный клик, YouTube сам тянет с токенами
  //   3) fetch страницы → timed_text по трекам HTML → get_transcript (InnerTube
  //      с куками и контекстом ytcfg) — самый тяжёлый путь, последним
  //   4) null → сервер дотянет через yt-dlp (фолбэк, ловит датацентровые 429)
  const dbg = (msg) => { console.log("[VFC:transcript]", msg); return null; };
  try {
    const vid = getVideoId();
    if (!vid) return dbg("нет videoId");

    // путь 0: мост из MAIN-мира
    const bridge = await requestPlayerData();
    const tracks0 = (bridge && bridge.captions) || [];
    const vd = (bridge && bridge.videoDetails) || {};
    dbg("мост: треков " + tracks0.length + (bridge ? "" : " (не ответил)"));

    // путь 1: timed_text по трекам моста — без фетча страницы
    if (tracks0.length) {
      const viaTT = await fetchTimedText(tracks0, vd, vid, dbg);
      if (viaTT) return viaTT;
    }

    // путь 2: DOM-панель расшифровки — метаданные уже есть из моста
    const viaDom = await fetchTranscriptViaDomPanel(vd, vid, dbg);
    if (viaDom) return viaDom;

    // путь 3: скачиваем страницу — нужны треки из HTML и параметры get_transcript
    dbg("fetch страницы " + vid + "…");
    const page = await fetch(`https://www.youtube.com/watch?v=${encodeURIComponent(vid)}`, {
      credentials: "same-origin",
    });
    if (!page.ok) return dbg("fetch не удался: HTTP " + page.status);
    const html = await page.text();
    dbg("HTML получен: " + html.length + " символов");
    const m = html.match(/ytInitialPlayerResponse\s*=\s*(\{.+?\})\s*;\s*(?:var|const|let|<\/script>)/);
    if (!m) return dbg("ytInitialPlayerResponse не найден в HTML (consent? redirect?)");
    let pr;
    try { pr = JSON.parse(m[1]); } catch (e) { return dbg("JSON parse error: " + e.message); }
    const prVd = pr.videoDetails || vd;
    const tracks = (pr.captions && pr.captions.playerCaptionsTracklistRenderer
                    && pr.captions.playerCaptionsTracklistRenderer.captionTracks) || [];
    dbg("треков субтитров: " + tracks.length + (tracks.length ? " (" + tracks.map(t => t.languageCode).join(",") + ")" : ""));

    if (tracks.length && !tracks0.length) {
      const viaTT = await fetchTimedText(tracks, prVd, vid, dbg);
      if (viaTT) return viaTT;
    }

    // путь 3b: get_transcript — эндпоинт панели «Расшифровка»
    const viaGte = await fetchTranscriptEndpoint(html, prVd, vid, dbg);
    if (viaGte) return viaGte;

    if (!tracks.length && !tracks0.length) return dbg("нет субтитров у видео");
    return dbg("все клиентские пути пусты — останется серверный фолбэк");
  } catch (e) {
    return dbg("исключение: " + e.message);
  }
}

function closeTranscriptPanel() {
  // прячем панель расшифровки, которую открыли для сбора сегментов.
  // проверяем результат: если visibility-кнопка не нашлась/не сработала — Esc
  const vis = document.querySelector(
    'ytd-engagement-panel-section-list-renderer[target-id="engagement-panel-searchable-transcript"] #visibility-button button');
  if (vis) vis.click();
  const panel = document.querySelector(
    'ytd-engagement-panel-section-list-renderer[target-id="engagement-panel-searchable-transcript"]');
  if (panel && panel.getAttribute("visibility") !== "hidden") {
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  }
}

async function fetchTranscriptViaDomPanel(vd, vid, dbg) {
  // Панель «Показать расшифровку»: программный клик по кнопке в описании,
  // YouTube сам тянет транскрипт со всеми токенами, мы читаем готовые сегменты.
  // Side effects минимизируем: описание возвращаем в исходное состояние (ревью P1-4)
  let descWasCollapsed = false;
  try {
    const expander = document.querySelector("#description-inline-expander, ytd-text-inline-expander");
    descWasCollapsed = !!(expander && expander.getAttribute("collapsed") === "");
    const expand = document.querySelector("#description-inline-expander #expand, ytd-text-inline-expander #expand");
    if (expand) { expand.click(); dbg("DOM: описание раскрыто"); }
    let btn = null;
    for (let i = 0; i < 20 && !btn; i++) {
      btn = document.querySelector("ytd-video-description-transcript-section-renderer button");
      if (!btn) await new Promise((r) => setTimeout(r, 100));
    }
    if (!btn) return dbg("DOM: кнопка расшифровки не найдена (нет расшифровки?)");
    btn.click();
    let segs = [];
    for (let i = 0; i < 40 && segs.length === 0; i++) {
      await new Promise((r) => setTimeout(r, 100));
      segs = Array.from(document.querySelectorAll("ytd-transcript-segment-renderer"));
    }
    if (!segs.length) { closeTranscriptPanel(); return dbg("DOM: сегменты не появились"); }
    const cues = [];
    for (const s of segs) {
      const ts = (s.querySelector(".segment-timestamp") || {}).textContent || "";
      const tx = (s.querySelector(".segment-text") || {}).textContent || "";
      const text = tx.replace(/\s+/g, " ").trim();
      const m = ts.trim().match(/^(?:(\d+):)?(\d{1,2}):(\d{2})$/);
      if (text && m) {
        const sec = parseInt(m[1] || "0", 10) * 3600 + parseInt(m[2], 10) * 60 + parseInt(m[3], 10);
        cues.push({ start: sec, end: sec + 4, text });
      }
    }
    closeTranscriptPanel();
    // описание свернуть обратно, если было свёрнуто до нас
    if (descWasCollapsed) {
      const collapse = document.querySelector("#description-inline-expander #collapse, ytd-text-inline-expander #collapse");
      if (collapse) collapse.click();
    }
    dbg("DOM cues: " + cues.length);
    if (!cues.length) return null;
    cues.sort((a, b) => a.start - b.start);
    for (let i = 0; i < cues.length - 1; i++) {
      cues[i].end = Math.max(cues[i].start + 1, Math.min(cues[i].end, cues[i + 1].start));
    }
    return {
      video_id: vd.videoId || vid,
      title: vd.title || document.title.replace(" - YouTube", ""),
      duration: parseFloat(vd.lengthSeconds || 0),
      lang: (vd.language || "en").slice(0, 2),
      sub_kind: "client-dom",
      cues,
    };
  } catch (e) {
    try { closeTranscriptPanel(); } catch {}
    try {
      if (descWasCollapsed) {
        const collapse = document.querySelector("#description-inline-expander #collapse, ytd-text-inline-expander #collapse");
        if (collapse) collapse.click();
      }
    } catch {}
    return dbg("DOM исключение: " + e.message);
  }
}

function balancedJsonFrom(html, fromIdx) {
  // вырезает сбалансированный {...} с позиции fromIdx (первая '{'); строки и
  // escape внутри учтены — регексом ytInitialData/ytcfg не берутся (вложенность)
  let depth = 0, inStr = false, esc = false;
  for (let i = fromIdx; i < html.length; i++) {
    const ch = html[i];
    if (esc) { esc = false; continue; }
    if (inStr) {
      if (ch === "\\") esc = true;
      else if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') inStr = true;
    else if (ch === "{") depth++;
    else if (ch === "}") { depth--; if (depth === 0) return html.slice(fromIdx, i + 1); }
  }
  return null;
}

function collectTranscriptSegments(node, out) {
  if (!node || typeof node !== "object") return out;
  if (Array.isArray(node)) { for (const v of node) collectTranscriptSegments(v, out); return out; }
  if (node.transcriptSegmentRenderer) out.push(node.transcriptSegmentRenderer);
  for (const v of Object.values(node)) {
    if (v && typeof v === "object") collectTranscriptSegments(v, out);
  }
  return out;
}

async function fetchTranscriptEndpoint(html, vd, vid, dbg) {
  // POST /youtubei/v1/get_transcript с параметрами живой страницы. Из curl это
  // не воспроизводится (Precondition failed без куки-сессии), внутри страницы
  // same-origin fetch несёт куки и visitorData — как у кнопки «Расшифровка».
  try {
    let gteParams = null;
    const md = html.match(/ytInitialData\s*=\s*/);
    if (md) {
      const brace = html.indexOf("{", md.index + md[0].length);
      const jd = brace >= 0 ? balancedJsonFrom(html, brace) : null;
      if (jd) {
        const findGte = (o) => {
          if (!o || typeof o !== "object") return null;
          if (o.getTranscriptEndpoint) return o.getTranscriptEndpoint;
          for (const v of (Array.isArray(o) ? o : Object.values(o))) {
            const r = findGte(v);
            if (r) return r;
          }
          return null;
        };
        const gte = findGte(JSON.parse(jd));
        if (gte && gte.params) gteParams = gte.params;
      }
    }
    let key = null, context = null;
    // ytcfg.set( в странице несколько раз: перебираем все, ключ и контекст
    // лежат в одном из них (у первого блока их может не быть)
    let cfgAnchor = html.indexOf("ytcfg.set(");
    while (cfgAnchor >= 0 && (!key || !context)) {
      const brace = html.indexOf("{", cfgAnchor);
      const jc = brace >= 0 ? balancedJsonFrom(html, brace) : null;
      if (jc) {
        try {
          const cfg = JSON.parse(jc);
          key = key || cfg.INNERTUBE_API_KEY || null;
          context = context || cfg.INNERTUBE_CONTEXT || null;
        } catch (e) { dbg("ytcfg parse: " + e.message); }
      }
      cfgAnchor = html.indexOf("ytcfg.set(", cfgAnchor + 1);
    }
    if (!gteParams) return dbg("get_transcript: params не найдены (расшифровки нет у видео?)");
    if (!key || !context) return dbg("get_transcript: нет ytcfg ключа/контекста");
    dbg("get_transcript POST…");
    const r = await fetch(
      "https://www.youtube.com/youtubei/v1/get_transcript?key=" + encodeURIComponent(key) + "&prettyPrint=false",
      {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ context, params: gteParams }),
      });
    if (!r.ok) return dbg("get_transcript HTTP " + r.status);
    const j = await r.json();
    const segs = collectTranscriptSegments(j, []);
    const cues = segs.map((s) => ({
      start: (parseFloat(s.startMs) || 0) / 1000,
      end: ((parseFloat(s.startMs) || 0) + (parseFloat(s.durationMs) || 4000)) / 1000,
      text: ((s.snippet && s.snippet.runs) || []).map((run) => run.text || "")
        .join("").replace(/\s+/g, " ").trim(),
    })).filter((c) => c.text);
    dbg("get_transcript cues: " + cues.length);
    if (!cues.length) return null;
    return {
      video_id: vd.videoId || vid,
      title: vd.title || document.title.replace(" - YouTube", ""),
      duration: parseFloat(vd.lengthSeconds || 0),
      lang: (vd.language || "en").slice(0, 2),
      sub_kind: "client-gte",
      cues,
    };
  } catch (e) {
    return dbg("get_transcript исключение: " + e.message);
  }
}

let installIdPromise = null;  // два параллельных вызова не должны родить два UUID (ревью P2)
async function installId() {
  // install-ID: UUID на установку, аккаунт на сервере заводится сам
  if (installIdPromise) return installIdPromise;
  installIdPromise = (async () => {
    try {
      const st = await chrome.storage.local.get("vfc_install_id");
      if (st.vfc_install_id) return st.vfc_install_id;
      const id = crypto.randomUUID();
      await chrome.storage.local.set({ vfc_install_id: id });
      return id;
    } catch { return ""; }
  })();
  return installIdPromise;
}

let lastBalance = null;  // последний ответ /api/account: {free_left_today, free_daily, credits}

function setServerStatus(ok) {
  // микро-подпись статуса сервера под заголовком шапки (design/tokens.json → header_status)
  if (!panel || !panel.srv) return;
  panel.srv.classList.toggle("down", !ok);
  panel.srv.classList.toggle("up", ok);
  panel.srv.innerHTML = '<i class="dot"></i>' + (ok ? tr("srvOk") : tr("srvFail"));
}

async function showBalance() {
  const iid = await installId();
  if (!iid) return;
  let r;
  try {
    r = await fetch(API + "/api/account?install_id=" + encodeURIComponent(iid), { headers: { "X-API-Key": API_KEY } });
    lastBalance = await r.json();
    setServerStatus(true);
  } catch {
    setServerStatus(false);
    return;
  }
  // сервер ответил, но не пустил: сборка без токена/с устаревшим ключом —
  // это не «сервер не отвечает», лечится обновлением расширения
  if (r.status === 401 || String((lastBalance && lastBalance.error) || "").includes("unauthorized")) {
    lastBalance = null;
    panel.status.classList.add("err");
    panel.status.innerHTML = `<span>${tr("errUpdate")}</span>`;
    return;
  }
  renderBalance();
}

function renderBalance() {
  // баланс показывается в трёх местах: idle-строка ленты и поля кабинета-поповера
  if (!lastBalance || !panel) return;
  const free = lastBalance.free_left_today + " / " + lastBalance.free_daily;
  const idleBal = panel.root.querySelector("#vfc-idlebal");
  if (idleBal) idleBal.textContent = tr("balanceLine", { free, credits: lastBalance.credits });
  const f = panel.root.querySelector("#vfc-free");
  if (f) f.textContent = free;
  const cr = panel.root.querySelector("#vfc-credits");
  if (cr) cr.textContent = String(lastBalance.credits);
  // 0/0 в поповере — та же подсказка, что и на экране «нечем проверять» (решение №2):
  // без продажи, только объяснение и ссылка на «как это работает» рядом
  const zero = !Number(lastBalance.free_left_today) && !Number(lastBalance.credits);
  if (panel.balEmpty) {
    panel.balEmpty.classList.toggle("hidden", !zero);
    if (zero) panel.balEmpty.innerHTML = `${tr("balanceEmpty")} · <a href="#">${tr("howLink")}</a>`;
  }
}

// --- Кабинет-поповер: локальный вход (мок), баланс, пакеты кредитов ---

function storedEmail() {
  return chrome.storage.local.get("vfc_email")
    .then((st) => st.vfc_email || "").catch(() => "");
}

async function renderAuth() {
  if (!panel) return;
  if (isPublicBuild()) { panel.auth.innerHTML = ""; return; }  // email-мок спрятан (решение №6)
  const email = await storedEmail();
  if (email) {
    panel.auth.innerHTML =
      `<div class="who"><span class="em" title="${escapeHtml(email)}">${escapeHtml(email)}</span>` +
      `<button class="mini" type="button" id="vfc-signout">${tr("btnSignOut")}</button></div>` +
      `<div class="mocknote">${tr("mockNote")}</div>`;
    panel.auth.querySelector("#vfc-signout").addEventListener("click", async () => {
      try { await chrome.storage.local.remove("vfc_email"); } catch {}
      renderAuth();
    });
    return;
  }
  panel.auth.innerHTML =
    `<div class="signin">` +
    `<input type="email" id="vfc-email" placeholder="${tr("emailPlaceholder")}" aria-label="${tr("emailLabel")}">` +
    `<button class="mini" type="button" id="vfc-signin">${tr("btnSignIn")}</button></div>` +
    `<div class="mocknote">${tr("mockNote")}</div>` +
    `<div class="autherr hidden" id="vfc-auth-err"></div>`;
  const input = panel.auth.querySelector("#vfc-email");
  const err = panel.auth.querySelector("#vfc-auth-err");
  const signIn = async () => {
    const val = (input.value || "").trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val)) {
      err.textContent = tr("emailInvalid");
      err.classList.remove("hidden");
      input.focus();
      return;
    }
    // локальный мок: email никуда не отправляется, живёт в chrome.storage
    try { await chrome.storage.local.set({ vfc_email: val }); } catch {}
    renderAuth();
  };
  panel.auth.querySelector("#vfc-signin").addEventListener("click", signIn);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") signIn(); });
}

async function fillInstallId() {
  const iid = await installId();
  if (panel && panel.iid) panel.iid.textContent = iid ? iid.slice(0, 8) + "…" : "";
}

function togglePop(force) {
  if (!panel) return;
  const open = force !== undefined ? force : panel.pop.classList.contains("hidden");
  panel.pop.classList.toggle("hidden", !open);
  panel.profile.setAttribute("aria-expanded", String(open));
  if (!open) { panel.profile.focus({ preventScroll: true }); return; }
  panel.pop.style.top = panel.profile.offsetTop + panel.profile.offsetHeight + 8 + "px";
  renderAuth();
  fillInstallId();
  verdictLangPref().then((v) => { if (panel && panel.vlang) panel.vlang.value = v; });
  showBalance();
  const input = panel.pop.querySelector("input");
  (input || panel.pop).focus({ preventScroll: true });
}

async function verdictLangPref() {
  // настройка «язык проверки»: "auto" (по умолчанию — локаль браузера) | "ru" | "en"
  try {
    const st = await chrome.storage.local.get("vfc_verdict_lang");
    return st.vfc_verdict_lang || "auto";
  } catch { return "auto"; }
}
function effectiveVerdictLang(pref) {
  return pref === "ru" || pref === "en" ? pref : uiLang();
}

let popDismissBound = false;
function bindPopDismissals() {
  // закрытие кликом вне и Esc; слушатели документа заводятся один раз на вкладку
  if (popDismissBound) return;
  popDismissBound = true;
  document.addEventListener("pointerdown", (e) => {
    if (!panel || panel.pop.classList.contains("hidden")) return;
    const path = e.composedPath ? e.composedPath() : [];
    if (path.includes(panel.pop) || path.includes(panel.profile)) return;
    togglePop(false);
  }, true);
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !panel || panel.pop.classList.contains("hidden")) return;
    togglePop(false);
  });
}

let topupBusy = false;
async function doTopup(n) {
  if (topupBusy || !panel) return;
  topupBusy = true;
  panel.topupErr.classList.add("hidden");
  panel.packs.forEach((b) => { b.disabled = true; });
  try {
    const r = await fetch(API + "/api/topup", {
      method: "POST", headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
      body: JSON.stringify({ install_id: await installId(), credits: n }),
    });
    const data = await r.json();
    if (data && data.error) {
      // ошибка сервера показывается его текстом (мокап выключен, лимит и т.п.)
      panel.topupErr.textContent = String(data.error);
      panel.topupErr.classList.remove("hidden");
    } else {
      await showBalance();  // ответ topup и есть аккаунт, но обновляем через общий путь
      showToast(tr("toastTopup", { n }));
    }
  } catch {
    panel.topupErr.textContent = tr("errServer");
    panel.topupErr.classList.remove("hidden");
  } finally {
    topupBusy = false;
    if (panel) panel.packs.forEach((b) => { b.disabled = false; });
  }
}

let toastTimer = 0;
function showToast(text) {
  if (!panel) return;
  panel.toast.textContent = text;
  panel.toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { if (panel) panel.toast.classList.remove("show"); }, 2600);
}

// --- Экраны «нечем проверять», квота-баннер, параллельные прогоны (решения №2, №3, №9) ---

function isEmptyBalance() {
  // последний известный баланс: ни свободных проверок, ни кредитов
  return !!(lastBalance && !Number(lastBalance.free_left_today) && !Number(lastBalance.credits));
}

function untilUtcMidnight() {
  // дневная квота обнуляется в полночь UTC (store._account_view) — считаем до сброса
  const now = new Date();
  let ms = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1) - now.getTime();
  if (ms < 0) ms = 0;
  let h = Math.floor(ms / 3600000), m = Math.round((ms % 3600000) / 60000);
  if (m === 60) { h += 1; m = 0; }
  return `${h}:${String(m).padStart(2, "0")}`;
}

function renderBalanceEmpty() {
  // экран «дневной лимит исчерпан» до старта (решение №2): без кнопок покупки —
  // только объяснение, время до сброса и «как это работает»; прогон не запускаем
  panel.status.classList.remove("err");
  panel.status.innerHTML = "<span></span>";
  panel.feed.innerHTML =
    `<div class="empty"><b>${tr("balanceEmpty")}</b><br>` +
    `<span>${tr("balanceResetIn", { time: untilUtcMidnight() })}</span><br>` +
    `<button class="how" type="button">${tr("howLink")}</button></div>`;
  panel.counts.classList.add("hidden");
  panel.quota.classList.add("hidden");
  syncFeedTabs();
  syncDlButton();
  const how = panel.feed.querySelector("button.how");
  if (how) how.addEventListener("click", () => {
    // пояснение «что бесплатно / что стоит» живёт в поповере кабинета
    togglePop(true);
    panel.howbody.classList.remove("hidden");
    panel.how.setAttribute("aria-expanded", "true");
  });
}

async function hasLiveRunElsewhere(videoId) {
  // клиентская эвристика параллельных прогонов (решение №3): в vfc_runs есть
  // незавершённый (не протухший, TTL 6 ч как у resume) прогон ДРУГОГО видео
  try {
    const all = (await chrome.storage.local.get("vfc_runs")).vfc_runs || {};
    const now = Date.now();
    return Object.keys(all).some((k) => k !== videoId && now - (all[k].at || 0) <= 6 * 3600e3);
  } catch { return false; }
}

function renderParallelWarning() {
  // неблокирующее предупреждение (решение №3): «Всё равно проверить» / «Отмена»
  setStatus(`<span>${tr("warnParallel")}</span>`);
  panel.feed.innerHTML =
    `<div class="warnbox"><div class="warntext">${tr("warnParallelText")}</div>` +
    `<div class="warnbtns">` +
    `<button class="mini" type="button" id="vfc-force-run">${tr("btnForceRun")}</button>` +
    `<button class="mini" type="button" id="vfc-cancel-run">${tr("btnCancel")}</button>` +
    `</div></div>`;
  panel.counts.classList.add("hidden");
  panel.quota.classList.add("hidden");
  syncFeedTabs();
  syncDlButton();
  panel.feed.querySelector("#vfc-force-run").addEventListener("click", () => startCheck(true));
  panel.feed.querySelector("#vfc-cancel-run").addEventListener("click", () => {
    setStatus(tr("idle"));
    panel.feed.innerHTML = idleMarkup();
    renderBalance();
    syncFeedTabs();
    syncDlButton();
  });
}

async function maybeQuotaBanner(st, videoId) {
  // хвост «не проверено» + свежий баланс 0/0 → баннер «свободные проверки
  // закончились» без «Продолжить с кредитов» (решение №9). Хвост от лимита
  // прогона (15 утверждений) баннером не помечаем — у карточек своя подсказка
  const c = (st.summary && st.summary.counts) || {};
  if (!((c["не проверено"] || 0) > 0)) return;
  await showBalance();
  if (!panel || state.videoId !== videoId) return;  // уход с видео между await (P1-1)
  if (isEmptyBalance()) {
    panel.quota.textContent = tr("quotaBanner");
    panel.quota.classList.remove("hidden");
  }
}

async function startCheck(force) {
  // честный отказ до тяжёлой работы: shorts-вёрстка и не-видео страницы (Сл-9) —
  // панель может быть открыта иконкой тулбара (ensurePanel(true))
  const refuse = (msg) => {
    if (!panel) return;
    setStatus(`<span>${msg}</span>`);
    panel.status.classList.add("err");
    panel.run.disabled = false;
    panel.run.textContent = tr("btnRun");
    syncActionButton();
  };
  if (location.pathname.startsWith("/shorts/")) { refuse(tr("errShorts")); return; }
  const videoId = getVideoId();
  if (!videoId) { refuse(tr("errNoVideo")); return; }
  // 0/0: экран «лимит исчерпан» вместо прогона (решение №2); баланс перечитываем —
  // локальная копия могла протухнуть с последней полуночи UTC
  if (isEmptyBalance()) {
    await showBalance();
    if (!panel || getVideoId() !== videoId) return;  // уход с видео между await (P1-1)
    if (isEmptyBalance()) { renderBalanceEmpty(); return; }
  }
  // живой прогон другого видео: неблокирующее предупреждение (решение №3);
  // force = «Всё равно проверить» из предупреждения
  if (!force && await hasLiveRunElsewhere(videoId)) {
    if (!panel || getVideoId() !== videoId) return;
    renderParallelWarning();
    return;
  }
  const epoch = navEpoch;  // уход с видео среди await — тишина, не порти новое состояние (P1-1)
  // live-детект (Сл-8): строго isLive===true — завершённый эфир проверять можно
  const vdLive = await requestPlayerData().catch(() => null);
  if (epoch !== navEpoch) return;
  if (vdLive && vdLive.videoDetails && vdLive.videoDetails.isLive === true) {
    refuse(tr("errLive")); return;
  }
  panel.run.disabled = true;
  panel.run.classList.remove("hidden");
  panel.run.textContent = tr("btnChecking");
  runProgress = null;
  syncActionButton();
  state = freshState(videoId);
  state.startedAt = Date.now();
  setStatus(tr("readingSubs"), true);
  panel.feed.innerHTML = `<div class="empty">${tr("starting")}</div>`;
  panel.counts.classList.add("hidden");
  panel.quota.classList.add("hidden");
  syncFeedTabs();
  syncDlButton();
  try {
    const transcript = await grabTranscript();
    if (epoch !== navEpoch) return;
    state.transcript = transcript;  // null → сервер сам дотянет через yt-dlp (фолбэк)
    if (!transcript) {
      setStatus(tr("errSubsNotRead"), false);
      panel.status.classList.add("err");
    }
    const r = await fetch(API + "/api/check", {
      method: "POST", headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
      body: JSON.stringify({
        url: `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`,
        transcript,  // null → сервер сам дотянет через yt-dlp (фолбэк)
        install_id: await installId(),
        verdict_lang: effectiveVerdictLang(await verdictLangPref()),
      }),
    });
    const data = await r.json();
    if (epoch !== navEpoch) return;
    setServerStatus(true);
    // сервер ответил кодом ошибки — прогоняем через finishWithError,
    // а не маскируем под «сервер не отвечает» в catch ниже
    if (data.error) { finishWithError(data.error); return; }
    state.runId = data.run_id;
    await storeRun(videoId, data.run_id);
    if (epoch !== navEpoch) return;  // storeRun тоже await — видео могли сменить
    // фича A: транскрипт уже в руках — текст видео в ленте сразу, факты
    // встроятся по таймкоду; без транскрипта — скелетоны как раньше
    if (state.transcript && state.transcript.cues && state.transcript.cues.length) {
      renderTranscriptFeed(state.transcript.cues);
    } else {
      renderSkeletons();
    }
    syncFeedTabs();
    startPolling();
  } catch (e) {
    if (epoch !== navEpoch || !panel) return;  // panel мог исчезнуть на не-watch (P1-1)
    setServerStatus(false);
    setStatus(tr("errServer"));
    panel.run.disabled = false;
    panel.run.textContent = tr("btnRun");
    syncActionButton();
  }
}

function startPolling() {
  stopPolling();  // пересоздание панели посреди прогона не должно плодить интервалы
  pollStatus();
  state.pollTimer = setInterval(pollStatus, 3000);
}
function stopPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = null;
}

async function pollStatus() {
  if (!state.runId) return;
  const runId = state.runId, videoId = state.videoId;  // сверка после await: ушли с видео — не пишем (P1-1)
  let st;
  try {
    const r = await fetch(`${API}/api/run/${runId}`, { headers: { "X-API-Key": API_KEY } });
    st = await r.json();
  } catch {
    if (panel && state.runId === runId) setServerStatus(false);
    return;
  }
  if (!panel || state.runId !== runId || state.videoId !== videoId) return;
  setServerStatus(true);
  if (!st.status) { finishWithError(st.error || tr("errNoRun")); return; }

  if (st.status === "done") {
    state.done = true;
    const c = st.summary && st.summary.counts || {};
    setStatus(tr("done", { t: c["правда"] || 0, f: c["ложно"] || 0, s: c["странно"] || 0 }));
    // фоновый прогон завершился при свёрнутой панели — тихий бейдж «результат готов»
    if (panelMode === "mini") setMiniDone(true);
    maybeQuotaBanner(st, videoId);  // хвост «не проверено» при исчерпанной квоте (решение №9)
  } else if (st.status === "error") {
    finishWithError(st.error || "");
  } else if (st.status !== "running") {
    // статус вне done/error/running: прогон завис или отменён — ошибка вместо вечного спиннера
    finishWithError(st.error || tr("errOtherEmpty"));
  } else {
    // этапный прогресс: транскрипт 0-8% → утверждения 8-55% → вердикты 55-97%
    const frac = (ph) => {
      const m = (ph || "").match(/(\d+)\/(\d+)/);
      return m ? parseInt(m[1], 10) / Math.max(1, parseInt(m[2], 10)) : 0;
    };
    let human, pct = 50;
    if (!st.phase) { human = tr("phaseFallback"); }
    else if (st.phase === "transcript") { human = tr("phaseTranscript"); pct = 5; }
    else if (st.phase.startsWith("claims")) {
      human = tr("phaseClaims", { progress: escapeHtml(st.phase.slice(7)) });
      pct = 8 + Math.round(47 * frac(st.phase));
    } else if (st.phase.startsWith("verdict")) {
      const elapsed = state.startedAt ? fmtElapsed(Date.now() - state.startedAt) : "";
      human = tr("phaseVerdict", { progress: escapeHtml(st.phase.slice(8)), time: elapsed,
        skip: `<a class="skip" href="#">${tr("skipWait")}</a>` });
      pct = 55 + Math.round(42 * frac(st.phase));
    } else human = tr("phaseFallback");
    setStatus(human, true, pct);
    const skip = panel.status.querySelector(".skip");
    if (skip) skip.addEventListener("click", (e) => { e.preventDefault(); onSkipWait(); });
  }

  if (st.claims) {
    // скелетоны/транскрипт живут до первого вердикта; финал без вердиктов → карточки «не проверено»
    if (st.claims.some((c) => c.verdict) || st.status === "done") {
      state.claims = st.claims;
      renderCurrent(st);
      const dur = (st.summary && st.summary.duration) || (getVideoEl() && getVideoEl().duration) || 0;
      renderTimeline(st.claims, dur);
    }
  }
  if (st.summary) renderCounts(st.summary);
  if (st.status === "done" && st.summary && st.summary.no_claims) {
    const msg = `<div class="empty"><b>${tr("noClaims")}</b><br>${tr("noClaimsHint")}</div>`;
    // в режиме «Текст» транскрипт остаётся читабельным — вывод добавляем поверх него
    if (state.feedMode === "text" && state.transcript && state.transcript.cues && state.transcript.cues.length) {
      panel.feed.insertAdjacentHTML("afterbegin", msg);
    } else {
      panel.feed.innerHTML = msg;
    }
  }
  if (st.status === "done" || st.status === "error") {
    saveHistory(videoId, st);  // итог переживёт F5 и переходы (restoreHistory); id снят до await
    stopPolling();
    panel.run.disabled = false;
    // повторный прогон запрещён: на проверенном видео
    // кнопки запуска нет — только результат; после ошибки повтор разрешён
    if (st.status === "done") panel.run.classList.add("hidden");
    else panel.run.textContent = tr("btnRun");
    syncActionButton();
    // и при done, и при error: мёртвый run не должен 6 ч авто-открывать панель
    // с ошибкой при каждом заходе на видео (приёмка карты сценариев, Сл-10)
    clearStoredRun(videoId);
  }
}

function finishWithError(raw) {
  const msg = (raw || "").toLowerCase();
  let human;
  if (msg.includes("не скачались") || msg.includes("ограничил запросы")) human = tr("errSubsLimited");
  else if (msg.includes("субтитр")) human = tr("errNoSubs");
  else if (msg.includes("перезапущен") || msg.includes("перезапустился")) human = tr("errRestart");
  else if (msg.includes("плейлист") || msg.includes("playlist")) human = tr("errPlaylist");
  else if (msg.includes("unauthorized")) human = tr("errUpdate");
  else if (raw) human = tr("errOther", { text: escapeHtml(String(raw).slice(0, 90)) });
  else human = tr("errOtherEmpty");
  panel.status.classList.add("err");
  panel.status.innerHTML = `<span>${human}</span>`;
  if (panel.feed.querySelector(".skel")) panel.feed.innerHTML = `<div class="empty">${tr("empty")}</div>`;
  stopPolling();
  panel.run.disabled = false;
  panel.run.textContent = tr("btnRun");
  syncActionButton();
}

function onSkipWait() {
  // «не ждать»: прогон живёт на сервере, поллинг продолжается — результат придёт
  // сам; панель сворачивается в кружок, чтобы не занимать экран (сценарий С2)
  setStatus(tr("skipped"));
  setPanelMode("mini");
}

function setStatus(html, spinner = false, pct = null) {
  panel.status.classList.remove("err");
  let bar = "";
  if (pct !== null && pct !== undefined) {
    // тонкая полоса этапного прогресса: сущности приезжают, юзер видит сколько осталось
    bar = `<span class="phasebar" aria-hidden="true"><i style="width:${Math.min(100, Math.max(0, pct))}%"></i></span>`;
  }
  panel.status.innerHTML = (spinner ? '<div class="spin"></div>' : "") + `<span>${html}</span>` + bar;
}

async function storeRun(videoId, runId) {
  try {
    const all = (await chrome.storage.local.get("vfc_runs")).vfc_runs || {};
    all[videoId] = { runId, at: Date.now() };
    await chrome.storage.local.set({ vfc_runs: all });
  } catch {}
}
async function clearStoredRun(videoId) {
  try {
    const all = (await chrome.storage.local.get("vfc_runs")).vfc_runs || {};
    delete all[videoId];
    await chrome.storage.local.set({ vfc_runs: all });
  } catch {}
}
async function saveHistory(videoId, st) {
  // сохраняем итог прогона: вердикты переживут F5 и переходы
  try {
    const all = (await chrome.storage.local.get("vfc_history")).vfc_history || {};
    all[videoId] = {
      runId: state.runId,
      claims: st.claims || [],
      summary: st.summary || {},
      status: st.status || "",  // done/error/running: restoreHistory решает, «Готово» или ошибка
      error: st.error || "",
      at: Date.now(),
    };
    // храним максимум 50 последних видео (v0.9.0: лимит по количеству вместо 24-часового
    // TTL — историю целиком читает account.html, формат записей не меняется)
    const keys = Object.keys(all);
    if (keys.length > 50) {
      keys.sort((a, b) => (all[a].at || 0) - (all[b].at || 0));
      for (let i = 0; i < keys.length - 50; i++) delete all[keys[i]];
    }
    await chrome.storage.local.set({ vfc_history: all });
  } catch {}
}

async function restoreHistory(videoId) {
  // восстановление вердиктов при возврате на видео (F5, SPA-навигация);
  // v0.9.0: живёт всё, что хранится (50 последних), 24-часовой TTL снят (решение №7)
  try {
    const all = (await chrome.storage.local.get("vfc_history")).vfc_history || {};
    const h = all[videoId];
    if (!h) return false;
    state.claims = h.claims || [];
    state.transcript = null;   // транскрипт в истории не хранится —
    state.feedMode = "facts"; // лента после возврата только с карточками (фича A)
    if (h.summary) renderCounts(h.summary);
    renderCurrent({ claims: state.claims });
    syncFeedTabs();
    syncDlButton();
    const dur = (h.summary && h.summary.duration) || (getVideoEl() && getVideoEl().duration) || 0;
    renderTimeline(state.claims, dur);
    // прогон не done и не running (error или завис) — статус ошибки, а не вечная загрузка
    if (h.status && h.status !== "done" && h.status !== "running") {
      const msg = h.error
        ? tr("errOther", { text: escapeHtml(String(h.error).slice(0, 90)) })
        : tr("errOtherEmpty");
      panel.status.classList.add("err");
      panel.status.innerHTML = `<span>${msg}</span>`;
      return true;
    }
    const c = (h.summary && h.summary.counts) || {};
    setStatus(tr("done", { t: c["правда"] || 0,
                           f: c["ложно"] || 0,
                           s: c["странно"] || 0 }));
    state.done = true;  // готовый результат: кнопка под видео открывает, не перезапускает
    // повторный прогон запрещён: кнопки запуска на проверенном видео нет
    panel.run.disabled = false;
    panel.run.classList.add("hidden");
    syncActionButton();
    return true;
  } catch { return false; }
}

async function resumeStoredRun() {
  // вернулся к видео с живым/завершённым прогоном — продолжаем показывать
  try {
    const videoId = getVideoId();
    const all = (await chrome.storage.local.get("vfc_runs")).vfc_runs || {};
    // между await и чтением storage пользователь мог уйти на другое видео (P1-1)
    if (!panel || getVideoId() !== videoId) return false;
    const rec = all[videoId];
    if (!rec || Date.now() - rec.at > 6 * 3600e3) return false;
    state.runId = rec.runId;
    state.startedAt = rec.at;
    panel.run.disabled = true;
    panel.run.textContent = tr("btnChecking");
    runProgress = null;
    syncActionButton();
    setStatus(tr("resume"), true);
    // транскрипт мог остаться в state (панель стёрта среди видео) — текст ценнее скелетонов
    if (state.transcript && state.transcript.cues && state.transcript.cues.length) {
      renderTranscriptFeed(state.transcript.cues);
    } else {
      renderSkeletons();
    }
    startPolling();
    return true;  // иначе restoreHistory затрёт возобновлённый прогон старой историей
  } catch { return false; }
}

function renderSkeletons() {
  // плейсхолдеры фазы running (verdict-stream §3): до первого вердикта лента занята
  const one = `<div class="card skel"><div class="statebg">
    <div class="row1"><span class="sk sk-badge"></span></div>
    <span class="sk sk-line"></span><span class="sk sk-line short"></span>
  </div></div>`;
  panel.feed.innerHTML = one.repeat(4);
}

let lastSummary = null;  // последний summary: клик по фильтру перерисовывает счётчики без нового poll

function renderCounts(s) {
  // стек-полоса «полоса правды видео»: доли вердиктов + четыре подписи-цифры под ней;
  // пустой прогон — полоса целиком цвета unchecked. Сегменты и подписи — фильтры
  // ленты (фикс 9): клик оставляет в ленте карточки одного вердикта, повторный — все
  lastSummary = s;
  const c = s.counts || {};
  const total = s.claims_total || 0, checked = s.checked || 0;
  const L = I18N[uiLang()];
  const items = [
    { v: "правда", n: c["правда"] || 0, color: BAR_COLOR["правда"], label: L.vTrue },
    { v: "ложно", n: c["ложно"] || 0, color: BAR_COLOR["ложно"], label: L.vFalse },
    { v: "странно", n: c["странно"] || 0, color: BAR_COLOR["странно"], label: L.vStrange },
    { v: "не проверено", n: c["не проверено"] || 0, color: BAR_COLOR["не проверено"], label: L.cntNone },
  ];
  const sum = items.reduce((a, i) => a + i.n, 0);
  const segs = sum > 0
    ? items.filter((i) => i.n > 0).map((i) =>
        `<i class="${state.filter ? "flt" : ""}${state.filter === i.v ? " active" : ""}" data-v="${i.v}"` +
        ` style="width:${((i.n / sum) * 100).toFixed(2)}%;background:${i.color}" title="${i.label} ${i.n}"></i>`).join("")
    : `<i style="width:100%;background:${BAR_COLOR["не проверено"]}"></i>`;
  const nums = items.map((i) => {
    const active = state.filter === i.v;
    const zero = i.n <= 0;
    const title = zero ? `${i.label} ${i.n}`
      : active ? tr("filterReset") : tr("filterTitle", { v: i.label });
    return `<button class="sn${zero ? " zero" : ""}${active ? " active" : ""}" type="button" data-v="${i.v}"` +
      `${zero ? " disabled" : ` aria-pressed="${active}"`} title="${escapeHtml(title)}">` +
      `<i style="background:${i.color}"></i>${i.label} <b>${i.n}</b></button>`;
  }).join("");
  const t = tr("countsTitle", { checked, total });
  panel.counts.title = t;
  panel.counts.innerHTML =
    `<div class="stackbar${state.filter ? " filtered" : ""}" role="group" aria-label="${escapeHtml(t)}">${segs}</div>` +
    `<div class="stacknums">${nums}</div>`;
  panel.counts.classList.remove("hidden");
  panel.counts.querySelectorAll("[data-v]").forEach((el) => {
    if (el.tagName === "BUTTON" && el.disabled) return;  // нулевой счётчик не фильтрует
    el.addEventListener("click", () => {
      const v = el.dataset.v;
      state.filter = state.filter === v ? null : v;  // повторный клик снимает фильтр
      renderCounts(lastSummary);
      renderCurrent({ claims: state.claims });
    });
  });
  runProgress = { checked, total };  // счётчик для кнопки в ряду действий
  syncActionButton();
}

function renderClaims(st) {
  // режим «Факты»: только карточки утверждений (как до стриминга транскрипта)
  const L = I18N[uiLang()];
  const scroll = panel.feed.scrollTop;
  // фильтр ленты (фикс 9): оставляем только карточки выбранного вердикта;
  // data-i хранит исходный индекс — по нему onTimeUpdate находит «текущую» карточку
  const f = state.filter;
  const items = st.claims.map((c, i) => ({ c, i }))
    .filter(({ c }) => !f || (f === "не проверено" ? !c.verdict : c.verdict === f));
  if (!items.length) {
    const lab = f ? escapeHtml(verdictLabel(f === "не проверено" ? null : f)) + " — " : "";
    panel.feed.innerHTML = `<div class="empty">${f ? lab + tr("filterEmpty") : tr("empty")}</div>`;
    return;
  }
  panel.feed.innerHTML = items.map(({ c, i }) => claimCardHTML(c, i, L)).join("");
  markNewCards();
  bindFeedHandlers();
  if (!state.userScrolled) panel.feed.scrollTop = scroll;
}

function renderCurrent(st) {
  // диспетчер ленты (фича A): «Текст» — транскрипт с карточками по таймкоду,
  // «Факты» — только карточки; без транскрипта всегда «Факты»
  syncDlButton();
  if (state.feedMode === "text" && state.transcript && state.transcript.cues && state.transcript.cues.length) {
    renderFeed(state.transcript.cues, st.claims || state.claims);
  } else {
    renderClaims(st);
  }
}

function renderTranscriptFeed(cues) {
  // фича A: текст видео в ленте сразу после grabTranscript, скелетоны не нужны;
  // факты встроятся по таймкоду в renderFeed, когда pollStatus их принесёт
  const L = I18N[uiLang()];
  const dc = dedupCues(cues);
  if (!dc.length) { renderSkeletons(); return; }
  panel.feed.innerHTML = groupCues(dc).map((g) => transcriptGroupHTML(dc, g, null, L)).join("");
  bindFeedHandlers();
}

function renderFeed(cues, claims) {
  // фича A, вариант B: транскрипт + карточки по таймкоду. Для каждого утверждения
  // находим ближайший cue (бинарный поиск) и вставляем карточку перед ним;
  // группы транскрипта без карточек сворачиваем в «··· ещё N фрагментов»
  const L = I18N[uiLang()];
  const scroll = panel.feed.scrollTop;
  const f = state.filter;
  const items = claims.map((c, i) => ({ c, i }))
    .filter(({ c }) => !f || (f === "не проверено" ? !c.verdict : c.verdict === f))
    .sort((a, b) => (a.c.t_start || 0) - (b.c.t_start || 0));
  const dc = dedupCues(cues);
  const before = new Map();  // индекс cue → карточки перед его строкой
  for (const it of items) {
    const k = nearestCueIndex(dc, it.c.t_start || 0);
    if (!before.has(k)) before.set(k, []);
    before.get(k).push(it);
  }
  const parts = [];
  let run = [];  // подряд идущие группы без карточек — один свёрнутый блок
  const flush = () => {
    if (!run.length) return;
    if (run.some((g) => state.unfolded.has(g.bucket))) {
      for (const g of run) parts.push(transcriptGroupHTML(dc, g, before, L));
    } else {
      const n = run.reduce((a, g) => a + g.cues.length, 0);
      parts.push(`<div class="tmore" role="button" tabindex="0" data-b="${run.map((g) => g.bucket).join(",")}">` +
        `··· ${escapeHtml(moreFragsLabel(n))}</div>`);
    }
    run = [];
  };
  for (const g of groupCues(dc)) {
    const hasCards = g.cues.some((k) => before.has(k));
    if (!before.size || hasCards) { flush(); parts.push(transcriptGroupHTML(dc, g, before, L)); }
    else run.push(g);
  }
  flush();
  panel.feed.innerHTML = parts.join("");
  markNewCards();
  bindFeedHandlers();
  if (!state.userScrolled) panel.feed.scrollTop = scroll;
}

function transcriptGroupHTML(dc, g, before, L) {
  // одна ~30-сек группа транскрипта; before — Map (индекс cue → карточки) или null.
  // Таймкод у каждой строки: единая колонка с карточками, клик — перемотка
  // (как в родной расшифровке YouTube); карточки встают перед строкой своего cue
  const lines = g.cues.map((k) => {
    const cue = dc[k];
    const cards = before && before.has(k)
      ? before.get(k).map(({ c, i }) => claimCardHTML(c, i, L)).join("") : "";
    const ts = `<span class="ts" role="button" tabindex="0" data-t="${Math.floor(cue.start || 0)}"` +
      ` title="${tr("jumpTitle", { t: fmtTS(cue.start || 0) })}">${fmtTS(cue.start || 0)}</span>`;
    return `${cards}<div class="tline">${ts}<span class="ttext">${escapeHtml(cue.text)}</span></div>`;
  }).join("");
  return `<div class="tgroup" data-b="${g.bucket}">${lines}</div>`;
}

// вес источника (дилемма наука-vs-sonar, шаг 1): sonar тоже находит научные
// статьи — они подсвечиваются пилюлей и встают первыми в списке источников.
// Список доменов суффиксный: nature.com покрывает и поддомены
const SCI_DOMAINS = new Set([
  "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "europepmc.org", "nature.com",
  "science.org", "sciencedirect.com", "springer.com", "link.springer.com",
  "wiley.com", "onlinelibrary.wiley.com", "elsevier.com", "thelancet.com",
  "lancet.com", "nejm.org", "bmj.com", "jamanetwork.com", "mdpi.com",
  "plos.org", "journals.plos.org", "frontiersin.org", "biorxiv.org",
  "medrxiv.org", "arxiv.org", "cochranelibrary.com", "academic.oup.com",
  "tandfonline.com", "pubs.acs.org", "ieeexplore.ieee.org",
  "biomedcentral.com", "springeropen.com", "doi.org",
]);
const ORG_DOMAINS = new Set(["who.int", "un.org", "oecd.org", "worldbank.org", "imf.org",
  "gov.ru", "gov.uk", "gov.cn", "usa.gov"]);
const ORG_SUFFIXES = [".gov", ".gov.ru", ".gov.uk", ".gov.cn", ".int"];
function domainKind(domain) {
  const d = String(domain || "").toLowerCase().replace(/^www\./, "").replace(/\/.*$/, "");
  if (!d) return null;
  for (const s of SCI_DOMAINS) if (d === s || d.endsWith("." + s)) return "sci";
  for (const s of ORG_DOMAINS) if (d === s || d.endsWith("." + s)) return "org";
  for (const suf of ORG_SUFFIXES) if (d.endsWith(suf)) return "org";
  if (d.endsWith(".edu")) return "sci";
  return null;
}
function kindPill(kind, full) {
  if (!kind) return "";
  const label = kind === "sci" ? tr(full ? "kindSciFull" : "kindSci") : tr("kindOrg");
  return `<span class="srckind ${kind}">${label}</span>`;
}

function claimCardHTML(c, i, L) {
  // разметка карточки утверждения — общая для режимов «Текст» и «Факты»;
  // фиксы 3/6/7/8 (seekTo, шкала уверенности, расхождение проходов, блоки
  // источников) живут здесь
  const v = c.verdict || null;
  const cls = v ? VERDICT_CLASS[v] : "v-none";
  const label = verdictLabel(v);
  const safeUrl = (u) => /^https?:\/\//.test(u) ? escapeHtml(u) : "#";
  // фича C: без вердикта и с дословной цитатой — карточка-конспект вместо заглушки
  const note = !v && (c.quote || "").trim();
  const long = !note && (c.claim || "").length > 90;
  const expanded = !note && state.expanded.has(c.hash);
  // шкала уверенности (фикс 6): три сегмента 18×4 + подпись уровня цветом
  let conf = "";
  if (c.result && c.result.confidence && v) {
    const dots = CONF_DOTS[c.result.confidence] || 0;
    const confTitle = tr("confTitle", { level: confLabel(c.result.confidence) });
    conf = `<span class="conf" style="color:${CONF_COLOR[c.result.confidence] || "#9aa0a6"}" title="${confTitle}" aria-label="${confTitle}">` +
      `<span class="segs">` + [1, 2, 3].map((k) => `<i class="${k <= dots ? "on" : ""}"></i>`).join("") + `</span>` +
      `<span class="lvl">${confLabel(c.result.confidence)}</span></span>`;
  }
  // расхождение проходов (фикс 7): вместо технической фразы — вывод каждого
  // прохода отдельной строкой; passes — массив вердиктов от бэкенда
  let why = "";
  if (c.why) {
    const passes = (c.result && Array.isArray(c.result.passes)) ? c.result.passes : null;
    if (passes && passes.length > 1 && c.why.includes("Проходы разошлись")) {
      const lines = passes.map((p, k) => {
        const name = k === 0 ? tr("splitFirst") : k === 1 ? tr("splitSecond") : `${k + 1}:`;
        return `<div class="spline">${name} <b style="color:${VERDICT_COLOR[p] || "#9aa0a6"}">${verdictLabel(p)}</b></div>`;
      }).join("");
      why = `<div class="why split"><div class="sphead">${tr("splitHead")}</div>${lines}</div>`;
    } else {
      why = `<div class="why">${escapeHtml(c.why)}</div>`;
    }
  }
  // этап 2.5 — косвенные научные свидетельства;
  // шаг 2 (v0.7.0): смежные/нерелевантные статьи (relevance adjacent/off)
  // блок не показывают — ретрив-шум отфильтрован; на старых прогонах поля нет,
  // считаем прямым. Конфликт = «правда» vs refutes, «ложно» vs supports ИЛИ
  // вердикт уже понижен наукой на сервере (science_flip: «странно» + склеенный
  // why) — тогда наука тоже первой, sonar с префиксом
  let plaus = "";
  const pl = c.result && c.result.plausibility;
  const flip = (c.result && c.result.science_flip) || "";
  const plDirect = !pl || pl.relevance === undefined || pl.relevance === "directly_on_topic";
  const plausConflict = !!(pl && pl.why && plDirect &&
    (flip ||
     (pl.relation === "refutes" && v === "правда") ||
     (pl.relation === "supports" && v === "ложно")));
  if (pl && pl.why && plDirect &&
      (pl.relation === "refutes" ||
       (pl.relation === "supports" && (v === "ложно" || flip === "supports")))) {
    const src = pl.source || {};
    plaus = `<div class="plaus"><span class="plaus-head">${tr(pl.relation === "refutes" ? "plausHead" : "plausHeadSup")}</span> ` +
      `<span class="plaus-why">${escapeHtml(pl.why)}</span>` +
      (src.title ? ` <a class="plaus-src" href="${safeUrl(src.url)}" target="_blank" rel="noopener" ` +
        `title="${escapeHtml(pl.quote || "")}">${kindPill("sci", true)}${escapeHtml(src.title)}${src.year ? " · " + escapeHtml(String(src.year)) : ""}</a>` : "") +
      `</div>`;
  }
  // источники (фикс 8): свёрнуто — домены в строку с цитатой в tooltip;
  // раскрыто — каждый источник блоком с полной цитатой и ссылкой.
  // Сортировка по весу: научные и официальные первыми (sort в V8 стабилен)
  const RANK = { sci: 0, org: 1, null: 2 };
  const votes = (((c.result && c.result.votes) || [])).slice()
    .sort((a, b) => RANK[domainKind(a.domain)] - RANK[domainKind(b.domain)]);
  let srcs = "";
  if (!note) {
    if (expanded) {
      srcs = votes.map((s) => `<div class="srcbox">` +
        `<div class="srcbox-head">${kindPill(domainKind(s.domain), true)}${escapeHtml(tr("srcLabel", { domain: s.domain || "" }))}</div>` +
        (s.quote ? `<div class="srcbox-quote">«${escapeHtml(s.quote)}»</div>` : "") +
        `<a class="srcbox-open" href="${safeUrl(s.url)}" target="_blank" rel="noopener">${tr("srcOpen")}</a>` +
        `</div>`).join("");
    } else {
      const links = votes.slice(0, 3).map((s) =>
        `<a href="${safeUrl(s.url)}" target="_blank" rel="noopener" title="${escapeHtml(s.quote || "")}">${kindPill(domainKind(s.domain))}${escapeHtml(s.domain)}</a>`).join("");
      const more = votes.length > 3
        ? `<span class="more" data-h="${escapeHtml(c.hash)}">${tr("more", { n: votes.length - 3 })}</span>` : "";
      srcs = links ? `<div class="srcs">${links}${more}</div>` : "";
    }
  }
  // конфликт: наука первой, sonar с префиксом «по интернет-источникам»
  let whyOut = why;
  if (plausConflict && c.why && !why.includes("split")) {
    whyOut = `<div class="why"><span class="sonar-tag">${tr("sonarPref")}</span> ${escapeHtml(c.why)}</div>`;
  }
  const body = note
    ? `<div class="tquote">«${escapeHtml(note)}»</div>` +
      (c.category ? `<div class="tcat">${escapeHtml(tr("catLabel"))}: ${escapeHtml(c.category)}</div>` : "")
    : `<div class="claim ${long && !expanded ? "clamp" : ""}">${escapeHtml(c.claim)}</div>` +
      (plausConflict ? `${plaus}${whyOut}${srcs}` : `${whyOut}${plaus}${srcs}`);
  return `<div class="card ${long ? "expandable" : ""}${expanded ? " expanded" : ""}" data-h="${escapeHtml(c.hash)}" data-i="${i}" role="article"${note ? ` title="${escapeHtml(tr("uncheckedHint"))}"` : ""}
    aria-label="${L.ariaClaim}, ${label}${v ? ", " + L.ariaConfidence + " " + confLabel((c.result && c.result.confidence) || "") : ""}, ${fmtTS(c.t_start)}">
    <div class="statebg" style="--rail:${v ? VERDICT_COLOR[v] : "#9aa0a6"}">
      <div class="row1">
        <span class="ts" role="button" tabindex="0" data-t="${Math.floor(c.t_start)}" title="${tr("jumpTitle", { t: fmtTS(c.t_start) })}">${fmtTS(c.t_start)}</span>
        <span class="badge ${cls}">${label}</span>${conf}
      </div>
      ${body}
    </div>
  </div>`;
}

function markNewCards() {
  // анимация прилёта только у карточек, которых ещё не видели (по hash);
  // data-i указывает на claim независимо от порядка в DOM (режим «Текст»)
  panel.feed.querySelectorAll(".card").forEach((el) => {
    const c = state.claims[parseInt(el.dataset.i, 10)];
    if (c && !state.seen.has(c.hash)) { state.seen.add(c.hash); el.classList.add("new"); }
  });
}

function bindFeedHandlers() {
  // общие обработчики после любой перерисовки ленты: карточки, таймкоды, «··· ещё N»
  panel.feed.querySelectorAll(".card").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest("a, .ts")) return;  // ссылки и таймкод клика не раскрывают
      const h = el.dataset.h;
      if (state.expanded.has(h)) state.expanded.delete(h); else state.expanded.add(h);
      renderCurrent({ claims: state.claims });
    });
  });
  // таймкод (фикс 3): перематываем плеер на месте, без href и новой вкладки
  panel.feed.querySelectorAll(".ts").forEach((el) => {
    const t = parseFloat(el.dataset.t) || 0;
    el.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); seekTo(t); });
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); seekTo(t); }
    });
  });
  // «··· ещё N фрагментов» (фича A): раскрыть свёрнутые группы, повторно не сворачиваем
  panel.feed.querySelectorAll(".tmore").forEach((el) => {
    const open = () => {
      el.dataset.b.split(",").forEach((b) => state.unfolded.add(parseInt(b, 10)));
      renderCurrent({ claims: state.claims });
    };
    el.addEventListener("click", open);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
    });
  });
}

function syncFeedTabs() {
  // «Текст / Факты» (фича A): виден только при живом транскрипте в state
  if (!panel || !panel.feedtabs) return;
  const has = !!(state.transcript && state.transcript.cues && state.transcript.cues.length);
  panel.feedtabs.classList.toggle("hidden", !has);
  panel.feedtabs.querySelectorAll(".ftab").forEach((b) => {
    const on = b.dataset.m === state.feedMode;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", String(on));
  });
}

function syncDlButton() {
  // «Скачать .md» (фича B): появляется вместе с первыми карточками
  if (panel && panel.dl) panel.dl.classList.toggle("hidden", !(state.claims && state.claims.length));
}

// --- Выгрузка протокола в Markdown (фича B) ---

function downloadMarkdown() {
  if (!state.claims || !state.claims.length) return;
  const vid = state.videoId || getVideoId() || "video";
  const blob = new Blob([buildMarkdown()], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `factcheck-${vid}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

function buildMarkdown() {
  const L = I18N[uiLang()];
  const one = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const cap = (s) => s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
  const sum = lastSummary || {};
  const counts = sum.counts || {};
  const video = getVideoEl();
  const durSec = sum.duration || (state.transcript && state.transcript.duration)
    || (video && isFinite(video.duration) ? video.duration : 0);
  const total = sum.claims_total || state.claims.length;
  const checked = sum.checked != null ? sum.checked
    : state.claims.filter((c) => c.verdict).length;
  const unchecked = counts["не проверено"] != null ? counts["не проверено"]
    : Math.max(0, total - checked);
  const title = one((state.transcript && state.transcript.title)
    || document.title.replace(/\s*-\s*YouTube\s*$/, ""));
  const icon = (v) => v === "правда" ? "✅" : v === "ложно" ? "❌" : v === "странно" ? "⚠" : "○";
  const out = [
    `# ${tr("headTitle")}: ${title}`,
    `_${Math.round(durSec / 60)} ${tr("mdMin")} · ${tr("countsTitle", { checked, total })}_`,
    "",
    `## ${tr("mdSummary")}`,
    `- ✅ ${cap(L.vTrue)}: ${counts["правда"] || 0}`,
    `- ❌ ${cap(L.vFalse)}: ${counts["ложно"] || 0}`,
    `- ⚠ ${cap(L.vStrange)}: ${counts["странно"] || 0}`,
    `- ○ ${cap(L.vNone)}: ${unchecked}`,
    "",
    `## ${tr("mdClaims")}`,
  ];
  for (const c of state.claims.slice().sort((a, b) => (a.t_start || 0) - (b.t_start || 0))) {
    out.push("", `### [${fmtTS(c.t_start)}] ${icon(c.verdict)} ${cap(verdictLabel(c.verdict || null))}: ${one(c.claim)}`);
    // у проверенных — обоснование, у непроверенных — дословная цитата (фича C);
    // при конфликте с наукой (включая серверный science_flip) — префикс, как в карточке
    const plMD = c.result && c.result.plausibility;
    const flipMD = (c.result && c.result.science_flip) || "";
    const directMD = !plMD || plMD.relevance === undefined || plMD.relevance === "directly_on_topic";
    const conflictMD = !!(c.verdict && plMD && plMD.why && directMD &&
      (flipMD ||
       (plMD.relation === "refutes" && c.verdict === "правда") ||
       (plMD.relation === "supports" && c.verdict === "ложно")));
    let note = one(c.why) || (!c.verdict && c.quote ? `«${one(c.quote)}»` : "");
    if (note && conflictMD) note = `${tr("sonarPref")} ${note}`;
    if (note) out.push("", `> ${note}`);
    const pl = plMD;
    if (pl && pl.why && directMD &&
        (pl.relation === "refutes" ||
         (pl.relation === "supports" && (c.verdict === "ложно" || flipMD === "supports")))) {
      out.push("", `> ${tr(pl.relation === "refutes" ? "plausHead" : "plausHeadSup")} ${one(pl.why)} ` +
        `([${one((pl.source || {}).title || "source")}](${one((pl.source || {}).url || "")}))`);
    }
    const votes = (c.result && c.result.votes) || [];
    if (votes.length) {
      out.push("", `${tr("mdSources")}:`);
      for (const s of votes) {
        const kind = domainKind(s.domain);
        const mark = kind === "sci" ? ` (${tr("kindSci")})` : kind === "org" ? ` (${tr("kindOrg")})` : "";
        out.push(`- [${one(s.domain || s.url)}](${one(s.url)})${mark} — «${one(s.quote)}»`);
      }
    }
    out.push("", "---");
  }
  return out.join("\n") + "\n";
}

function renderTimeline(claims, duration) {
  // карта вердиктов поверх прогресс-бара YouTube: % позиции = % длительности;
  // перекрытия — «худший» вердикт рисуется последним (сверху). Порядок рисования: правда → странно → ложно.
  const bar = document.querySelector(".ytp-progress-bar");
  if (!bar || !duration) return;
  let host = bar.querySelector(".vfc-segments");
  if (!host) {
    host = document.createElement("div");
    host.className = "vfc-segments";
    bar.appendChild(host);
  }
  const order = { "правда": 0, "странно": 1, "ложно": 2 };
  const colored = claims.filter((c) => c.verdict && order[c.verdict] !== undefined)
    .sort((a, b) => (order[a.verdict] || 0) - (order[b.verdict] || 0));
  const TL = { "правда": "#2f9e4f", "ложно": "#e5484d", "странно": "#d9b02f" };
  host.innerHTML = colored.map((c) => {
    const left = (c.t_start / duration) * 100;
    const w = Math.max(((c.t_end || c.t_start + 10) - c.t_start) / duration * 100, 0.4);
    return `<i style="left:${left}%;width:${w}%;background:${TL[c.verdict]}" ` +
           `title="${fmtTS(c.t_start)} · ${verdictLabel(c.verdict)} · ${escapeHtml(String(c.claim).slice(0, 80))}"></i>`;
  }).join("");
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

// --- Кнопка запуска в ряду действий под видео (паттерн conspect) ---
// Живёт в DOM страницы, не в shadow-панели: стили — отдельный <style> в head,
// классы изолированы префиксом vfc-action-. Якорь как у conspect: сиблинг
// #subscribe-button внутри стабильного #owner — та же строка, где «Подписаться»
// и лайк/поделиться; сам #top-level-buttons-computed YouTube перерисовывает и
// подменяет скелетоном, #owner стабилен. Вид — пилюля как соседние action-кнопки
// (как «Скачать» у расширений): нейтральный фон уровня «Подписаться» (на тёмной
// теме #272727 + рамка #3d3d3d, hover #3f3f3f), радиус 18, иконка-щит с галочкой.
const ACTION_HOST_ID = "vfc-action-host";
const ACTION_BTN_ID = "vfc-action-btn";
const ACTION_ICON =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"' +
  ' stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<rect x="4" y="6.4" width="15.7" height="11.2" rx="3"/>' +
  '<path d="M8.6 12 L10.9 14.3 L15.7 8.6"/></svg>';
// галочка в круге — состояние «видео проверено» на кнопке под видео
const ACTION_DONE_ICON =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"' +
  ' stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<circle cx="12" cy="12" r="9"/><path d="M8.3 12.4 L10.8 14.9 L15.8 9"/></svg>';
const ACTION_CSS = `
  #vfc-action-host { display: inline-flex; align-items: center; margin-left: 10px; }
  .vfc-action-btn {
    display: inline-flex; align-items: center; gap: 8px;
    box-sizing: border-box; height: 36px; padding: 0 14px; border: none; border-radius: 18px;
    background: rgba(0, 0, 0, .05); color: #0f0f0f;
    font: 500 14px/1 Roboto, "Segoe UI", system-ui, sans-serif;
    letter-spacing: .01em; cursor: pointer; transition: background-color .12s ease;
  }
  .vfc-action-btn:hover { background: rgba(0, 0, 0, .1); }
  .vfc-action-btn:focus-visible { outline: 2px solid #3ea6ff; outline-offset: 2px; }
  .vfc-action-text { white-space: nowrap; }
  .vfc-action-icon { display: inline-flex; flex: none; }
  .vfc-action-icon svg { display: block; }
  .vfc-action-icon-done svg { display: block; color: #2f9e4f; }
  .vfc-action-spinner {
    display: none; flex: none; width: 16px; height: 16px; border-radius: 50%;
    border: 2px solid rgba(0, 0, 0, .15); border-top-color: #606060;
    animation: vfc-action-rot .9s linear infinite;
  }
  .vfc-action-count { display: none; flex: none; font-variant-numeric: tabular-nums; }
  .vfc-action-btn.vfc-running .vfc-action-icon { display: none; }
  .vfc-action-btn.vfc-running.vfc-has-count .vfc-action-count { display: inline; }
  .vfc-action-btn.vfc-running:not(.vfc-has-count) .vfc-action-spinner { display: inline-block; }
  /* проверено: галочка вместо знака запуска — клик открывает результат, не перезапускает */
  .vfc-action-btn .vfc-action-icon-done { display: none; }
  .vfc-action-btn.vfc-done .vfc-action-icon { display: none; }
  .vfc-action-btn.vfc-done .vfc-action-icon-done { display: inline-flex; }
  /* тёмная тема: непрозрачный фон как у «Подписаться», с рамкой — rgba(.1) на
     тёмном почти не виден (фикс 1). YouTube ставит атрибут dark и на ytd-app,
     и на <html> — покрываем оба, иначе кнопка остаётся светлой и пропадает */
  ytd-app[dark] .vfc-action-btn, html[dark] .vfc-action-btn {
    background: #272727; color: #f1f1f1; border: 1px solid #3d3d3d;
  }
  ytd-app[dark] .vfc-action-btn:hover, html[dark] .vfc-action-btn:hover { background: #3f3f3f; }
  ytd-app[dark] .vfc-action-spinner, html[dark] .vfc-action-spinner {
    border-color: rgba(255, 255, 255, .2); border-top-color: #aaa;
  }
  @keyframes vfc-action-rot { to { transform: rotate(360deg); } }
  /* подсказка первого запуска (решение №5): однократная пульсация кнопки «Факт-чек»
     на первом /watch после установки; первый клик гасит навсегда (vfc_hint_seen) */
  .vfc-action-btn.vfc-hint { animation: vfc-hint-pulse 1.6s ease-out infinite; }
  @keyframes vfc-hint-pulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(62, 166, 255, .5); }
    50% { box-shadow: 0 0 0 9px rgba(62, 166, 255, 0); }
  }
  @media (prefers-reduced-motion: reduce) {
    .vfc-action-spinner { animation-duration: 2.4s; }
    .vfc-action-btn.vfc-hint { animation: none; }
  }
`;

// счётчик вердиктов идущего прогона для кнопки: {checked, total} из summary
let runProgress = null;

function ensureActionStyles() {
  if (document.getElementById("vfc-action-style")) return;
  const st = document.createElement("style");
  st.id = "vfc-action-style";
  st.textContent = ACTION_CSS;
  (document.head || document.documentElement).appendChild(st);
}

// подсказка «где вход» при первом заходе на /watch после установки (решение №5):
// кнопка пульсирует, пока юзер не кликнул по ней; флаг vfc_hint_seen в
// chrome.storage.local гасит пульсацию навсегда, без модалок
let hintDismissed = null;  // null — ещё не читали из storage; true/false — итог
async function syncHintPulse(btn) {
  if (hintDismissed === null) {
    try { const st = await chrome.storage.local.get("vfc_hint_seen"); hintDismissed = !!st.vfc_hint_seen; }
    catch { hintDismissed = true; }
  }
  if (!hintDismissed && btn && btn.isConnected) btn.classList.add("vfc-hint");
}
function dismissHint() {
  hintDismissed = true;
  const btn = document.getElementById(ACTION_BTN_ID);
  if (btn) btn.classList.remove("vfc-hint");
  try { chrome.storage.local.set({ vfc_hint_seen: true }); } catch {}
}

function actionAnchor() {
  // #owner живёт в метаданных ytd-watch-metadata и не встречается в скелетоне
  const owner = document.querySelector("#owner");
  if (!owner) return null;
  return owner.querySelector("#subscribe-button")
      || owner.querySelector("ytd-subscribe-button-renderer");
}

function injectActionButton() {
  const existing = document.getElementById(ACTION_HOST_ID);
  if (!getVideoId()) {  // кнопка живёт только на страницах видео
    if (existing) existing.remove();
    return;
  }
  // На месте, внутри #owner и видна — ок. offsetParent===null ловит и hidden-предка
  // (скелетон), и display:none — в обоих случаях перепривязываем (приём conspect).
  if (existing && existing.closest("#owner") && existing.offsetParent !== null) {
    syncActionButton();
    syncActionVisibility(existing);
    return;
  }
  if (existing) existing.remove();
  const sub = actionAnchor();
  if (!sub || !sub.parentNode) return;  // #owner ещё не готов — интервал повторит
  ensureActionStyles();
  const host = document.createElement("div");
  host.id = ACTION_HOST_ID;
  host.innerHTML =
    `<button class="vfc-action-btn" id="${ACTION_BTN_ID}" type="button"` +
    ` title="${tr("btnRun")}" aria-label="${tr("btnRun")}">` +
    `<span class="vfc-action-icon">${ACTION_ICON}</span>` +
    `<span class="vfc-action-icon vfc-action-icon-done">${ACTION_DONE_ICON}</span>` +
    `<span class="vfc-action-spinner" aria-hidden="true"></span>` +
    `<span class="vfc-action-count" aria-hidden="true"></span>` +
    `<span class="vfc-action-text">${tr("headTitle")}</span>` +
    `</button>`;
  host.querySelector("button").addEventListener("click", onActionClick);
  sub.parentNode.insertBefore(host, sub.nextSibling);
  syncHintPulse(host.querySelector("button"));  // первый запуск: пульсация до первого клика
  syncActionButton();
}

async function onActionClick() {
  // иконка тулбара открывает панель на любой странице youtube: на /shorts и вне
  // видео startCheck честно откажется (Сл-9), на watch — запустит проверку
  dismissHint();  // первый клик по кнопке гасит подсказку навсегда (решение №5)
  ensurePanel(true);
  if (!panel) return;
  // панель скрыта или свёрнута в кружок — сначала показываем целиком
  if (panelMode !== "full") setPanelMode("full");
  // история/прогон могли ещё не дочитаться из storage — guard решает по факту (Сл-11)
  if (bootPromise) { try { await bootPromise; } catch { /* восстановление упало — ниже стартует новый прогон */ } }
  if (panel.run.disabled) { syncActionButton(); return; }  // прогон уже идёт
  if (state.done || state.claims.length) return;  // результат есть — просто открываем
  startCheck();
}

function syncRunRing() {
  // ободок кнопки в шапке: конус i/N, когда счётчик есть; иначе пульс
  if (!panel || !panel.run) return;
  const busy = panel.run.disabled;
  const has = busy && runProgress && runProgress.total > 0 && runProgress.checked > 0;
  panel.run.classList.toggle("ringed", has);
  panel.run.classList.toggle("pulse", busy && !has);
  if (has) panel.run.style.setProperty("--p", ((runProgress.checked / runProgress.total) * 100).toFixed(1));
}

function syncActionButton() {
  syncRunRing();  // ободок в шапке панели живёт теми же событиями, что и кнопка под видео
  syncMiniBusy(); // и пульс свёрнутого кружка — тоже
  const btn = document.getElementById(ACTION_BTN_ID);
  if (!btn) return;
  const busy = !!(panel && panel.run && panel.run.disabled);
  const done = !!(panel && state.done && !busy);
  btn.classList.toggle("vfc-running", busy);
  btn.classList.toggle("vfc-done", done);
  // во время прогона: счётчик вердиктов, если данные уже есть, иначе спиннер
  const hasCount = busy && runProgress && runProgress.checked > 0;
  btn.classList.toggle("vfc-has-count", hasCount);
  if (hasCount) btn.querySelector(".vfc-action-count").textContent =
    `${runProgress.checked}/${runProgress.total}`;
  btn.title = busy ? tr("btnChecking") : done ? tr("openResult") : tr("btnRun");
  btn.setAttribute("aria-label", btn.title);
}

// YouTube при скролле в ряде режимов делает метаданные sticky/fixed — кнопка-сиблинг
// «Подписаться» уезжала бы поверх контента. Прячем, пока предок sticky/fixed (из conspect).
function syncActionVisibility(host) {
  let stuck = false;
  for (let el = host; el && el !== document.documentElement; el = el.parentElement) {
    const pos = getComputedStyle(el).position;
    if (pos === "sticky" || pos === "fixed") { stuck = true; break; }
  }
  host.style.visibility = stuck ? "hidden" : "";
}
let actionVisRaf = 0;
function scheduleActionVisibility() {
  if (actionVisRaf) return;
  actionVisRaf = requestAnimationFrame(() => {
    actionVisRaf = 0;
    const host = document.getElementById(ACTION_HOST_ID);
    if (host) syncActionVisibility(host);
  });
}
window.addEventListener("scroll", scheduleActionVisibility, { passive: true });

// YouTube — SPA: перезаводим панель при навигации; на не-страницах видео панели нет
let lastUrl = location.href;
setInterval(() => {
  if (location.href !== lastUrl) {
    lastUrl = location.href;
    navEpoch++;  // асинхронные цепочки старого видео обязаны замолчать (ревью P1-1)
    stopPolling();
    state = freshState(getVideoId());
    runProgress = null;
    panel = null;
    panelMode = "hidden";  // на новом видео панели нет — только кнопка под видео
    document.querySelectorAll(".vfc-segments").forEach((e) => e.remove());  // карта вердиктов живёт в плеере — стираем (P1-2)
    ensurePanel();
  } else if (getVideoId() && !document.getElementById("vfc-host")) {
    panel = null;
    panelMode = "hidden";  // YouTube стёр панель: после пересоздания она скрыта (фикс рассинхрона)
    stopPolling();         // старый poll-интервал не должен утекать — resume заведёт свой
    ensurePanel();
  }
  injectActionButton();  // YouTube перерисовывает ряд действий — возвращаем кнопку
}, 1500);

ensurePanel();
injectActionButton();

// клик по иконке расширения в тулбаре Chrome (background.js) — тот же вход,
// что и кнопка под видео: открыть/развернуть панель, запустить, если не проверялось
chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "vfc-open-panel") onActionClick();
});
