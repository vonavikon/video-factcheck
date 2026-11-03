// video-factcheck, MAIN world: bridge to YouTube player data.
// The isolated-world content script cannot see window.ytInitialPlayerResponse,
// so this script (world: MAIN) emits caption tracks and metadata via
// CustomEvent. The content script later downloads the transcript itself:
// same-origin, with the user's cookies and IP, so datacenter 429s do not apply.
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
    } catch (e) { /* page without a player, stay silent */ }
  }
  emit();
  window.addEventListener("vfc-request-data", emit);
})();
