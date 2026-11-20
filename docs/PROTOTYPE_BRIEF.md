# Prototype brief: TaskFactory

Status: working prototype, 2026-11-20. Repo: https://github.com/0xPolybit/innodata-hackathon

## What it is

A factory that makes chart questions with known answers, checks each one without an AI model, and scores free vision models on a fixed set of items. The output is a static HTML report, and a web app runs the same generator locally or in a container.

## What works now

| Part | Evidence |
|---|---|
| Generates bar and line charts from seeded configs | `tf run` on `configs/runs/pool.toml` gave 565 generated, 564 accepted (yield 0.998) |
| Five question types with exact answers | Ground truth comes from the generated data, not from a model |
| Seven deterministic checks, with a rejection path | Rejected tasks are kept with the reason |
| Self-test of the checks with planted defects | 20 of 20 clean packages pass; every planted defect class is caught in full and content-only modes |
| Benchmark on free models with cache and retries | Gemini 3.1 Flash-Lite 97.5% and Gemini 3.5 Flash-Lite 95.5% on the 200-item set |
| Static HTML report | Opens from a local file; no scripts, no external links |
| Web app, local and hosted | `tf serve` and the container serve the same form at `/`, the results page, the ZIP and the status routes. No key field, no model call |
| Container, measured on 20 November 2026 | 841 MB image on a pinned `python:3.13-slim` base with Tesseract 5.5.0 |
| Local gate at the same check | Exit 0: 14 attempted, 14 accepted, 0 rejected, every task 7/7; 968,203-byte response in 9.6 seconds |
| Sample site | `/about` is the landing page and `/sample/` is the committed static report |
| Test suite | Full suite passes with no API keys needed |

Not built: floor plans, the `generate`, `validate` and `score` commands, and offline replay from files.

## Technology list (all free)

| Technology | Used for | Free route | Billing needed |
|---|---|---|---|
| Python 3.12+ (tested on 3.14) | Whole package | Open source | No |
| matplotlib, Pillow, numpy | Drawing charts, image handling | Open source | No |
| OpenCV (headless) | Independent pixel reader | Open source | No |
| Tesseract OCR | OCR read-back check | Open source, free install | No |
| pytest | Test suite | Open source | No |
| Google AI Studio (Gemini API) | Benchmark: Gemini 3.1 and 3.5 Flash-Lite | Free tier; API key only | No |
| OpenRouter `:free` models | Benchmark: Nemotron vision model | Free models; key only; no credit purchase | No |
| Plain files and JSONL | Tasks, answers, caches, manifests | No database | No |
| Static HTML | Report | Plain files, no server | No |
| GitHub repo and GitHub Pages | Code and report link | Free for public repos | No |
| Mermaid or draw.io | Diagrams | Free | No |
| OBS Studio | Demo video | Free | No |
| Google Slides | Deck, on the required template | Free | No |

No database or paid API is used. Hosting is Vercel's free Hobby plan, with no billing details; the model benchmark stays local. Nothing in the project asks for payment details.

## Cost

Service cost: 0. The only costs are our own laptops and time. Free-tier limits set the benchmark size: 200 items per model, and the OpenRouter model takes several days at its 50-request daily cap.

Free tiers can change. The model roster was checked on 19 Nov 2026 (see `configs/models.toml`).

## How to run it

See the Quick start in `README.md`. The short path:

1. `tf run --config configs/runs/demo.toml --run-id demo1 --out out\demo` (generates and checks tasks)
2. `tf eval --items out\eval\items.jsonl --out out\eval` (needs free API keys in `.env`)
3. `tf report --pool out\pool --eval out\eval --out out\report --selftest out\report\selftest.json`
4. Open `out\report\index.html`

## Known limits

- Synthetic charts only, so the benchmark does not show performance on real reports.
- The two Gemini models have full results on the 200 items. The OpenRouter model is partial because of its daily cap.
- The standard set cannot separate the two Gemini models: their 95% intervals overlap (94.3 to 98.9 and 91.7 to 97.6).
- The harder tiers are only a little harder for the models, and the hardest tier (12 bars, 81.6% yield) has been scored on 90 of its 200 items so far.
- The default form plans 15 tasks; the pipeline attempts 14 at the default seed because the margin rule skips one. The cap is 24 tasks.
- The platform stops a request at 300 seconds and the app's own budget is 280. A run that times out cannot be killed; it holds the one-generation lock until it ends.
- The results page is capped at 4,000,000 bytes and kept artifacts at 3,500,000 bytes; the platform response limit is about 4.5 MB.
- The free monthly allowance is 4 CPU-hours. The app cannot read it; Vercel's platform page reports exhaustion. There is no per-IP rate limiting.
- A cold start can take up to 60 seconds according to the form note; this figure is unverified.
- The Container runtime is in beta, and Hobby is for non-commercial use.
- PNG bytes can differ across machines; the JSON files and run IDs stay deterministic.
- The self-test has no `tf` command yet.
- Human audit is not done.
- Floor plans are not built.

## Next steps

- Finish the OpenRouter run (about 100 items left, at 50 a day).
- Finish the hardest tier's Gemini run (110 items left).
- Human audit: the kit is ready in `audit/`; the review is still to do.
- Freeze the run and publish the report on GitHub Pages.
