# TaskFactory design audit

Date: 20 November 2026. Scope: the form (`/`), the results (`/api/generate`), the
error pages (`render_message`), the landing page (`/about`, served from
`site/index.html`) and the shared shell in `src/taskfactory/web/theme.py`. The
sample report under `site/sample/` was not changed.

## What was looked at

* `theme.py` (`STYLESHEET`, `page_shell`), `render_page.py`, `results_page.py`,
  `results_summary.py`, `site/index.html`.
* Served pages from the WSGI app, plus the form and results rendered in a
  browser. The skill's `snapshot.mjs` could not run because Playwright is not
  installed; nothing was installed. Installed Chrome was used headless, and a
  true 360 px viewport was set through the DevTools protocol. All four pages
  reported `scrollWidth == innerWidth == 360`.

## Signs found

### Surfaces and colour

1. `theme.py` `:root` used a pure white/grey shadcn ramp with a near-black
   primary; it could belong to any product. (Template look.)
2. `theme.py` `.card`, `.stat`, `.site-header` put the same white surface, grey
   hairline and soft shadow on every block; no surface hierarchy.
3. `theme.py` carried four unrelated semantic hues (green, red, amber, near
   black) and no single accent.
4. `theme.py` `.badge`, `.checkbox` made every tag, count and option a 999 px
   pill. (Everything a pill.)
5. `theme.py` `.badge-success` and `results_page.py` `_chips()` tinted every
   pass/fail chip; `results_page.py` `.answer-box` added another green wash, so
   the chrome competed with the chart.
6. `results_summary.py` `_STYLE` used a second palette (`#f6f7f9`, `#1a5fb4`
   links), a 960 px column and 10 px radii; the error/summary pages read as a
   different product.

### Type

7. `theme.py` `.section-title` was uppercase, 12.8 px, 0.06 em tracking, 700.
8. `results_page.py` `.stat-label`, `.meta-label`, `.answer-label` repeated the
   uppercase tracked micro-label three more times.
9. `results_summary.py` `th` uppercased every table header.
10. 700 weights appeared in `theme.py` `.section-title`, `.stat`, and
    `results_page.py` `.stat-value`.
11. `theme.py` `.brand` used negative letter spacing on 16 px text.
12. `results_summary.py` printed yield as `0.5000` while `results_page.py`
    printed `50.0%`; one screen, two number formats.

### Icons and spacing

13. `theme.py` icons were 1.05 em, 1.35 rem in the brand and 0.95 em in
    `results_page.py` chips; three sizes.
14. `theme.py` used `1.1rem`, `0.35rem`, `0.45rem`, `0.65rem`, `0.9rem`,
    `0.15rem` and `0.55rem` in the form; off the 4 px rhythm.
15. `theme.py` `.stat` padding (`1rem 1.1rem`) did not match `.card`
    (`1.25rem`); `results_summary.py` used `0.6rem` table padding.

### Copy

16. `render_page.py` put a pill badge (`Free chart-question factory`) above the
    headline.
17. `render_page.py` said "about 15 tasks" twice, in the card description and
    in the hint under Question types.
18. `render_page.py` styled the cold-start note as an info alert box.
19. `results_summary.py` said "The images and the ZIP come next" although the
    page is a table-only summary.
20. `render_page.py` said "not from an AI guess" where the rest of the page
    says "no model"; one voice, two labels.

### Layout, details and motion

21. `render_page.py` `.stats` was three equal icon feature cards beside the form;
    `site/index.html` repeated the same three cards.
22. `results_page.py` `.stat-tiles` was four equal cards, one with a meter; the
    summary was template-shaped.
23. `results_page.py` `.task-title` made the machine task id the heading and put
    the human question below it.
24. `results_page.py` `.commit-details summary` used `display: inline-flex`,
    which removed the disclosure marker.
25. `results_page.py` `.task-card:hover` lifted cards 2 px and added a 24 px
    shadow; `theme.py` `.brand .icon` floated on a 6 s infinite loop.
26. `theme.py` animated `.hero, .card, .stat` together, so every card flew in.
27. `site/index.html` had no product visual in the hero: headline, paragraph and
    a card of feature bullets only.
28. `theme.py` `.btn:active` translated down 1 px instead of a small press
    scale.

### Contrast and accessibility

29. `theme.py` `--muted-foreground #737373` on `--muted #f5f5f5` was 4.35:1;
    `.badge-muted` and the hint in that surface failed 4.5:1.
30. `theme.py` `.badge-success` text was 4.28:1 at 12 px.
31. `theme.py` focus ring `#a3a3a3` on white was 2.52:1 (needs 3:1 for UI);
    the dark ring `#525252` on `#0a0a0a` was also short.
32. `theme.py` input border `#e5e5e5` on white was about 1.3:1; the control
    boundary was not perceivable.
33. `theme.py` `a { color: inherit }` made inline links (the source line on
    `/about`) look like body text until hover.
