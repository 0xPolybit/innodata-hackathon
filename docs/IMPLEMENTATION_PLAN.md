# Implementation plan: one app, hosted and local

Status: draft, 20 Nov 2026. Deadline 6 Dec 2026. Everything free: Vercel Hobby (non-commercial demo), no paid plan, no billing details. Ollama and Gemma are already removed from the machine.

## 1. Summary

"Fully functional" means one codebase runs in two places:

- **Hosted:** a public `*.vercel.app` URL. A visitor fills a short form and gets charts, questions, exact answers, all seven check results, rejected items with reasons, and a ZIP.
- **Local:** the same form and output on the developer's machine, plus the Gemini/OpenRouter benchmark. The hosted app calls no model and has no key field.

| # | Acceptance test | Pass rule |
|---|---|---|
| H1 | Open the hosted URL on phone and laptop | Form renders; no login; no key field |
| H2 | Submit the defaults | 15 attempted; each accepted task shows seven passing checks |
| H3 | Compare three shown answers with chart labels | All three match |
| H4 | Read the rejected list | Each item names a failed check |
| H5 | Open the ZIP | Six files per package plus indices, `metrics.json`, `run.json` |
| H6 | Open `/api/health` and `/api/version` | `ok`; version and 40-character commit |
| H7 | View source and network log | No key, no model call, no `.env` value |
| L1 | `tf serve` | Same form at `127.0.0.1:8000` |
| L2 | Submit the defaults locally | Same counts and accepted IDs as H2 at one commit |
| L3 | `tf run`, `tf eval`, `pytest` | All still work; eval uses Gemini and OpenRouter only |

## 2. Architecture

```
HOSTED
browser -> Vercel container (Waitress, tesseract-ocr)
  GET  /   /api/health   /api/version
  POST /api/generate -> results HTML (inline PNGs)
  POST /api/zip      -> ZIP stream
       | canonical TOML in /tmp/<id>/configs/{runs,domains}
  pipeline.run_pipeline: sample -> render -> questions -> 7 checks -> package
       | output in /tmp, deleted after the response

LOCAL
tf serve -> same WSGI app and routes
tf run / tf eval / tf report -> CLI; eval uses Gemini + OpenRouter, keys in .env
```

**New:** `src/taskfactory/web/{app,forms,render}.py`, templates, `tests/test_web.py`, `Dockerfile`, `.dockerignore`, `vercel.json`, `site/` (static fallback), `scripts/spike_gate.py`, `docs/DEPLOY.md`.

**Changed:** `cli.py` (`serve`), `pyproject.toml` (waitress, package data), `uv.lock`, `pipeline.py` (explicit SHA), `package.py` (SHA resolution), `README.md`, `PROTOTYPE_BRIEF.md`, plus section 5.

Trap: `pipeline.py` finds domains at `<config>.parent.parent`. Write `/tmp/<id>/configs/runs/request.toml`, copy `domains/` and `blocklist.txt` beside it, and set `MPLCONFIGDIR` and `TMPDIR` to `/tmp`; everything else is read-only.

## 3. Inputs

| Field | Default | Allowed | Effect |
|---|---|---|---|
| Seed | `20261206` | 1 to 2147483647 | `run_seed`, fixes every spec |
| Charts per type | 3 | 1 to 6 | `tasks_per_cell` for each family |
| Chart types | bar + line | bar, line; at least one | `families`; no floor plan, no `spatial` |
| Domain | tourism | tourism, retail, energy | `domains` |
| Question types | all five | the five; at least one | `question_types`; `series_at_x` needs line, the other four need bar |
| Difficulty | standard | standard, harder | standard 0.05 margin / 9 px / 8 bars; harder 0.02 / 7 px / 12 bars |
| Print question on image | on | on, off | `question_in_image`; the answer is always printed |

Defaults give 12 bar tasks (3 charts x 4 bar types) + 3 line tasks = **15**. Any combination above **24 tasks** is refused. No benchmark controls, no key fields.

## 4. Output

