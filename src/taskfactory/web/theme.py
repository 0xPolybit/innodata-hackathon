# Design: unslop by Damir Sokolovsky (https://x.com/heydamir,
# https://heydamir.design/unslop), adapted for TaskFactory under CC BY 4.0.
# Icons: Lucide (https://lucide.dev), ISC License. The paths are inlined below.
"""The shared TaskFactory design system: one quiet measurement-bench stylesheet,
inline Lucide icons and one page shell.

The direction is a calibration bench: warm paper surfaces, graphite ink and one
instrument blue for the primary action and passing checks. Warm red is kept for
failures only. Every figure is tabular and set in the system mono. The signature
is the small L-shaped registration mark before each section label.

There is no build step, no font download and no script. The static landing page
in ``site/index.html`` carries an exact copy of :data:`STYLESHEET` between its
shared-stylesheet comments; keep the two in sync.

Icons: Lucide (https://lucide.dev), ISC License. The SVG paths are inlined so
the pages load no external resource.
"""

from __future__ import annotations

from html import escape

__all__ = ["ICONS", "STYLESHEET", "page_shell"]

REPO_URL = "https://github.com/0xPolybit/innodata-hackathon"

# One entry per icon this site uses. Every string is a complete 24x24 SVG that
# inherits its colour and sits in the surrounding text flow.
ICONS: dict[str, str] = {
    "beaker": (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">'
        '<path d="M4.5 3h15"/><path d="M6 3v16a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V3"/>'
        '<path d="M6 14h12"/></svg>'
    ),
    "sliders-horizontal": (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">'
        '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/>'
        '<line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/>'
        '<line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/>'
        '<line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/>'
        '<line x1="16" x2="16" y1="18" y2="22"/></svg>'
    ),
    "database": (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">'
        '<ellipse cx="12" cy="5" rx="9" ry="3"/>'
        '<path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/></svg>'
    ),
    "list-checks": (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">'
        '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/>'
        '<path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/></svg>'
    ),
    "gauge": (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">'
        '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/></svg>'
    ),
    "image": (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">'
        '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/>'
        '<circle cx="9" cy="9" r="2"/>'
        '<path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/></svg>'
    ),
    "play": (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">'
        '<polygon points="6 3 20 12 6 21 6 3"/></svg>'
    ),
    "file-text": (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">'
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/>'
        '<path d="M16 13H8"/><path d="M16 17H8"/></svg>'
    ),
    "github": (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">'
        '<path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5'
        '.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c'
        '-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05'
        '-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/>'
        '<path d="M9 18c-4.51 2-5-2-7-2"/></svg>'
    ),
    "info": (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">'
        '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/>'
        '<path d="M12 8h.01"/></svg>'
    ),
    "alert-triangle": (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">'
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 '
        '1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>'
    ),
    "check-circle": (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">'
        '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>'
    ),
    "x-circle": (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">'
        '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/>'
        '<path d="m9 9 6 6"/></svg>'
    ),
    "arrow-left": (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">'
        '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></svg>'
    ),
}