34. Form section labels were `<div class="section-title">`, not headings, so the
    card's h2 had no h3 level.
35. The error page used `.card-title` at 18 px for its `<h1>`.

### Checked and not found

No emoji, hue gradients, gradient text, coloured glows, glass cards, decorative
blobs, fake numbers, `<script>`, dead links or icon-only buttons. The sample
report's own page was not edited.

## Direction

* **Product.** TaskFactory generates synthetic chart questions with exact,
  machine-checkable answers for benchmark builders and evaluators.
* **Character.** Precise, calm, checkable.
* **World.** A calibration bench: warm paper, graphite ink, one instrument blue,
  ruler ticks and thin graticule lines.
* **Moments.** The generated chart itself, framed as a specimen on a clean white
  plate with its question and exact answer; on `/about`, one drawn chart
  specimen does the same job before a run exists.
* **Signature.** A small L-shaped registration mark before every section label,
  and tabular mono figures for every number.

The brief's direction held up in the audit. It was refined in two places: the
world is the sample report's paper-and-blue world, so the accent is the
instrument blue already in the product's charts (`#225f7d` light, `#7fc7dd`
dark), and the signature became the registration mark. Warm red (`#b42318`
light, `#f97066` dark) is reserved for failed checks. Everything else is the
one warm neutral ramp; the chart remains the one bright element on a results
screen.

## Passes applied

1. **Spacing.** Form fields on a 4 px rhythm (`0 0 20px`, 8 px label gap, 24 px
   section separators); card padding 20; result sections 40 apart; fixed 64 px
   header and 36 px nav targets.
2. **Colour.** One warm ramp (`#f7f5ef` page, `#fffdf8` card, `#14130f` dark
   page), one instrument blue for the primary action and passing checks, warm
   red for failures, amber only for warnings. No shadows on cards; hairlines
   and surface steps. Body contrast is 6.3:1 light and 7.4:1 dark.
3. **Icons.** Kept the existing Lucide-style set and 2 px stroke at one 16 px
   size (20 px brand mark). Removed decorative section-title and stat icons;
   only labels, buttons, alerts and status marks keep icons.
4. **Copy.** Removed the hero pill, the duplicate task count and the stale
   summary sentence; one sentence case voice; no exclamation marks or claims.
5. **Type.** System sans for the interface and system mono for figures/meta;
   weights 400/500 throughout, no 700; page title 32-44 px; no uppercase and no
   negative tracking below 16 px. All figures tabular.
6. **Layout.** Form two columns at 720; results summary is one band of four
   figures, task grid one column until 900 then two; `/about` is an asymmetric
   split with the chart specimen on the right. No horizontal scroll at 360.
7. **Details.** Radii 12 (card), 8 (control), 4 (tag/image); checks are one
   eight-pixel strip; counts are mono text, not pills; the full-commit
   disclosure has a visible marker; focus ring is 6.4:1.
8. **Visuals.** Added one hand-built SVG chart specimen to `/about` with real
   sample values, its question and its exact answer. No generated image was
   needed; no filler remains.
9. **Motion.** One 400 ms rise for the hero/page entry with a 60 ms stagger,
   140 ms colour transitions, a 0.98 press scale, all inside
   `prefers-reduced-motion: no-preference`; no loops, floats or hover lifts.

## Glitches fixed

* Form section headings were `<div>`s; now `<h3>` under the card's `<h2>`.
* The error page `<h1>` was 18 px; now a page-sized `.error-title`.
* Muted text on muted surfaces 4.35:1 and the success badge 4.28:1; now 5.8:1
  and 6.1:1 in light mode (dark muted 6.3:1).
* Focus ring 2.52:1 and input border about 1.3:1; now 6.42:1 and 3.64:1.
* The full-commit `<summary>` had no disclosure marker; restored with
  `display: list-item`.
* The summary fallback's stale "images and ZIP come next" line; corrected.
* Duplicate "about 15 tasks" sentence on the form; one source remains.
* Inline links were invisible until hover; paragraph/hint/note links are now
  accent and underlined.
* Yield printed two ways (`0.5000` and `50.0%`); both print `50.0%`.
* No dead link or icon-only button was found; every href resolves to `/`,
  `/sample/`, `/about` or the repository.
* The first visual check caught a broad `.specimen svg` rule sizing the caption
  check icon at page width; scoped to `.specimen-chart` before delivery.

## Visual check

The skill's snapshot script was attempted and failed with "Playwright is not
installed"; no package was installed. Chrome headless was used instead. The
screenshots live in
`C:\Users\KIIT\AppData\Local\Temp\opencode\taskfactory-design\`:
`form-light-2.png`, `form-dark.png`, `results-light-tall.png`,
`about-light-3.png`, `error-light.png`, and true-360 captures
`form-mobile-360.png`, `results-mobile-360.png`, `about-mobile-360.png`.
The 360 captures all reported `scrollWidth == 360`.
