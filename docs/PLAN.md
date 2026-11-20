# Build plan: Innodata AI Hackathon prototype

Status: draft v3, 2026-11-19 (task-sequenced schedule; every component free, no billing)
Based on: source brief (session auto-captions and event pages)

People are referred to by role. Facts marked (UNCERTAIN) or (UNVERIFIED) come from garbled captions, were not settled by the organisers, or have not been tested by us. See section 11.

**Binding constraint:** every part of the stack is free, with no paid tier and no billing information. No paid API keys, no credit purchases, no paid cloud. Estimated service cost: 0.

---

## 0. TL;DR

- **Track:** Track 2, Visual Task Factory. Fall back to Track 1 only if the organisers rule out code-rendered images (decision gate: the organisers' answer, task G1).
- **Design:** A local Python CLI draws charts and floor plans from seeded, config-driven data, so the reference answer is generator ground truth and is printed in the image. Validity is proven without any model: layout checks, OCR read-back (Tesseract), an independent pixel reader (OpenCV) that recomputes the answer from the image, a counterfactual re-render, and a human audit. The best free-tier multimodal models available on build day are then benchmarked on about 200 stratified items each, with results in a static report on GitHub Pages.
- **MVP by 6 Dec:** 3 image families x 3 domains x 6 question types, a pool of about 500 tasks, full deterministic validation, validator self-test, a 50-task human audit, benchmark of 3 free models, report, deck, video.
- **Demo on 20 Dec:** live run from config, open one task package, walk the report, delete and regenerate with zero manifest diff, add a domain by editing config only. Everything runs offline from cached files.

## 1. What the hackathon asks, in our words

Build a reusable factory, not a fixed dataset. For Track 2, the factory produces visual tasks: an image, a question grounded in it, and an answer that is present in the image. A question not grounded in the image is invalid. A question whose answer is not in the image is invalid. Each output is a task package with its own validation proof. The factory must work across image families by reuse, not by rewriting. Judges score repeatability, validation evidence, meaningful variation, engineering judgement and communication. Hard-coding is not wanted. Manual edits are allowed only if transparent and justified.

## 1A. Application, why errors matter, and what the synthetic examples represent

The Track 2 brief asks which visual capabilities matter most in real use, and how to test them reliably. Our answer:

- **Application.** Assistants that read charts in business and public-sector reports, and floor plans in building documents. Users are analysts checking figures before a decision, and inspectors or facilities staff checking room layouts against a drawing.
- **Why errors matter.** A misread value in a financial or regulatory chart can lead to a wrong budget figure or a wrong disclosure. A wrong room relationship on a plan can lead to a wrong compliance finding. Both errors look confident, so a reviewer may miss them.

| Capability that matters | Question types | Real-world challenge | Synthetic knob that stresses it |
|---|---|---|---|
| Associate a label with the right bar or line | value_lookup | Dense or rotated labels, small fonts | label count, label rotation, min font size |
| Compare and rank categories | extremum, rank_k, pair_compare | Near-equal values, many categories | category count, minimum margin between values |
| Follow one series among several | series_at_x | Legends far from the data, crossing series | series count, distractor series |
| Compare values on a log axis | extremum, rank_k | Log scales in finance and science | log-scale toggle, axis range |
| Reason about layout | spatial | Room adjacency and orientation on plans | room count, orientation |

The synthetic examples are simpler than real documents: no 3-D charts, no hand-drawn plans, no photos. They keep the same visual problems, and every answer is exact. The report shows which challenges each model handles, not just one overall score.

## 2. Rubric to evidence

| Criterion | Weight | Artifact or metric that earns it | How we show it live |
|---|---|---|---|
| Working and repeatable implementation | 25% | One CLI, `tf run --config <file>`. Stable per-task seeds. Pinned lockfile. Cached model responses (JSONL). `tf diff` compares manifests. | Delete output, regenerate, `tf diff` prints 0 changed. Add a domain by config edit, run again. |
| Validity and validation evidence | 25% | Per-task `validation.json` with 7 deterministic checks. Batch funnel. Validator self-test catch rate. Human audit agreement with 95% CI. No evaluated model validates anything. | Open one package. Then the report's funnel, self-test and audit tables. |
| Meaningful variation | 20% | Coverage matrix, structural-difference rate, near-duplicate rejections, reasoning-step histogram, accuracy spread across question types. | Report variation tab: heatmap plus the numbers. |
| Originality and engineering judgement | 15% | Two-path agreement (generator vs pixel reader). Counterfactual re-render. Validator self-test. All on a zero-cost stack. | Show a task each guard rejected, with the reason. |
| Practical impact and communication | 15% | Benchmark of free multimodal models with exact IDs and dates. Deck on the mandatory template. README quickstart. | Close on yield, accuracy by type, and "service cost 0". |

## 3. Track comparison

Effort is working days for a 2-person team.

| Factor | Track 1: Coding Task Factory (ablation variant) | Track 2: Visual Task Factory (rendered variant) |
|---|---|---|
| Inputs we control | No. Three organiser repos, not announced. Format and language unknown. | Yes. We choose families, domains, data. |
| Ground truth | Original code is the reference. Strong. | Computed from the seeded spec. Exact. |
| Repeatable (25) | Needs per-repo Docker env (Docker Engine in WSL2). Env setup is the weak point. | Seeded data, pinned renderer, no containers needed. |
| Validity (25) | Organisers' 3 checks map to 3 local test runs. Very credible. Yield depends on test strength. | 7 deterministic checks + human audit. Credible, model-free. |
| Variation (20) | Limited to what tests cover. Ablations look alike. | Many structural knobs we own. |
| Originality (15) | Ablation-as-task is known (mutation testing). | Two-path agreement and counterfactual re-render are uncommon and easy to explain. |
| Impact (15) | Closest to the organisers' core business. | Clear use cases (chart-QA benchmarks, accessibility, inventory). |
| Free-stack fit | Harbor (Apache-2.0) runs locally with Docker, but its examples need an Anthropic key. A free-model config is UNVERIFIED. Agent runs on free quotas are slow. | Generation and validation are fully local. Models are only used for the benchmark, which fits free quotas. |
| Evidence by 6 Dec | Depends on repo arrival. Maybe 30 to 80 tasks on one repo. | About 500 tasks, full funnel, audit, self-test, benchmark. |
| Biggest technical risk | Repo env unknown; weak or flaky tests; Harbor with a free model untested. | Organisers may require generative-model images, or read "question visible" literally. |
| Build effort (2 people) | 13 to 15 days, blocked until repos arrive. | 8 to 10 days, can start today. |

**Recommendation: Track 2.**
1. We can start today. Track 1 is blocked on repos and on an untested Harbor free-model setup.
2. Ground truth is exact, so validity can be proven with no model at all. This also satisfies "no evaluated model as validator".
3. Variation is driven by parameters we own and can measure.
4. The shared core (config, model client, cache, packaging, manifest, diff, report) is track-agnostic. If gate G1 goes against us, about 40% carries over.

Hedge for the literal reading of "the question must be visible in the image": a config flag `question_in_image = true` prints the question as a caption strip. Default on (see the defaults in section 10).

Track 1 fallback note (Harbor with a free model, UNVERIFIED until tested). Harbor's agents take a model name and a provider key from the environment. The intended free setup is one of these (illustrative syntax, not yet checked):
```
# Gemini free tier (AI Studio key, no billing)
GEMINI_API_KEY=...   harbor run --agent <agent> --model gemini/<free-tier-model-id> ...
# OpenRouter free variant (no credit purchase)
OPENROUTER_API_KEY=... harbor run --agent <agent> --model openrouter/<model-id>:free ...
# Local Ollama
harbor run --agent <agent> --model ollama/gemma3:4b ...
```
Flag names and model-string format must be checked against Harbor's docs on the day. Run locally with Docker only. No Daytona, Modal or other cloud sandbox.

## 4. Recommended design

### 4.1 Stack (all free)

Python 3.12 or newer (the machine has 3.14; pin a version that all wheels support). One package, `taskfactory`, with an `argparse` CLI named `tf`.

| Need | Choice | Notes |
|---|---|---|
| Rendering | matplotlib (Agg), Pillow, numpy | Bundled DejaVu font, fixed DPI, PNG metadata stripped. |
| Config | TOML via stdlib `tomllib` | No extra dependency. |
| OCR read-back | Tesseract OCR via a thin subprocess wrapper | Record Tesseract version in every manifest. |
| Pixel reader, near-dup hash | OpenCV + numpy | pHash written in about 20 lines with OpenCV DCT. |
| Tests | pytest | Includes the validator self-test. |
| Model calls | stdlib HTTP in one module `llm.py`, 3 providers | Gemini REST, OpenRouter (OpenAI-compatible REST), Ollama local REST. |
| Storage | Plain files + JSONL | No database. |
| Report | stdlib `string.Template` to static HTML, charts as PNG | Hosted on GitHub Pages from a `gh-pages` branch. |
| Pinning | `pyproject.toml` + lockfile | Reproducible install. |

No backend, no hosted database, no auth, no queue, no web server.

Model roles, kept in `configs/models.toml` with exact IDs and the date each was checked:

| Role | Model | Provider | Notes |
|---|---|---|---|
| Evaluated | best free-tier Gemini Flash-class model on build day (candidates: 3 Flash Preview, 3.1 Flash-Lite, 3.5 Flash-Lite) | Google AI Studio free tier | Not 2.5 Pro or 2.5 Flash (routed elsewhere from 1 Dec 2026). |
| Evaluated | a second Gemini free-tier model from the same list | Google AI Studio free tier | Gives a size or version contrast. |
| Evaluated | NVIDIA Nemotron 3.5 Super VL, ID ending `:free` | OpenRouter | Alternates: Ling 3.2 Flash, Nemotron 3 Nano Omni (`:free`). Not Span-01 Lite. |
| Secondary validator only | Gemma 3 4B (`gemma3:4b`) | Ollama, local CPU | Excluded from the evaluated set. Its checks are labelled secondary and never decide validity. |

Data note: free-tier Gemini prompts may be used to improve Google products. That is acceptable because every image and question is synthetic. We send nothing else.

### 4.2 Pipeline

```
 configs/*.toml
      |
 [1 sample]    seed = H(run_seed, family, domain, index) -> spec.json
 [2 render]    family renderer -> image.png + text_boxes.json
 [3 ask]       question template + answer from spec -> task.json   (ground truth)
 [4 validate]  deterministic checks 1-7 (local, no model)
               secondary: S1 local Gemma text-only check (labelled, non-blocking)
 [5 score]     variation metrics + near-duplicate filter (batch)
 [6 package]   manifest.json + tasks.jsonl index
 [7 evaluate]  ~200 stratified valid tasks per evaluated model, resumable, cached
 [8 report]    report.html + metrics.json -> GitHub Pages
```

Stages 1 to 6 and 8 are local and need no network. Stage 7 is the only one that calls free APIs. Each stage runs alone (`tf generate`, `tf validate`, `tf score`, `tf eval`, `tf report`) or together (`tf run`). `tf diff runA runB` compares manifests.

Families (renderer code): `bar` (vertical, horizontal), `line` (multi-series), `floorplan` (labelled rooms with areas). Domains (config only): for example tourism by country, retail sales by product, energy by month, house plans.

| Question type | Example | Reasoning steps | Answer printed as |
|---|---|---|---|
| value_lookup | "What value is shown for Spain?" | 1 | data label |
| extremum | "Which country has the most arrivals?" | n | category label |
| rank_k | "Which product ranks third by sales?" | n log n | category label |
| pair_compare | "Which is higher, March or July?" | 2 | category label |
| series_at_x | "Which series is highest in 2021?" | k | legend label |
| spatial (floorplan) | "Which room is directly north of the kitchen?" | 2 | room label |

Structural knobs: category count, series count, sorted or shuffled, label rotation, log scale, orientation, distractor series, room count. Cosmetic knobs (palette, font size within a band, grid) are tracked but not counted as variation.

### 4.3 One task package

```
out/<run_id>/tasks/bar-tourism-000123/
  image.png            rendered image
  spec.json            data + render params + seed
  text_boxes.json      every rendered string with its pixel bbox
  task.json            question, answer (ground truth), type, family, domain, steps
  validation.json      each check: pass/fail, details, tool versions
  counterfactual.png   re-render with altered data
  manifest.json        sha256 of each file, config hash, git sha, package + Tesseract versions
out/<run_id>/tasks.jsonl  validation.jsonl  metrics.json  report.html  rejected/  overrides.log
eval/<model_id>/responses.jsonl   append-only, one line per (task_id, prompt_hash)
```

Manual changes go through `overrides/<task_id>.toml` with a reason and reviewer, and are listed in the report.

### 4.4 Config sketch

```toml
# configs/runs/demo.toml
run_seed = 20261206
tasks_per_cell = 6
question_in_image = true
families = ["bar", "line", "floorplan"]
domains  = ["tourism", "retail", "energy"]
question_types = ["value_lookup", "extremum", "rank_k", "pair_compare", "series_at_x", "spatial"]

[checks]
ambiguity_min_margin = 0.05
min_font_px = 9
near_dup_phash_max = 6

[eval]
items_per_model = 200
stratify_by = ["family", "question_type"]
models = "configs/models.toml"

# configs/domains/tourism.toml
title = "International tourist arrivals ({year})"
categories = ["France", "Spain", "Italy", "Japan", "Mexico", "Thailand", "Turkey", "Germany"]
value_range = [2_000_000, 90_000_000]
value_format = "{:.1f}M"
families = ["bar", "line"]
```

Adding a domain is one TOML file. Adding a family is one renderer module with `render(spec) -> (png, text_boxes)` plus a pixel-reader module. We show the domain case live.

### 4.5 Repeatability

- Per-task seed is a hash of (run seed, family, domain, index). Adding a family does not shift other tasks.
- PNG bytes are deterministic on one machine. (UNCERTAIN across OSes: if bytes differ, `tf diff` falls back to spec hash + pixel threshold and says so.)
- All model responses go to append-only JSONL keyed by (model ID, prompt hash, image hash), with temperature 0. `tf eval` resumes where it stopped. `tf run --offline` replays from the files, so judges need no account or key.
- Ollama model digest and Tesseract version are recorded in manifests.
- `tf diff` prints changed, added and removed files. Demo target: 0 changed.

### 4.6 Validation (independent of evaluated models)

Reference answers come only from generator ground truth. No evaluated model ever validates a task, and benchmark results never change a task's label.

Why each task needs the image: the values and positions are random synthetic data that exists only in the image, so the answer cannot come from the question text or from prior knowledge. The answer-position test shows that guessing is at chance. S1 measures text-only success on the pool.

| # | Check | Pass rule |
|---|---|---|
| 1 | Schema | task.json and spec.json match schema; answer type fits question type |
| 2 | Layout and geometry | text bboxes inside canvas, no label overlaps, font >= min px |
| 3 | Ambiguity | unique answer: margin >= threshold, no two printed (rounded) labels equal, no ties |
| 4 | OCR read-back | Tesseract finds the answer string and every entity named in the question |
| 5 | Pixel reader | OpenCV finds bars, line points or room rectangles by colour and contour, pairs them with OCR labels, recomputes the answer from pixels; must equal ground truth |
| 6 | Counterfactual re-render | data altered so the true answer must change; re-render; pixel reader must return the new answer |
| 7 | Re-render determinism | rendering the same spec twice gives the same hash |
| S1 | Secondary: text-only necessity | local Gemma 3 4B sees the question without the image; logged, non-blocking |

Batch-level evidence:
- Funnel: generated, pass count after each check, final valid yield.
- Answer-position test (deterministic): the answer is uniformly spread over candidate positions, so guessing without the image is at chance. Chi-square result in the report.
- Validator self-test (pytest): inject known defects (wrong answer, hidden label, forced tie, absent entity, mismatched bar) into 10% of a run. Report catch rate per defect class.
- Human audit: 50 random valid tasks, 2 reviewers. Report error rate with Wilson 95% CI and inter-rater agreement.

### 4.7 Benchmark sized to free quotas

- Pool: about 500 tasks, generated and validated locally at no cost.
- Eval set: about 200 valid tasks per evaluated model, stratified by family x question type. The same 200 for every model.
- OpenRouter: 50 requests a day in total without purchase, so one model x 200 items takes about 4 days at the cap. Start once the 200-item set is frozen (task PL2). A second OpenRouter model is stretch, only if time allows before submission.
- Gemini: per-model free limits are not verified. Before any Gemini run (task SU5) we read the limits page, write them into `models.toml`, and `tf eval` throttles to them. If daily limits are low, spread runs over several days or cut to 150 items.
- Report: accuracy by model x question type, with exact model IDs and the dates they were called. We describe them as "the best free-tier multimodal models available on build day".
- Grading is deterministic: a normalised string match against the ground truth. No model grades another model's answer.
- Error analysis, for strengths and weaknesses: each wrong answer gets one error label (wrong entity, adjacent or rank confusion, series confusion, right entity with a wrong number, format error or refusal). The report breaks errors down by family, question type and structural knob (for example, accuracy against category count), and shows five annotated failures per model.

### 4.8 Variation in numbers

| Metric | Definition | MVP target |
|---|---|---|
| Cell coverage | share of feasible (family x domain x question type) cells with >= 5 valid tasks | >= 90% |
| Question-type balance | normalised Shannon entropy of question types | >= 0.9 |
| Structural difference | share of nearest-neighbour pairs (by pHash) differing in >= 1 structural knob | >= 95% |
| Near-duplicate rate | pHash distance <= 6 or identical rounded spec; removed before packaging | 0 after filter; report count removed |
| Reasoning depth | histogram of reasoning steps | >= 3 bins with >= 15% each |
| Difficulty spread | benchmark accuracy range across question types | >= 20 points |

Targets are goals, not results. The report prints actual values.

### 4.9 Originality: the two ideas to remember

1. **Two-path agreement.** The generator knows the answer from the data. A separate pixel reader recomputes it from the image alone. A task is valid only when both paths agree. No model is involved.
2. **Counterfactual re-render.** The Track 2 version of the organisers' "remove the feature, the test must fail". We change the data so the answer must change, re-render, and require the pixel reader to follow.

Supporting: validator self-test with injected defects; ambiguity guard on printed labels; a whole factory at zero service cost.

### 4.10 Guardrails

The organisers have not answered the security and performance question. Our rules for Track 2:
- Synthetic data only. A "Synthetic data" footer on every image.
- No people, faces, medical dosing, political or election data. All domain vocabulary passes `configs/blocklist.txt`; `tf run` refuses a config that fails.
- Only synthetic images and questions are sent to free-tier APIs.
- Track 1 fallback: no tasks touching auth, crypto, sandboxing, network exploits or malware. Path denylist on ablatable units, keyword screen on requirement text, tests run in a local container with no network and a timeout.

## 5. Scope

Tags: R = repeatable, V = validity, Var = variation, O = originality, C = communication.

| MVP (by 6 Dec) | Tag |
|---|---|
| CLI: generate, validate, score, eval, report, run, diff | R |
| Stable seeds, lockfile, JSONL cache, `--offline`, resumable eval | R |
| Families bar, line, floorplan; 3 domains; 6 question types | Var |
| Checks 1 to 7 on all tasks; S1 on all if CPU time allows, else a sample | V, O |
| Pixel readers for all 3 families | V, O |
| Near-dup filter and variation metrics | Var |
| Validator self-test, 50-task human audit | V |
| Benchmark: 2 Gemini free models + 1 OpenRouter free model, about 200 items each | C, Var |
| Static report on GitHub Pages; README; deck; video; prototype brief | C |

| Stretch (after MVP, before 20 Dec) | Tag |
|---|---|
| Second OpenRouter free model (50 a day limit) | C |
| Fourth family (table or stacked bar), fifth domain | Var |
| Larger human audit (100 tasks) | V |
| CI regen check, only if confirmed free for public repos; else keep it as a local script | R |

| Cut | Why |
|---|---|
| Any paid API, credit purchase, paid cloud or sandbox | Binding free-stack rule. |
| Generative-model images | Ground truth not exact. Revisit only if the organisers require it. |
| Backend, hosted database, auth, web UI | No rubric point; not free-stack necessary. |
| Model-based validation that decides validity | Validation must stay independent of evaluated models. |
| Model paraphrase of questions | Would need extra free quota; templates carry 2 to 3 phrasings each. |

Team size:
- 1 person: drop floorplan (bar + line still proves reuse), benchmark 2 models, audit 30 tasks.
- 2 to 3 people: as written. A = sample, render, questions. B = checks, pixel readers, `llm.py`. C = report, variation, benchmark runs, deck, video (B covers C if only 2).
- 4 people: D owns the human audit, the self-test defect set, a fourth family and the deck. Stay on one track.

## 6. Task sequence (no calendar dates)

Work top to bottom. A task starts once everything in its **Needs** column is done. **You** means you do it. **Builder** means the AI assistant does it, delegating coding per your routing rule (Haiku 5.5 for high-level work, DeepSeek V4.1 Flash 1017 for low-level work, both at max effort). The Builder checks each result before marking a task done.

Done today, per you: event checked on the dashboard, team or solo set up, Track 2 confirmed, organisers emailed.

Rules:
- A "You" task that blocks others does not stop the Builder. Everything that doesn't depend on it keeps going.
- A task is done only when its "Done when" check passes and is recorded here.
- If time runs short, cut in this order: SC5 (floor plan), then BM2 (second Gemini model), then AR1 drops to 30 tasks. Never cut the checks, the report or the submission steps.

### Setup

| ID | Task | Needs | Owner | Done when |
|---|---|---|---|---|
| SU1 | Create a Google AI Studio API key with no billing linked | none | You | A test request to one free Gemini model returns text |
| SU2 | Create an OpenRouter account, no credit purchase | none | You | A test request to a `:free` vision model returns text |
| SU3 | Install Tesseract OCR and Ollama; pull `gemma3:4b` | none | You | `tesseract --version` and `ollama run gemma3:4b` both work |
| SU4 | Settle the Python version: 3.12 (recommended) or accept 3.14 | none | You | Version written into `pyproject.toml` |
| SU5 | Record exact model IDs, limits and check date in `configs/models.toml` | SU1, SU2 | Builder | Each model has its ID and limits, or "unknown" with a reason |
| SU6 | Time one Gemma 3 4B call on this CPU | SU3 | Builder | Latency recorded; decides whether the local check runs on all items or a sample |

### Core build

| ID | Task | Needs | Owner | Done when |
|---|---|---|---|---|
| CB1 | Repo skeleton: `pyproject.toml`, `taskfactory/` package, `tf` command stub, tests folder, `.gitignore` | SU4 | Builder | `tf --help` runs; `pytest` passes an empty test |
| CB2 | Lockfile and a clean-install check | CB1 | Builder | A fresh virtual environment installs from the lockfile and runs `tf --help` |
| CB3 | Config loader for run, domain and family files, with the blocklist check | CB1 | Builder | A bad config is refused with a reason (test) |
| CB4 | `llm.py` model client: three providers, JSONL cache, resume, throttling | CB1 (live calls also need SU1–SU3) | Builder | Offline test replays a stored response; a live test call works for each provider |

### Factory

| ID | Task | Needs | Owner | Done when |
|---|---|---|---|---|
| FA1 | Seeded sampler: per-task seed from run seed, family, domain and index | CB3 | Builder | Same seed gives the same spec; adding a family leaves other tasks unchanged (test) |
| FA2 | Bar renderer with text boxes and synthetic footer | FA1 | Builder | Same spec gives the same PNG hash on this machine; text boxes saved |
| FA3 | Question templates for value_lookup and extremum; answer taken from the spec | FA2 | Builder | Each `task.json` answer matches the spec (test) |
| FA4 | Task package writer and manifest (hashes, tool versions) | FA3 | Builder | Package matches the layout in section 4.3 |
| FA5 | `tf diff` command | FA4 | Builder | Regenerating a run gives zero changed files |

### Checks

| ID | Task | Needs | Owner | Done when |
|---|---|---|---|---|
| CK1 | Checks 1, 2, 3 and 7: schema, layout, ambiguity, re-render determinism | FA4 | Builder | Each check has a passing and a failing test |
| CK2 | OCR read-back (check 4) | CK1, SU3 | Builder | Tesseract finds the answer on a sample of bar charts; every miss is logged |
| CK3 | Bar pixel reader (check 5) | FA2 | Builder | Recomputes answers from pixels on a clean sample; every miss is logged with a reason |
| CK4 | Counterfactual re-render (check 6) | CK3 | Builder | Changing the data changes the answer, and the reader follows |

### Gate

| ID | Task | Needs | Owner | Done when |
|---|---|---|---|---|
| G1 | Get the organisers' answers: is code-drawn imagery allowed, and must the question text be printed in the image | Email sent (done) | You | Answers recorded in section 10. Until then, only the bar pipeline is built. If code-drawn images are refused, switch to Track 1 |

### Scaling up

| ID | Task | Needs | Owner | Done when |
|---|---|---|---|---|
| SC1 | Line renderer and series_at_x questions | CK4, G1 | Builder | Checks pass on a sample |
| SC2 | Line pixel reader | SC1 | Builder | Same standard as CK3 |
| SC3 | Near-duplicate filter (pHash) and variation metrics | CK4 | Builder | `metrics.json` written |
| SC4 | Two more domains (config files only) | FA3 | Builder | Both run through the pipeline with no code changes |
| SC5 | Floor plan renderer, spatial questions and reader | SC2, G1 | Builder | Checks pass on a sample (solo: drop this task) |
| SC6 | Validator self-test: plant known defects, measure the catch rate | CK1–CK4 | Builder | Catch rate reported per defect class |

### Pool and evaluation set

| ID | Task | Needs | Owner | Done when |
|---|---|---|---|---|
| PL1 | Full pool run (about 500 tasks), offline | SC1–SC4, SC6, and SC5 unless solo | Builder | Funnel and yield recorded |
| PL2 | Freeze the 200-item evaluation set, stratified by family and question type | PL1 | Builder | Frozen list with hashes |

### Benchmark

| ID | Task | Needs | Owner | Done when |
|---|---|---|---|---|
| BM1 | Gemini model 1 on the 200 items, cached and throttled to its limits | PL2, SU5 | Builder | 200 answers stored |
| BM2 | Gemini model 2 on the same 200 items | PL2, SU5 | Builder | 200 answers stored |
| BM3 | OpenRouter vision model on the same 200 items, 50 a day | PL2, SU2 | Builder | 200 answers stored. Takes about 4 days at the cap and resumes after each stop |
| BM4 | Deterministic grading; one error label per wrong answer | BM1, BM3 (and BM2 if run) | Builder | Every wrong answer has one label |
| BM5 | Error analysis by family, question type and structural knob; five annotated failures per model | BM4 | Builder | Tables and failure examples ready for the report |

### Audit and report

| ID | Task | Needs | Owner | Done when |
|---|---|---|---|---|
| AR1 | Human audit: 50 random valid tasks, two reviewers (solo: 30 tasks) | PL1 | You | Error rate with 95% CI and agreement recorded |
| AR2 | Report v1: static HTML and `metrics.json`, partial results allowed | CK1, PL1 | Builder | Opens from a local file |
| AR3 | Report v2: benchmark and audit results added | BM5, AR1 | Builder | Every number shows its model ID and check date |

### Freeze and submission

| ID | Task | Needs | Owner | Done when |
|---|---|---|---|---|
| FZ1 | Feature freeze: final run from config; commit manifests and caches (the Builder asks before committing) | AR3 | Builder; you approve | `tf diff` against the frozen run shows zero changes |
| FZ2 | Fresh-clone test with `--offline`, in a clean folder or on another machine | FZ1 | Builder runs it; you check | Report reproduced with no API keys |
| SB1 | README quickstart and prototype brief (technologies; service cost 0) | FZ2 | Builder | Brief matches section 7 |
| SB2 | Publish the report on GitHub Pages from the public repo | FZ1 | You | Report link opens |
| SB3 | Deck on the mandatory Google Slides template; export .pptx | AR3 | You; Builder drafts text | .pptx exported |
| SB4 | Demo video in OBS, 3 to 5 minutes, following section 8 | FZ1, SB2 | You | Video ready |
| SB5 | Submit everything in the portal; check it on the dashboard | SB1–SB4 | You | Submission visible on the dashboard |

### Demo prep (after finalists are announced)

| ID | Task | Needs | Owner | Done when |
|---|---|---|---|---|
| DM1 | Offline demo script, following section 8 | FZ2 | Builder | Runs end to end offline |
| DM2 | Pre-recorded fallback video of the same sequence | DM1 | You | Video saved locally and linked on the report page |
| DM3 | Three full rehearsals | DM1 | You | Each run completes offline |

**Fixed external dates** (not scheduled by us): the portal closes 6 Dec, so SB5 must finish before then. Finalists are announced 7–14 Dec. Mentor connect starts 15 Dec. Demo day is 20 Dec.

## 7. Submission checklist

- [ ] Public GitHub repo: README quickstart, lockfile, manifests, JSONL caches, one sample run.
- [ ] Report live on GitHub Pages.
- [ ] Demo video link, 3 to 5 minutes, recorded with OBS Studio, mirrors section 8.
- [ ] PPT on the mandatory template from the Submission tab (edited in Google Slides, exported as .pptx).
- [ ] Prototype brief with the technology list below. Estimated service cost: 0.
- [ ] Track 2 selected in the portal. All members listed on the dashboard before team formation closes (about 6 Dec, UNCERTAIN).
- [ ] Source, docs, working prototype and demo all submitted.

Technology list for the brief: Python, matplotlib, Pillow, numpy, OpenCV, pytest, Tesseract OCR; Google AI Studio free tier (Gemini API, no billing); OpenRouter `:free` models (no credit purchase); Ollama with Gemma 3 4B (local); plain files + JSONL; static HTML on GitHub Pages; Mermaid or draw.io for diagrams; OBS Studio; Google Slides. Free tiers and open source only. Estimated service cost: 0.

## 8. Demo-day script (about 4 minutes)

| Time | Show | Evidence |
|---|---|---|
| 0:00 | One slide: config in, task packages out; 7 checks; cost 0. | C |
| 0:20 | `demo.toml` and one domain file. `tf run --offline --n 30`. | R |
| 0:50 | One package: image, question, answer, validation.json. | V |
| 1:30 | Report: funnel, self-test catch rates, audit with CI. | V |
| 2:10 | A task the pixel reader rejected; a counterfactual pair. | O |
| 2:40 | Variation tab: heatmap, structural-difference rate. Benchmark by type with model IDs and dates. | Var, C |
| 3:10 | Delete output, regenerate, `tf diff`: 0 changed. | R |
| 3:30 | New domain by editing 4 lines of TOML; run; new tasks appear. | R |
| 3:50 | Close: yield, accuracy spread, use cases. | C |

Fallback: pre-recorded OBS capture of the same sequence, plus the GitHub Pages report and a local copy. Every live step runs offline.

## 9. Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | Organisers require generative-model images. | Ask now. Gate G1 before the line renderer and the full pool. Shared core allows a Track 1 switch. |
| 2 | "Question visible in image" means printed question text. | `question_in_image` flag. |
| 3 | Gemini free limits are too low, or a preview model is withdrawn. | Read limits in task SU5; resumable eval; record IDs and dates; swap to another listed free model. |
| 4 | OpenRouter 50 a day total is too slow. | One model, about 4 days at the cap; second model is stretch. |
| 5 | Pixel reader is brittle and rejects good tasks. | Controlled palette and layout; report reader coverage; self-test both ways. |
| 6 | Gemma 3 4B too slow on CPU. | S1 is secondary; run it on a sample. |
| 7 | Tesseract misreads small or rotated text. | Min font rule; fixed rendering font; tune page segmentation mode. |
| 8 | Team forms late or a member drops out. | Form team now; cuts by team size in section 5. |

## 10. Open questions and user decisions

Email to organisers (verify the support address on the dashboard; the caption is garbled):
1. May Track 2 images be rendered by code, or must they come from a generative image model?
2. Does "the question must be visible in the image" mean printed question text, or only reference to visible content?
3. Is there a Track 2 task-package template or required fields?
4. What is the exact team-formation close date?
5. Is there a minimum number of tasks or image families expected?
6. What content restrictions apply (security, sensitive domains)?
7. Are AI model credits offered, and on what terms? (Optional only. The plan does not depend on them.)

Decisions the user must make:
- Confirm Track 2 (assumed done today; say if not). Decide the fallback if the organisers refuse code-drawn images (gate G1).
- Team size, and who owns roles A, B, C.
- Who creates the free AI Studio and OpenRouter accounts (no billing, no purchase), and accept that free-tier Gemini prompts may be used by Google (synthetic data only).
- Which machine runs Ollama, and the Python version to pin.

### Defaults chosen (organiser answers not received; we build on these and change them only if the organisers say otherwise)

1. **Code-drawn images:** allowed. They give exact ground truth, are repeatable and cost nothing. No generative image model in the MVP.
2. **Question text in the image:** on by default (`question_in_image = true`). It costs one caption strip and removes the literal-reading risk. The answer stays printed.
3. **Team formation:** assumed to close around 6 Dec. We stay ahead of it anyway.
4. **Content:** synthetic data only, with a "Synthetic data" footer. No people, faces, medical, political or election content. The config loader enforces the blocklist.
5. **Minimum size:** none given, so we target the MVP pool (about 500 tasks, 3 families, 3 domains) and the 200-item evaluation set.
6. **Task-package format:** our own layout (section 4.3). We adapt when the organisers publish a template.
7. **Organiser model credits:** not used. Everything runs on free tiers.
8. **Team:** assumed solo, so the solo cut in section 5 applies. Tell us if this is wrong.
9. **Python:** 3.14.6, as chosen. Verified 19 Nov: numpy, pillow, matplotlib, opencv-python-headless, pytesseract and pytest all install and import on it.

### Free-stack check

"Checked 19 Nov" means verified from the provider's page that day. "Known" means a well-established licence or policy that we did not re-check today.

| Component | Free option | Billing needed | How checked | Residual risk |
|---|---|---|---|---|
| Gemini API | Google AI Studio free tier | No | Checked 19 Nov: AI Studio billing page | Per-model limits unverified; prompts may be used by Google; previews can change |
| OpenRouter | `:free` model variants | No | Checked 19 Nov: free collection page and limits | 50 a day total; IDs and vision support to confirm on the day |
| Local model | Ollama + Gemma 3 4B | No | Checked 19 Nov: Ollama repo MIT; Gemma 3 vision at 4B, 12B, 27B | CPU speed untested; Gemma licence terms not reviewed here |
| Track 1 harness | Harbor, local Docker | No | Checked 19 Nov: Apache-2.0 | Free-model config UNVERIFIED |
| Containers | Docker Engine in WSL2 | No | Known: free and open source | Docker Desktop terms not checked; we do not rely on Desktop |
| Hosting | GitHub Pages (public repo) | No | Known | None known |
| Repo | Public GitHub repo | No | Required by hackathon | None known |
| CI (stretch) | GitHub Actions on public repo | No | Not checked | Use only if confirmed; else local script |
| Libraries | Python, matplotlib, Pillow, numpy, OpenCV, pytest | No | Known licences | Wheel support on Python 3.14 to check |
| OCR | Tesseract OCR | No | Known licence (Apache-2.0) | Windows install path to check |
| Storage, DB | Plain files + JSONL | No | No service | None |
| Video, slides, diagrams | OBS Studio, Google Slides, Mermaid or draw.io | No | Known free tools | Template must open cleanly in Google Slides |

### Excluded

| Item | Reason |
|---|---|
| Claude API | No free API tier stated on the pricing page; API credits appear only with paid plans. Excluded either way. |
| Claude Code | Paid subscription. |
| Groq | Free-plan terms not confirmed; do not rely on it. |
| Any paid API key or credit purchase (incl. OpenRouter $10 for 1,000 a day) | Binding free-stack rule. |
| Google Cloud Free Trial or linked billing | Requires billing information. |
| Ollama Cloud | Cost not stated. |
| Cloud sandboxes (Daytona, Modal and others) | Pricing not stated. |
| OpenRouter Span-01 Lite | May need a funded account. |
| Gemini 2.5 Pro and 2.5 Flash | Route to other models from 1 Dec 2026. |
| Supabase, Firebase, hosted DB | Not needed. |
| Organiser AI model credits as a dependency | Unconfirmed; optional only. |

## 11. Facts relied on and their sources

Event facts are from the source brief (session auto-captions and video description; slides not seen). Free-stack facts were checked on 2026-11-19 from provider pages.

| Fact | Confidence |
|---|---|
| Weights 25 / 25 / 20 / 15 / 15 | High (sum checked) |
| Submission closes 6 Dec; finalists 7 to 14 Dec; mentor connect from 15 Dec; demo day 20 Dec | High |
| Team size 1 to 4 | High |
| Deliverables: brief with technologies, public repo, demo video, PPT on mandatory template; "submit them all" | High |
| Track 2: question and answer must be present in the image | Medium: "question visible" is ambiguous |
| Programmatic images allowed | UNCERTAIN |
| Team-formation close about 6 Dec | UNCERTAIN |
| Model credits exist and their timing | UNCERTAIN; not a dependency |
| Support mailbox address | UNCERTAIN (garbled) |
| AI Studio free tier needs no billing; listed vision models | Checked 19 Nov |
| Gemini per-model free rate limits | UNVERIFIED; read in task SU5 |
| OpenRouter free caps 20 a minute, 50 a day without purchase | Checked 19 Nov |
| Exact OpenRouter `:free` IDs for the three vision models | UNVERIFIED; confirm in task SU5 |
| Harbor running with a free model | UNVERIFIED |
| Gemma 3 4B latency on our CPU | UNVERIFIED |
| Byte-identical PNGs across OSes | UNCERTAIN |
| The Devpost "InnoData Hackathon" (Feb 2026) is a different event | Per brief; confirm on dashboard |