**Results page:** run ID from the config hash (never a timestamp), commit, seed, counts, a seven-check aggregate table, one card per task (chart, question, exact answer, type, domain, check chips), rejected items with failed check names, and a download button that reposts the canonical form to `/api/zip`. The ZIP is regenerated, not stored, so the app stays stateless and identical for identical inputs.

**ZIP:** `tasks/<id>/` with `image.png`, `spec.json`, `task.json`, `text_boxes.json`, `validation.json`, `manifest.json`; `rejected/<id>/` with the same plus failing `validation.json`; `tasks.jsonl`, `validation.jsonl`, `metrics.json`, `run.json` (seed, hash, commit, versions, Tesseract), `README.txt`. No keys, `.env`, or benchmark data.

## 5. Ollama removal

Reason: the hosted app does not use Ollama, the model is gone so those paths cannot run, and the Gemini/OpenRouter benchmarks remain.

| File | Change |
|---|---|
| `llm.py` | Delete `call_ollama`, `OLLAMA_URL`, the `ollama` entries in `PROVIDERS` and `DEFAULT_MIN_INTERVAL_S`, and the docstring mention |
| `configs/models.toml` | Delete the `gemma3:4b` block; three evaluated models remain |
| `tests/test_llm.py` | Delete the Ollama request test; use OpenRouter with a fake key for no-key cases; update the provider list and interval assertion |
| `tests/test_config.py` | Test `check_no_secondary_in_eval` with a temporary TOML; assert the real roster has no secondary entries |
| `tests/test_benchmark.py` | Fixture secondary `local-check` changes provider to `gemini`; it is only tested as excluded |
| Docs | Remove Ollama/Gemma from `PROTOTYPE_BRIEF.md`, `IDEA_SUBMISSION.md`, `PLAN.md` (§4.1, §4.2, §4.5, §4.6, SU3, SU6, §7, §9, §10, free-stack table) |
| Keep | `check_no_secondary_in_eval` is generic policy and stays |

Proof: `grep -ri "ollama\|gemma" src configs tests docs` returns nothing and `pytest` passes. The S1 Gemma check was documentation only.

## 6. Build steps

| Day | Step and goal | Files | Proof | Size |
|---|---|---|---|---|
| 22 Nov | **Static sample site.** Landing page plus committed report as Option A fallback | `site/`, `vercel.json` | URL serves the report; links work | S |
| 23 Nov | **Ollama removal, form shell.** Clean roster; `tf serve` renders the form | section 5, `web/app.py`, `cli.py` | `pytest`; defaults show | S |
| 25 Nov | **Container spike and gate.** Pinned image, Tesseract, fixed-default generation | `Dockerfile`, `vercel.json`, `scripts/spike_gate.py` | Gate: 15 tasks, 7/7 checks, under 180 s, under 4.5 MB; seconds and bytes recorded in `docs/DEPLOY.md` | L |
| 27 Nov | **Real generation.** Validate every field, build canonical config, enforce caps | `web/forms.py`, `web/app.py` | Each field changes output; bad input gets section 9 messages | M |
| 29 Nov | **Results page and ZIP.** Charts, answers, checks, rejects, download | `web/render.py`, templates | All items shown; ZIP opens with six files per package | M |
| 2 Dec | **Hardening and docs.** Size, timeout, cleanup, secret scan, `DEPLOY.md` | `web/*`, `docs/DEPLOY.md`, `README.md` | No key text in responses; forced failure shows its message | M |
| 4 Dec | **Fresh-clone replay.** New clone, `uv sync --locked`, tests, local defaults | none | Local and hosted counts, IDs and spec/answer hashes match | M |

The 25 Nov gate is stop/go: if it fails, ship Option A and keep generation local.

## 7. Local run path

`tf serve --port 8000` runs Waitress on `127.0.0.1:8000` with the same app, form, canonical config builder, routes and cap. Tesseract comes from `TESSERACT_CMD`, the usual Windows path, then `PATH`. The commit comes from git; hosted uses `VERCEL_GIT_COMMIT_SHA`. Output goes to temp, never `out/`, and is deleted after the response. `docker run -p 8000:8000 <image>` is the optional production-like path.

