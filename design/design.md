---
product: video-factcheck, a YouTube fact-check extension
surface: side panel on the video page + a verdict map on the timeline
mode: operate (per the impeccable classification: a working screen; the ambition is precision and restraint)
color_strategy: restrained, a neutral dark base plus semantic verdict colors
scene: "A viewer watches a long lecture or interview in a dark room in the evening. The panel is a working tool next to the video: it helps parse the speech instead of competing with the player for attention."
tokens: tokens.json
method: the "registries + specifications" structure of an agent-ready design system (designpub, E. Hörner); the Operate/Restrained principles and the calibration self-check come from impeccable (pbakaus/impeccable v4.8)
---

# design.md: shared rules and agreements

## What this world is

A dark, YouTube-native working panel. The product lives on top of someone else's interface (YouTube), so the strategy is "our tool in a foreign house": typography and background close to YouTube dark, but our own card and badge structure that YouTube does not offer. Nothing loud: the only source of color is verdict semantics.

Calibration self-check (impeccable): the typical AI look of "near black plus one neon" would not survive here. Three semantic colors work as a status system, not decoration; the neutral base is warm (#16181d), not bluish black.

## Color

Rules on top of tokens.json:

1. **Color in this product does work, it does not decorate.** Green, red and yellow exist only in the verdict sense (true / false / strange) and nowhere else. Exceptions: the red of the action button (the YouTube "subscribe" convention), the blue of the sign #2F6FED (brand, outside verdict semantics), the green "video checked" check mark on the button under the video (completion, the same "green = all good" system), the amber "run in progress" pulse on the collapsed dot: that is a process status, not a verdict, the `status.busy` token, the single icon value #ffd66e; the strange yellow (#ffd666) is not reused for it.
2. **Verdict colors come in tint+fg pairs** (a light fill plus colored text), never a bright solid fill. The badge pill takes bg from `verdict.*.bg` and text from `verdict.*.fg`.
3. **Contrast:** text on its own backgrounds at 4.5:1 or better (AA). Muted text (#9aa0a6) on the panel is for service lines only, not for substantive claims.
4. **Links** use YouTube blue #3ea6ff: ours in style, familiar from the platform. The brand sign #2F6FED is not #3ea6ff: the sign is brand, links are platform.

## The sign (logo, v0.6)

The "frame with a check mark": a rounded video frame plus a check mark, blue #2F6FED (variant D of the four concepts, picked 2026-10-29). Reasoning from genre research: fact-checking organizations do not use play shields or magnifiers; the red triangle is taken by the YouTube trademark; green and yellow are reserved for verdicts, so the sign stays neutral. Placements: extension icons 16/32/48/128 (a bolder variant for the small grid), a monochrome outline on the button under the video, a colored one on the collapsed dot. Sources in design/logo/src/*.svg, preview in design/logo/preview.html.

## The "unchecked" state

The "unchecked" class is visually the fourth one and muted (verdict.unchecked). This is a principle, not a styling choice: unchecked must look neither confirmed nor refuted (the implied truth effect from product research). Design must keep this difference readable at first glance, in the panel, on the timeline and in the counters.

## Hierarchy in a verdict card

Order of importance: timecode, verdict badge, claim, explanation, sources. The user scans the feed diagonally looking for "red"; anything that hinders this scan (frames, icons, large quotes in the card body) is an error.

## One shared timecode column (canon since 2026-10-29, v0.6.6)

Transcript lines and fact cards stand on the same vertical: the timecode in a 46px right-aligned column (a wall of digits), the left edge at 24px (12px of the card plus the 3+9px background), line text and the card badge start on the same 77px vertical. The timecode is clickable on every transcript line, as in the native transcript. The timecode width does not float: a variable width ("0:12" vs "40:07") and the indents of continuation lines broke column scanning, the jumps were removed by fixing the column.

## Source weight pills (canon since 2026-10-29, v0.6.8)

Sources differ in strength, and it shows before the click: "science" (peer-reviewed journals, PMC, preprints, .edu) uses the blue pair of the science block (#17233a/#7ab3ff), "official" (government domains, WHO/UN) uses the green v-true pair (#1d3a24/#7bd88f). The pill is 9px uppercase in front of the domain; in the science block it carries the full label "scientific article". In the source list, science and official sources come first. The pill marks the source class, not a verdict: it does not compete with the badges in state colors.

## Roundness (canon since 2026-10-28, review reviews/2026-10-28-screens.md)

The principle: **objects are soft, links are hard**. Badges, counters and the button are pills (radius = half the height); the panel is 12px on all sides (a floating card); card state backgrounds (hover/current/new) are insets of radius 8 with 3px side margins. The links, 1px card dividers, the monospace timecodes, the 12px grid, stay straight: the feed reads as a column, not as a set of candies. The 50% dot (the collapsed panel with its ×) is the limiting case of a pill: it is an object, not a container, so the "radius over 16" ban does not apply to it, the ban targets containers. Bans: nested radii, shadows on cards (a shadow belongs to the panel only). Operate strictness is held by the tint pairs, the single weight of 700 and the dense scale: we round the shape, we do not touch the typography.

## Panel composition

- Width 340px, a floating card (right 16px, radius 12px on all sides, the floating-dot panel pattern). By default the panel is HIDDEN: the entry is the button under the video or the toolbar icon; auto-open happens only when resuming a live run. The panel does not cover the video: below about 1100px of window width it narrows to 300px (the tongue is iteration 2).
- Modes: hidden / mini (a 52px dot, the same panel morphed, sign plus run pulse plus × on hover) / full. A click on the dot expands, × hides it completely.
- Vertical rhythm: header, status line, counters, feed. The feed is the only scrollable area.
- The current card (synced with playback) is highlighted with the `panel_highlight` background without changing sizes: the highlight must not move the feed.

## Motion

The duration scale: **120 / 160 / 180 / 280 ms**. 120 for all hovers and highlights (one pace), 160 for the panel slide-in, 180 for verdict arrival, 280 for the morph into the dot (width/max-height/border-radius, easing cubic-bezier(.2,.8,.3,1)): it is a transition of shape, not of attention. Intermediate values (popover 140, × on the dot 150, hide fade 130) live next to the scale, do not spawn new steps. Pulses are the only infinite animations and live only during a run: the spinner 900ms, the button ring and skeletons 1200ms, the dot pulse 1800ms. Verdicts arrive during viewing, so the animation must be noticeable in the periphery without pulling attention from the speech (see verdict-stream.pattern.md).

## Text tone

Short wording without bureaucratese and without accusatory pathos: "strange", not "misleading"; "unchecked", not "unverifiable". The explanation is one line, in the user's language. This is a product rule from research, design supports it (clamping to 2 lines with an expand).

## Accessibility

- Every interactive element works from the keyboard: the panel via tabindex, cards via focus, timecodes as links.
- Timecode hit area at least 32px tall (the link is narrow today, to be fixed).
- The verdict color is doubled by text in the badge (not color alone).
- prefers-reduced-motion: all animations turn off or slow down, the panel morph is instant.

## World boundaries

The panel renders in a shadow DOM: YouTube styles do not leak in either way. Everything that lives on the page itself (timeline segments) must survive the YouTube player redraw (the SponsorBlock approach: segments are an overlay over the progress bar, not part of it). Pulling foreign fonts and images into the panel is forbidden: system stack and vectors only, the extension stays minimal in weight.
