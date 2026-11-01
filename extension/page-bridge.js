// video-factcheck, MAIN world: мост к данным плеера YouTube.
// Контент-скрипт в изолированном мире не видит window.ytInitialPlayerResponse,
// поэтому этот скрипт (world: MAIN) отдаёт субтитровые треки и метаданные
// через CustomEvent. Транскрипт качается потом самим контент-скриптом —
// same-origin, с куками и IP пользователя: датацентровые 429 не касаются.
"use strict";
(function () {
  function emit() {
    try {
      var pr = window.ytInitialPlayerResponse;
      if (!pr) return;
      var detail = {
        captions: (pr.captions && pr.captions.playerCaptionsTracklistRenderer
                   && pr.captions.playerCaptionsTracklistRenderer.captionTracks) || [],
        videoDetails: pr.videoDetails || null,
      };
      window.dispatchEvent(new CustomEvent("vfc-player-data", { detail: detail }));
    } catch (e) { /* страница без плеера — молчим */ }
  }
  emit();
  window.addEventListener("vfc-request-data", emit);
})();