Same inputs and commit give the same specs, questions, answers, checks and run ID. PNG bytes may differ across machines; they are stable inside the pinned image. Compare JSON hashes across machines, bytes within one.

## 8. Verification plan

| Check | How | Expect |
|---|---|---|
| Health, version | `curl /api/health`, `/api/version` | `ok`; version, 40-character commit, image digest |
| Generate | POST defaults | 15 attempted; seven check names per task; rejects have reasons |
| Size | `curl -w "%{size_download}"`; `unzip -l` | Page and ZIP each under 4.5 MB |
| Timing | Time the POST | Under 180 s (gate); typical value recorded, not promised |
| Determinism | POST twice; sha256 of sorted `spec.json` + `task.json`, and `tasks.jsonl` | Identical hashes; local `tf diff` shows 0 changed |
| Bad input | Seed `abc`; 6 charts with all types; no question type | Section 9 messages, no traceback |
| Secrets, benchmark | Grep responses and logs for `AIza`, `sk-`, `.env`; run benchmark tests | No match; benchmark tests pass with fakes |
| Container config details | Spike | **UNVERIFIED** until 25 Nov |

## 9. Failure handling

| Failure | Exact user message |
|---|---|
| Timeout (300 s) | "Generation took longer than the 300 second limit. Choose fewer charts and try again. The sample report still works." |
| Out of memory | "The generator ran out of memory. Choose fewer charts and try again." |
| Request too large | "Your request is too large. Reload the form and choose fewer charts." |
| Response or ZIP too large | "The result is too large to send. Choose fewer charts, or open the sample report." |
| Monthly CPU quota (4 h) | "The free monthly compute limit for this demo is used up. Try again next month, or run the app locally. The sample report is still available." |
| Bad input | "Seed must be a whole number between 1 and 2147483647." / "Charts per type must be between 1 and 6." / "This choice makes 30 tasks; the limit is 24. Choose fewer charts or question types." / "Pick at least one chart type and one question type." |
| Cold start | "Starting the demo. The first request can take up to 60 seconds." (timing **UNVERIFIED**) |
| Build size (build time) | Build fails; fallback page: "The live generator is offline. You are viewing the committed sample report." |

## 10. Risks and fallbacks

| Risk | Fallback |
|---|---|
| Container runtime beta or config detail wrong | Ship Option A; keep generation local; show it in the video |
| Tesseract or a wheel missing in the image | Caught by the gate; fix before form work continues |
| 4 CPU-hours/month too small | Lower the default cap; static fallback banner |
| Over 4.5 MB | Thumbnails; ZIP stream only; omit `text_boxes.json` from the ZIP |
| PNG bytes differ on Vercel | Compare JSON hashes; pin and publish the image digest |
| Hobby is non-commercial | Hackathon demo only; no ads, payments, or commercial use |
| Generation exceeds 300 s | Cut the hard cap to 15 and tell the user to retry smaller |

## 11. Decisions still open

| Decision | Default |
|---|---|
| Domains offered | tourism, retail, energy; tourism preselected |
| Show "harder" difficulty | Yes; standard preselected |
| Charts-per-type maximum | 6, with the 24-task cap enforced |
| ZIP replay or stored in `/tmp` | Replay: stateless and deterministic |
| Link the benchmark report in the nav | Yes, labelled "sample, run locally" |
| Per-IP rate limiting | None; rely on Vercel and the cap |
| Inline charts | Yes, sized to stay under 4.5 MB |

## 12. Simple version

- The site works like the app on a laptop: same form, charts and answers.
- You keep the default seed or type your own, choose charts and questions, and press Generate.
- It makes about 15 tasks by default and never more than 24.
- Each task shows its chart, question, exact answer and seven checks.
- Any task that fails a check is listed with the reason.
- You can download everything as one ZIP file.
- The site does not test AI models and has nowhere to enter a key.
- Model testing happens on a laptop with free keys kept in a local file.
- Ollama and Gemma are removed because the site does not use them.
- The same seed and same code give the same tasks, so runs repeat.
- If the live generator breaks, a saved sample report is shown instead.
- Everything is free and asks for no payment details.