# Keep this under about 350 lines: one readable block, no build step. The
# palette is one warm-neutral ramp, one instrument blue and one failure red,
# expressed as CSS custom properties so a dark scheme only redefines tokens.
STYLESHEET = """
:root {
  color-scheme: light;
  --background: #f7f5ef;
  --foreground: #1c1b17;
  --card: #fffdf8;
  --card-foreground: #1c1b17;
  --primary: #225f7d;
  --primary-foreground: #fbfaf6;
  --secondary: #efece3;
  --secondary-foreground: #1c1b17;
  --muted: #efece3;
  --muted-foreground: #5f5a50;
  --accent: #ece7db;
  --accent-foreground: #1c1b17;
  --destructive: #b42318;
  --success: #225f7d;
  --warning: #8a5a12;
  --border: #e2ddd1;
  --input: #8c8475;
  --ring: #225f7d;
  --radius: 12px;
  --radius-control: 8px;
  --radius-tag: 4px;
  --shadow: 0 1px 2px rgb(28 27 23 / 0.05);
  --mono: ui-monospace, "Cascadia Mono", "SFMono-Regular", Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --background: #14130f;
    --foreground: #f2eee4;
    --card: #1b1a16;
    --card-foreground: #f2eee4;
    --primary: #7fc7dd;
    --primary-foreground: #0c1518;
    --secondary: #24221c;
    --secondary-foreground: #f2eee4;
    --muted: #24221c;
    --muted-foreground: #a9a396;
    --accent: #2a2720;
    --accent-foreground: #f2eee4;
    --destructive: #f97066;
    --success: #7fc7dd;
    --warning: #e8b96b;
    --border: #2e2b24;
    --input: #6d675b;
    --ring: #7fc7dd;
    --shadow: 0 1px 2px rgb(0 0 0 / 0.5);
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }
body {
  margin: 0; min-height: 100vh; display: flex; flex-direction: column;
  background: var(--background); color: var(--foreground);
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 15px; line-height: 1.55; font-variant-numeric: tabular-nums;
}
a { color: inherit; text-decoration: none; }
a:hover { text-decoration: underline; text-underline-offset: 3px; }
p a, .hint a, .note a { color: var(--primary); text-decoration: underline; text-underline-offset: 3px; }
.icon { width: 16px; height: 16px; flex: none; vertical-align: -0.12em; }
.container { width: 100%; max-width: 1080px; margin: 0 auto; padding-left: 16px; padding-right: 16px; }
main.container { flex: 1; padding-top: 32px; padding-bottom: 48px; }
.site-header { border-bottom: 1px solid var(--border); background: var(--background); }
.header-inner {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: 8px; min-height: 64px; padding-top: 8px; padding-bottom: 8px;
}
.brand { display: inline-flex; align-items: center; gap: 8px; font-size: 17px; font-weight: 500; letter-spacing: 0; }
.brand .icon { width: 20px; height: 20px; color: var(--primary); }
.nav { display: flex; flex-wrap: wrap; align-items: center; gap: 2px; }
.nav a {
  display: inline-flex; align-items: center; gap: 6px; min-height: 36px; padding: 0 12px;
  border-radius: var(--radius-control); color: var(--muted-foreground); font-size: 14px; font-weight: 500;
}
.nav a:hover { background: var(--accent); color: var(--foreground); text-decoration: none; }
.nav a[aria-current="page"] { background: var(--accent); color: var(--foreground); }
.hero { max-width: 44rem; padding: 24px 0 32px; }
.hero h1 {
  margin: 0; font-size: clamp(2rem, 1.4rem + 2.4vw, 2.75rem); line-height: 1.1;
  font-weight: 500; letter-spacing: -0.015em;
}
.hero p { max-width: 40rem; margin: 12px 0 0; color: var(--muted-foreground); font-size: 17px; }
.badge {
  display: inline-flex; align-items: center; gap: 6px; padding: 2px 8px;
  border: 1px solid var(--border); border-radius: var(--radius-tag);
  background: var(--secondary); color: var(--secondary-foreground);
  font-family: var(--mono); font-size: 12px; font-weight: 400; line-height: 1.5;
}
.badge-success {
  border-color: color-mix(in srgb, var(--success) 35%, var(--border));
  background: color-mix(in srgb, var(--success) 8%, var(--card)); color: var(--success);
}
.badge-destructive {
  border-color: color-mix(in srgb, var(--destructive) 35%, var(--border));
  background: color-mix(in srgb, var(--destructive) 8%, var(--card)); color: var(--destructive);
}
.badge-muted { background: var(--muted); color: var(--muted-foreground); }
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  height: 40px; padding: 0 16px; border: 1px solid transparent;
  border-radius: var(--radius-control); background: var(--secondary);
  color: var(--secondary-foreground); font: inherit; font-size: 14px;
  font-weight: 500; line-height: 1; cursor: pointer; text-decoration: none;
}
.btn:hover { background: color-mix(in srgb, var(--secondary) 88%, var(--foreground)); text-decoration: none; }
.btn-primary { background: var(--primary); color: var(--primary-foreground); }
.btn-primary:hover { background: color-mix(in srgb, var(--primary) 88%, var(--foreground)); }
.btn-outline { border-color: var(--input); background: var(--card); color: var(--foreground); }
.btn-outline:hover { background: var(--accent); }
.btn-ghost { background: transparent; color: var(--foreground); }
.btn-ghost:hover { background: var(--accent); }
.btn-lg { height: 44px; padding: 0 20px; font-size: 15px; }
.card { background: var(--card); color: var(--card-foreground); border: 1px solid var(--border); border-radius: var(--radius); }
.card-header { padding: 20px 20px 0; }
.card-title { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 18px; font-weight: 500; letter-spacing: -0.01em; }
.card-description { margin: 4px 0 0; color: var(--muted-foreground); font-size: 14px; }
.card-content { padding: 20px; }
.card-footer { display: flex; align-items: center; gap: 8px; padding: 0 20px 20px; }
.field { min-width: 0; margin: 0 0 20px; padding: 0; border: 0; }
.field:last-child { margin-bottom: 0; }
.label, .field > label, .field > legend {
  display: flex; align-items: center; gap: 6px; margin: 0 0 8px;
  padding: 0; font-size: 14px; font-weight: 500;
}
.label .icon { color: var(--muted-foreground); }
.input, .select {
  display: block; width: 100%; height: 40px; padding: 0 12px;
  border: 1px solid var(--input); border-radius: var(--radius-control);
  background: var(--card); color: var(--foreground); font: inherit; font-size: 15px;
}
.input:hover { border-color: var(--foreground); }
.input::placeholder { color: var(--muted-foreground); }
.hint { margin: 4px 0 0; color: var(--muted-foreground); font-size: 13px; }
.checkbox-group { display: flex; flex-wrap: wrap; gap: 8px; }
.checkbox {
  position: relative; display: inline-flex; align-items: center; gap: 6px;
  margin: 0; padding: 8px 12px; border: 1px solid var(--input);
  border-radius: var(--radius-control); background: var(--card);
  font-size: 14px; font-weight: 400; cursor: pointer; user-select: none;
}
.checkbox:hover { background: var(--accent); }
.checkbox input { position: absolute; width: 1px; height: 1px; margin: 0; opacity: 0; }
.checkbox:has(input:checked) { border-color: var(--primary); background: var(--primary); color: var(--primary-foreground); }
.checkbox:has(input:checked):hover { background: color-mix(in srgb, var(--primary) 88%, var(--foreground)); }
.checkbox:has(input:focus-visible) { outline: 2px solid var(--ring); outline-offset: 2px; }
.alert { display: flex; align-items: flex-start; gap: 8px; padding: 12px 16px; border: 1px solid var(--border); border-radius: var(--radius-control); background: var(--muted); font-size: 14px; }
.alert p { margin: 0; }
.alert .icon { margin-top: 2px; }
.alert-info {
  border-color: color-mix(in srgb, var(--primary) 30%, var(--border));
  background: color-mix(in srgb, var(--primary) 5%, var(--card));
}
.alert-destructive {
  border-color: color-mix(in srgb, var(--destructive) 35%, var(--border));
  background: color-mix(in srgb, var(--destructive) 7%, var(--card));
  color: var(--destructive);
}
.alert-warning {
  border-color: color-mix(in srgb, var(--warning) 35%, var(--border));
  background: color-mix(in srgb, var(--warning) 7%, var(--card));
  color: var(--warning);
}
.separator { height: 1px; margin: 24px 0; border: 0; background: var(--border); }
.section-title {
  display: flex; align-items: center; gap: 8px; margin: 0 0 12px;
  color: var(--secondary-foreground); font-size: 14px; font-weight: 500; letter-spacing: 0;
}
.section-title::before { content: ""; width: 10px; height: 8px; flex: none; border-left: 2px solid var(--primary); border-bottom: 2px solid var(--primary); }
.form-grid { display: grid; grid-template-columns: 1fr; gap: 0 24px; }
.form-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 24px; }
.stats { display: grid; grid-template-columns: 1fr; gap: 0; margin: 0; border-top: 1px solid var(--border); }
.stat { padding: 16px 0; border-bottom: 1px solid var(--border); }
.stat h3 { margin: 0 0 4px; font-size: 15px; font-weight: 500; }
.stat p { margin: 0; color: var(--muted-foreground); font-size: 13px; }
.note { display: flex; align-items: flex-start; gap: 8px; margin: 16px 0 0; color: var(--muted-foreground); font-size: 13px; }
.note .icon { margin-top: 2px; }
.footer { border-top: 1px solid var(--border); padding: 20px 0; color: var(--muted-foreground); font-size: 13px; }
.footer-inner { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; }
.footer a { display: inline-flex; align-items: center; gap: 6px; }
.error-card { max-width: 640px; }
.error-title { margin: 0 0 16px; font-size: clamp(1.75rem, 1.2rem + 2vw, 2.25rem); line-height: 1.1; font-weight: 500; letter-spacing: -0.015em; }
.error-actions { margin-top: 20px; }
:where(a, button, input, select, textarea, summary, [tabindex]):focus-visible {
  outline: 2px solid var(--ring);
  outline-offset: 2px;
}
@media (min-width: 720px) {
  .container { padding-left: 24px; padding-right: 24px; }
  main.container { padding-top: 40px; padding-bottom: 64px; }
  .form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .stats { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 32px; }
  .stat { border-bottom: 0; }
}
@media (prefers-reduced-motion: no-preference) {
  @keyframes rise {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: none; }
  }
  .hero, .page-enter { animation: rise 400ms cubic-bezier(0.22, 1, 0.36, 1) both; }
  .delay-1 { animation-delay: 60ms; }
  .delay-2 { animation-delay: 120ms; }
  .btn {
    transition: background-color 140ms cubic-bezier(0.22, 1, 0.36, 1),
      border-color 140ms cubic-bezier(0.22, 1, 0.36, 1),
      color 140ms cubic-bezier(0.22, 1, 0.36, 1),
      transform 140ms cubic-bezier(0.22, 1, 0.36, 1);
  }
  .btn:active { transform: scale(0.98); }
}
"""

