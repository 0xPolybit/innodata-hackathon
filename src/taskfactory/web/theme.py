# Icons: Lucide (https://lucide.dev), ISC License. The paths are inlined below.
"""The shared TaskFactory design system: inline Lucide icons, one stylesheet, one page shell.

The look follows shadcn/ui's default neutral theme: 0.5rem radius, 1px borders,
soft shadows, muted surfaces and a visible focus ring. There is no build step,
no font download and no script. The static landing page in ``site/index.html``
carries a copy of :data:`STYLESHEET`; keep the two in sync.

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
# palette is shadcn/ui's neutral theme, expressed as plain CSS custom
# properties so a dark scheme only redefines tokens.
STYLESHEET = """
:root {
  color-scheme: light;
  --background: #ffffff;
  --foreground: #0a0a0a;
  --card: #ffffff;
  --card-foreground: #0a0a0a;
  --primary: #171717;
  --primary-foreground: #fafafa;
  --secondary: #f5f5f5;
  --secondary-foreground: #171717;
  --muted: #f5f5f5;
  --muted-foreground: #737373;
  --accent: #f5f5f5;
  --accent-foreground: #171717;
  --destructive: #dc2626;
  --success: #16a34a;
  --warning: #d97706;
  --border: #e5e5e5;
  --input: #e5e5e5;
  --ring: #a3a3a3;
  --radius: 0.5rem;
  --shadow: 0 1px 2px rgb(0 0 0 / 0.05);
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --background: #0a0a0a;
    --foreground: #fafafa;
    --card: #111111;
    --card-foreground: #fafafa;
    --primary: #fafafa;
    --primary-foreground: #171717;
    --secondary: #262626;
    --secondary-foreground: #fafafa;
    --muted: #262626;
    --muted-foreground: #a3a3a3;
    --accent: #262626;
    --accent-foreground: #fafafa;
    --destructive: #f87171;
    --success: #4ade80;
    --warning: #fbbf24;
    --border: #262626;
    --input: #262626;
    --ring: #525252;
    --shadow: 0 1px 2px rgb(0 0 0 / 0.5);
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }
body {
  margin: 0;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--background);
  color: var(--foreground);
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 15px;
  line-height: 1.55;
}
a { color: inherit; text-decoration: none; }
a:hover { text-decoration: underline; text-underline-offset: 3px; }
.icon { width: 1.05em; height: 1.05em; flex: none; vertical-align: -0.12em; }
.container {
  width: 100%;
  max-width: 1120px;
  margin: 0 auto;
  padding-left: 16px;
  padding-right: 16px;
}
main.container { flex: 1; padding-top: 2rem; padding-bottom: 3rem; }
.site-header { border-bottom: 1px solid var(--border); background: var(--card); }
.header-inner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  min-height: 3.5rem;
  padding-top: 0.5rem;
  padding-bottom: 0.5rem;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1rem;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.brand .icon { width: 1.35rem; height: 1.35rem; }
.nav { display: flex; flex-wrap: wrap; align-items: center; gap: 0.15rem; }
.nav a {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.45rem 0.65rem;
  border-radius: calc(var(--radius) - 2px);
  color: var(--muted-foreground);
  font-size: 0.875rem;
  font-weight: 500;
}
.nav a:hover { background: var(--accent); color: var(--foreground); text-decoration: none; }
.nav a[aria-current="page"] { background: var(--accent); color: var(--foreground); }
.hero { max-width: 46rem; padding: 1.25rem 0 1.75rem; }
.hero h1 {
  margin: 0.75rem 0 0.5rem;
  font-size: clamp(1.75rem, 5vw, 2.5rem);
  line-height: 1.1;
  letter-spacing: -0.02em;
}
.hero p { max-width: 40rem; margin: 0; color: var(--muted-foreground); font-size: 1rem; }
.badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.2rem 0.65rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--secondary);
  color: var(--secondary-foreground);
  font-size: 0.75rem;
  font-weight: 600;
}
.badge-success {
  border-color: color-mix(in srgb, var(--success) 35%, var(--border));
  background: color-mix(in srgb, var(--success) 10%, var(--card));
  color: color-mix(in srgb, var(--success) 80%, var(--foreground));
}
.badge-destructive {
  border-color: color-mix(in srgb, var(--destructive) 35%, var(--border));
  background: color-mix(in srgb, var(--destructive) 10%, var(--card));
  color: color-mix(in srgb, var(--destructive) 80%, var(--foreground));
}
.badge-muted { background: var(--muted); color: var(--muted-foreground); }
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  height: 2.5rem;
  padding: 0 1rem;
  border: 1px solid transparent;
  border-radius: calc(var(--radius) - 2px);
  background: var(--secondary);
  color: var(--secondary-foreground);
  font: inherit;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
}
.btn:hover { background: color-mix(in srgb, var(--secondary) 82%, var(--foreground)); text-decoration: none; }
.btn-primary { background: var(--primary); color: var(--primary-foreground); }
.btn-primary:hover { background: color-mix(in srgb, var(--primary) 88%, var(--background)); }
.btn-outline { border-color: var(--input); background: var(--card); color: var(--foreground); }
.btn-outline:hover { background: var(--accent); }
.btn-ghost { background: transparent; color: var(--foreground); }
.btn-ghost:hover { background: var(--accent); }
.btn-lg { height: 2.75rem; padding: 0 1.5rem; font-size: 0.95rem; }
.card {
  background: var(--card);
  color: var(--card-foreground);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}
