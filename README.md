# TaskFactory

A free, automated factory for visual test tasks. It draws synthetic bar and line charts from seeded data, asks a question with a known exact answer, checks each task without any AI model, and then scores free vision models on the same items.

Track 2 (Visual Task Factory) of the Innodata AI Hackathon. Service cost: 0. No billing details are needed for any part.

## What it does

1. **Generate.** A config file sets the domain, families and question types. Each task gets a seed, so the same config always gives the same tasks.
2. **Check.** Each task passes deterministic checks: schema, layout, ambiguity margin, OCR read-back (Tesseract), an independent pixel reader (OpenCV), a counterfactual redraw, and a byte-level redraw check. Tasks that fail are moved to `rejected/` with the reason.
3. **Package.** Accepted tasks are saved as folders with the image, question, answer and validation record.
4. **Benchmark.** A frozen set of 200 items is sent to free models (Gemini and OpenRouter). Answers are cached and graded by exact match with no model involved. Each wrong answer gets one error label.
5. **Report.** One static HTML page shows the funnel, self-test results, accuracy by model and question type, and examples.

## Status

| Part | State |
|---|---|
| Bar and line charts, five question types | Built |
| Seven checks and the rejection path | Built |
| Pool of about 565 tasks (`configs/runs/pool.toml`) | Built; 564 pass |
| Self-test with planted defects | Built; 20 of 20 clean packages pass, all planted defects caught |
| Benchmark runner (Gemini, OpenRouter, Ollama) with cache and retries | Built |
| Static report | Built |
| Harder tier (`configs/runs/hard.toml`) | In progress |
| Floor plans | Not built (dropped from the MVP scope) |
| `tf generate`, `tf validate`, `tf score`, `tf diff` | Placeholders; they print "not implemented" |
| Offline replay from files | Not built yet |

## Quick start

Requirements: Windows 10 or 11, Python 3.12 or newer (3.14 tested), Git. Tesseract OCR is needed for the OCR check.

```powershell
git clone https://github.com/0xPolybit/innodata-hackathon.git
cd innodata-hackathon
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Install Tesseract (for example `winget install UB-Mannheim.TesseractOCR`). The tool looks for it in `TESSERACT_CMD`, then in the usual install folder, then on `PATH`.

### Generate tasks

```powershell
.\.venv\Scripts\tf.exe run --config configs/runs/demo.toml --run-id demo1 --out out\demo
```

Output: `out\demo\tasks\` (one folder per accepted task), `out\demo\rejected\`, `out\demo\validation.jsonl`, and `out\demo\metrics.json`. The metrics also print to the terminal.

Use `--overwrite` to delete the old output in `--out` first.

### Benchmark (needs free API keys)

Create a Google AI Studio key and an OpenRouter key (no credit purchase). Put them in a `.env` file at the repo root, which git ignores:

```
GEMINI_API_KEY=your-key
OPENROUTER_API_KEY=your-key
```

Then:

```powershell
.\.venv\Scripts\tf.exe eval --items out\eval\items.jsonl --out out\eval
```

This reads the frozen item set at `--items`. To build that set from a pool first, add `--build-from out\pool\tasks`. Answers are cached per model, so a rerun continues where it stopped. OpenRouter's free models allow about 50 requests a day, so the full 200-item set for that model takes several days.

Smoke test on a few items:

```powershell
.\.venv\Scripts\tf.exe eval --items out\eval\items.jsonl --out out\eval --limit 5
```

### Report

```powershell
.\.venv\Scripts\tf.exe report --pool out\pool --eval out\eval --out out\report --selftest out\report\selftest.json
```

Open `out\report\index.html` in a browser. The page has no scripts and loads nothing from the internet.

## Configuration

| File | What it sets |
|---|---|
| `configs/runs/*.toml` | Seed, tasks per cell, families, domains, question types, check thresholds, eval settings |
| `configs/domains/*.toml` | Title, categories, value range and format for one domain |
| `configs/models.toml` | Evaluated and secondary models, with their free-tier limits |
| `configs/blocklist.txt` | Terms that may not appear in titles or categories |

A new domain is one TOML file. A run uses domains by file name.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The suite has 544 tests and needs no API keys. It covers the sampler, renderers, questions, each check, the pipeline, the benchmark (with fake providers), the report and the self-test.

The self-test plants five kinds of defect in copies of good tasks and checks that the pipeline catches them. It has no `tf` command yet. Call it from Python, with the pool's package folders and a work folder outside them. The function is `run_selftest` in `src/taskfactory/selftest.py`. It returns the catch rate per defect class, in two modes: full, and content-only (redraw checks excluded). Save the result as JSON and pass that file to `tf report --selftest`.

## Repository layout

```
configs/          run, domain, model and blocklist files
docs/             PLAN.md (plan and schedule), IDEA_SUBMISSION.md, PROTOTYPE_BRIEF.md
src/taskfactory/  the package; cli.py is the `tf` command
tests/            pytest suite
out/              generated output (git ignored)
```

## Limits

- Only bar and line charts are built. Floor plans are not.
- Answers are exact-match graded. Models are not asked for free text.
- The benchmark uses synthetic data, so it does not show how models do on real reports.
- Free-tier quotas set the sample size: 200 items per model.
- We do not claim the data is secret. Random data for each run only reduces the chance that a model has memorised the answers.
- The checks are only as good as the OCR and the pixel reader. The rejection log shows the cases they miss or reject.

## Documentation

- `docs/PLAN.md`: plan, rubric mapping, task schedule, open questions and defaults.
- `docs/PROTOTYPE_BRIEF.md`: the technology list and cost statement.
- `docs/IDEA_SUBMISSION.md`: draft answers for the submission form.