_NAV = (
    ("generate", "/", "Generate"),
    ("sample", "/sample/", "Sample report"),
    ("about", "/about", "About"),
    ("github", REPO_URL, "GitHub"),
)


def _nav_link(key: str, href: str, label: str, active: str) -> str:
    """One header link, marked with ``aria-current`` when it is the open page."""
    current = ' aria-current="page"' if key == active else ""
    icon = ICONS["github"] if key == "github" else ""
    return f'<a class="nav-link" href="{escape(href, quote=True)}"{current}>{icon}{escape(label)}</a>'


def page_shell(title: str, body: str, *, active: str = "") -> str:
    """Wrap ``body`` in the full document: head, header nav, main and footer.

    ``active`` is one of ``generate``, ``sample``, ``about`` or ``github`` and
    marks that nav link with ``aria-current="page"``. The body is trusted HTML
    built by this package; the title is escaped.
    """
    safe_title = escape(title.strip())
    if safe_title in {"", "TaskFactory"}:
        document_title = "TaskFactory"
    else:
        document_title = f"{safe_title} \u00b7 TaskFactory"
    nav = "\n".join(_nav_link(key, href, label, active) for key, href, label in _NAV)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{document_title}</title>
<style>{STYLESHEET}</style>
</head>
<body>
<header class="site-header">
<div class="container header-inner">
<a class="brand" href="/">{ICONS["beaker"]}<span>TaskFactory</span></a>
<nav class="nav" aria-label="Main">
{nav}
</nav>
</div>
</header>
<main class="container">
{body}
</main>
<footer class="footer">
<div class="container footer-inner">
<span>Free and open source. No billing, no key fields on this site.</span>
<a href="{REPO_URL}">{ICONS["github"]}<span>GitHub</span></a>
</div>
</footer>
</body>
</html>
"""