.card-header { padding: 1.25rem 1.25rem 0; }
.card-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  font-size: 1.125rem;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.card-description { margin: 0.35rem 0 0; color: var(--muted-foreground); font-size: 0.875rem; }
.card-content { padding: 1.25rem; }
.card-footer { display: flex; align-items: center; gap: 0.5rem; padding: 0 1.25rem 1.25rem; }
.field { min-width: 0; margin: 0 0 1.1rem; padding: 0; border: 0; }
.field:last-child { margin-bottom: 0; }
.label,
.field > label,
.field > legend {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0 0 0.35rem;
  padding: 0;
  font-size: 0.875rem;
  font-weight: 600;
}
.label .icon { color: var(--muted-foreground); }
.input,
.select {
  display: block;
  width: 100%;
  height: 2.5rem;
  padding: 0 0.75rem;
  border: 1px solid var(--input);
  border-radius: calc(var(--radius) - 2px);
  background: var(--background);
  color: var(--foreground);
  font: inherit;
  font-size: 0.95rem;
}
.input:hover { border-color: var(--ring); }
.input::placeholder { color: var(--muted-foreground); }
.hint { margin: 0.35rem 0 0; color: var(--muted-foreground); font-size: 0.8rem; }
.checkbox-group { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.checkbox {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0;
  padding: 0.45rem 0.8rem;
  border: 1px solid var(--input);
  border-radius: 999px;
  background: var(--card);
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  user-select: none;
}
.checkbox:hover { background: var(--accent); }
.checkbox input { position: absolute; width: 1px; height: 1px; margin: 0; opacity: 0; }
.checkbox:has(input:checked) {
  border-color: var(--primary);
  background: var(--primary);
  color: var(--primary-foreground);
}
.checkbox:has(input:checked):hover { background: color-mix(in srgb, var(--primary) 88%, var(--background)); }
.checkbox:has(input:focus-visible) { outline: 2px solid var(--ring); outline-offset: 2px; }
.alert {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border);
  border-radius: calc(var(--radius) - 2px);
  background: var(--muted);
  font-size: 0.875rem;
}
.alert p { margin: 0; }
.alert .icon { margin-top: 0.15rem; }
.alert-info {
  border-color: color-mix(in srgb, var(--primary) 18%, var(--border));
  background: color-mix(in srgb, var(--primary) 6%, var(--card));
}
.alert-destructive {
  border-color: color-mix(in srgb, var(--destructive) 40%, var(--border));
  background: color-mix(in srgb, var(--destructive) 8%, var(--card));
  color: color-mix(in srgb, var(--destructive) 55%, var(--foreground));
}
.alert-warning {
  border-color: color-mix(in srgb, var(--warning) 40%, var(--border));
  background: color-mix(in srgb, var(--warning) 10%, var(--card));
  color: color-mix(in srgb, var(--warning) 45%, var(--foreground));
}
.separator { height: 1px; margin: 1.5rem 0; border: 0; background: var(--border); }
.section-title {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin: 0 0 0.9rem;
  color: var(--muted-foreground);
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.form-grid { display: grid; grid-template-columns: 1fr; gap: 0 1.25rem; }
.form-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; margin-top: 1.5rem; }
.stats { display: grid; grid-template-columns: 1fr; gap: 1rem; margin-top: 1.75rem; }
.stat {
  padding: 1rem 1.1rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--card);
  box-shadow: var(--shadow);
}
.stat h3 { display: flex; align-items: center; gap: 0.45rem; margin: 0 0 0.25rem; font-size: 0.95rem; }
.stat p { margin: 0; color: var(--muted-foreground); font-size: 0.85rem; }
.footer { border-top: 1px solid var(--border); padding: 1.25rem 0; color: var(--muted-foreground); font-size: 0.8rem; }
.footer-inner { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.5rem; }
.footer a { display: inline-flex; align-items: center; gap: 0.35rem; }
.error-card { max-width: 40rem; }
.error-actions { margin-top: 1rem; }
:where(a, button, input, select, textarea, summary, [tabindex]):focus-visible {
  outline: 2px solid var(--ring);
  outline-offset: 2px;
}
@media (min-width: 720px) {
  main.container { padding-top: 3rem; }
  .form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .stats { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (prefers-reduced-motion: no-preference) {
  @keyframes fade-up {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }
  @keyframes float {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-2px); }
  }
  .hero, .card, .stat { animation: fade-up 400ms ease-out both; }
  .delay-1 { animation-delay: 80ms; }
  .delay-2 { animation-delay: 160ms; }
  .brand .icon { animation: float 6s ease-in-out infinite; }
  .btn {
    transition: background-color 120ms ease, border-color 120ms ease,
      color 120ms ease, transform 120ms ease;
  }
  .btn:active { transform: translateY(1px); }
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
