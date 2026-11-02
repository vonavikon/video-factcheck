// video-factcheck, MAIN world: bridge to YouTube player data.
// The content script in the isolated world cannot see window.ytInitialPlayerResponse,
// so this script (world: MAIN) hands out caption tracks and metadata
// via CustomEvent. The transcript is later downloaded by the content script itself,
// same-origin with the user's cookies and IP: datacenter 429s do not apply.
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
    } catch (e) { /* page without a player: stay silent */ }
  }
  emit();
  window.addEventListener("vfc-request-data", emit);
})();
