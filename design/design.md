---
product: video-factcheck, a fact-check extension for YouTube
surface: side panel on the video page + a verdict map on the timeline
mode: "operate (per the impeccable classification: a working screen; the ambition = precision and restraint)"
color_strategy: restrained, a neutral dark base + semantic verdict colors
scene: "In the evening a viewer watches a long lecture or interview in a dark room. The panel is a working tool next to the video: it helps the viewer parse the speech instead of competing with the player for attention."
tokens: tokens.json
method: 'the "registers + specifications" structure per agent-ready design system (designpub, E. Hörner); the Operate/Restrained principles and the calibration self-check per impeccable (pbakaus/impeccable v4.8)'
---

# design.md: general rules and conventions

## What this world is

A dark, YouTube-native working panel. The product lives on top of someone else's interface (YouTube), so the strategy is "our own tool in a borrowed house": familiar typography and a background close to YouTube's dark theme, plus a card and badge structure of our own that YouTube does not offer. Nothing loud: the only source of color is verdict semantics.

Calibration self-check (impeccable): the typical AI look of "near-black + one neon" would not survive here. Our three semantic colors work as a status system, not decoration; the neutral base is warm (#16181d), not bluish black.

## Color

Rules on top of tokens.json:

1. **Color in this product does work, it does not decorate.** Green, red, and yellow exist only in the verdict sense (true / false / strange) and nowhere else. Exceptions: the red action button (the YouTube "subscribe" convention), the sign blue #2F6FED (brand, outside verdict semantics), the green "video checked" checkmark on the button under the video (completion, the same "green = all good" system), and the amber "run in progress" pulse on the collapsed dot. The pulse is a process status, not a verdict: the token is `status.busy`, the icon's single value is #ffd66e; the strange yellow (#ffd666) is not reused for it.
2. **Verdict colors are tint+fg pairs** (a light fill + colored text), never a solid bright fill. The badge pill takes its bg from `verdict.*.bg` and its text from `verdict.*.fg`.
3. **Contrast:** text on its own surfaces is at least 4.5:1 (AA). Muted text (#9aa0a6) on the panel is for service text only, not for substantive statements.
4. **Links** use YouTube blue #3ea6ff: our own in style, familiar on the platform. The brand sign #2F6FED is not #3ea6ff: the sign is the brand, links belong to the platform.

## The sign (logo, v0.6)

A "frame with a checkmark": a rounded video-frame outline plus a checkmark, blue #2F6FED (variant D of the four concepts, chosen by genre research). The genre research rationale: fact-checking organizations have no play-shields or magnifiers; the red triangle is taken by the YouTube trademark; green and yellow are reserved for verdicts, so the sign is neutral. Placements: extension icons 16/32/48/128 (a bold variant for the small grid), a monochrome outline on the button under the video, colored on the collapsed dot. Sources are design/logo/src/*.svg, the preview is design/logo/preview.html.

## The "unchecked" state

The "not checked" class is visually a fourth, muted one (verdict.unchecked). This is a principle, not a styling choice: unchecked must not look either confirmed or refuted (the implied truth effect from product research). Design must keep this difference readable at a glance: in the panel, on the timeline, and in the counters.

## Hierarchy inside a verdict card

Order of importance: timestamp → verdict badge → claim → explanation → sources. The user scans the feed diagonally for "red"; anything that gets in the way of that scan (borders, icons, large quotes inside the card body) is an error.

## One shared timestamp column (canon since 2026-10-29, v0.6.6)

Transcript lines and fact cards sit on one vertical: the timestamp in a 46px right-aligned column (a wall of digits), the left edge at 24px (12px of card + 3+9px of background), and the line text and the card badges start on the same 77px vertical. The timestamp is clickable on every transcript line, as in the native transcript. The timestamp width does not drift: variable width ("0:12" to "40:07") and continuation-line indents broke column scanning, so the jumps were removed by fixing the column.

## Source weight pills (canon since 2026-10-29, v0.6.8)

Sources differ in strength, and that is visible before the click: "science" (peer-reviewed journals, PMC, preprints, .edu) gets the blue pair of the science block (#17233a/#7ab3ff), "official" (government domains, WHO/UN) gets the v-true green pair (#1d3a24/#7bd88f). The pill is 9px uppercase before the domain; in the science block the full label reads "scientific article". In the source list, science and official come first. The pill marks the source class, not a verdict: it does not compete with the badges through state colors.

## Roundness (canon since 2026-10-28)

The principle: **objects are soft, connections are hard.** Badges, counters, and the button are pills (radius = half the height); the panel is 12px on all sides (a floating card); card state backgrounds (hover/current/new) are radius-8 insets with 3px side margins. Connections, the 1px card dividers, mono timestamps, and the 12px grid, stay straight: the feed reads as a column, not a set of candies. The 50% dot (the collapsed panel with its ×) is the limiting case of a pill: it is an object, not a container, so the radius >16 ban does not apply to it; the ban targets containers. Bans: nested radii, shadows on cards (a shadow belongs to the panel alone). Operate strictness is held by the tint pairs, the single 700 weight, and the tight type scale: we round the shape and leave the typography alone.

## Panel composition

- Width 340px, a floating card (right 16px, radius 12px on all sides, the conspect pattern). By default the panel is HIDDEN; entry is through the button under the video or the toolbar icon, and auto-open happens only when a live run resumes. The panel never covers the video: if the window is narrower than ~1100px, the panel shrinks to 300px (the tongue is iteration 2).
- Modes: hidden / mini (a 52px dot, a morph of the same panel: sign + run pulse + × on hover) / full. A click on the dot expands it; × hides it completely.
- Vertical rhythm: header → status line → counters → feed. The feed is the only scrollable area.
- The current card (in sync with playback) is highlighted with the `panel_highlight` background without changing size: the highlight must not move the feed.

## Motion

Duration scale: **120 / 160 / 180 / 280 ms**. 120 for all hovers and highlights (one tempo), 160 for the panel slide-in, 180 for verdict arrival, 280 for the morph into the dot (width/max-height/border-radius, easing cubic-bezier(.2,.8,.3,1)): a transition of shape, not of attention. Intermediate values (popover 140, × on the dot 150, hide fade 130) live next to the scale; do not grow new steps. Pulses are the only infinite animations and live only during a run: the spinner 900ms, the button ring and skeletons 1200ms, the dot pulse 1800ms. Verdicts arrive during viewing: the animation must be noticeable in peripheral vision and must not pull attention from the speech (see verdict-stream.pattern.md).

## Text tone

Short wording with no officialese and no accusatory pathos: "unclear" rather than "misleading"; "not checked" rather than "unverifiable". The explanation is one line, in the user's language. This is a product rule from research; design supports it (clamping to 2 lines with an expand).

## Accessibility

- Every interactive element works from the keyboard: the panel via tabindex, cards take focus, timestamps are links.
- The timestamp hit area is at least 32px tall (today the link is narrow; to be fixed).
- The verdict color is doubled by text in the badge (not color alone).
- prefers-reduced-motion: all animations turn off or slow down; the panel morph is instant.

## World boundaries

The panel renders in a shadow DOM: YouTube styles do not reach it and vice versa. Everything that lives on the page itself (timeline segments) must survive YouTube player redraws (the SponsorBlock pattern: segments are an overlay over the progress bar, not part of it). The panel must not pull in third-party fonts or images: the system font stack and vectors only, so the extension stays lightweight.
