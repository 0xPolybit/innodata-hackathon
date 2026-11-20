# Deploying TaskFactory

Status: the container gate passed on 20 November 2026. The hosted app runs on
Vercel's Container runtime (beta on all plans), Hobby plan, with no billing
details and no API keys. One deployment serves the form, the generator, the
status routes and the committed sample site.

## What the app serves

| Route | Method | What it is |
|---|---|---|
| `/` | GET | The form page. It says "About 15 tasks" from the form's own count. |
| `/about` | GET | The static landing page from `site/index.html`. |
| `/sample/` | GET | The committed sample report from `site/sample/`. |
| `/api/generate` | POST | Validates the form, generates and checks the tasks, returns the results page with inline charts. |
| `/api/zip` | POST | Runs the same form again and returns the ZIP attachment. Nothing is stored. |
| `/api/health` | GET | `{"status": "ok", "python": "<version>"}`. |
| `/api/version` | GET | The package version and the commit. The commit comes from `VERCEL_GIT_COMMIT_SHA`, then git, then `unknown`. |

`/sample` without the trailing slash redirects to `/sample/`. An unknown route
is a JSON 404. A wrong method on a known route is a JSON 405. A request body
over 4096 bytes is a 413 page. Only one generation runs at a time; a second
request while one is running gets a 503 page with `Retry-After: 60`.

## Failure messages

These are the exact messages a visitor sees. The user-facing text lives in one
constant per message in `src/taskfactory/web/`.

| Failure | What the visitor sees |
|---|---|
| Timeout | "Generation took longer than the 300 second limit. Choose fewer charts and try again. The sample report still works." |
| Out of memory | "The generator ran out of memory. Choose fewer charts and try again." |
| Request body too large | "Your request is too large. Reload the form and choose fewer charts." |
| Response or ZIP too large | "The result is too large to send. Choose fewer charts, or open the sample report." |
| Monthly compute limit | "The free monthly compute limit for this demo is used up. Try again next month, or run the app locally. The sample report is still available." |
| Bad seed | "Seed must be a whole number between 1 and 2147483647." |
| Bad chart count | "Charts per type must be between 1 and 6." |
| Too many tasks | "This choice makes 30 tasks; the limit is 24. Choose fewer charts or question types." |
| No chart type or question type | "Pick at least one chart type and one question type." |
| Cold start | "Starting the demo. The first request can take up to 60 seconds." This is a normal note in the form footer, not an error. |

The app has a `GenerationQuotaExceeded` error and a 503 page for the monthly
compute message, but nothing reads the Vercel quota and no code path raises
that error today. In practice, when the free monthly compute is used up,
Vercel's own platform error page is what a visitor sees, not this app. The
message is documented here so the wording is fixed if a quota signal is added.

The timeout is worth explaining. Vercel refuses a request at 300 seconds. The
app stops waiting at 280 seconds (`TIMEOUT_SECONDS` in
`src/taskfactory/web/generate.py`), so it still has time to send the page. The
message keeps the plan's 300-second wording. The run itself is not killed:
Python cannot stop a thread, so the worker keeps the single-generation lock
and the temporary folder cleanup until it finishes. Its result is discarded.
A visitor can try again only after that worker ends; until then the app answers
503 "busy".

The build-time fallback text, "The live generator is offline. You are viewing
the committed sample report.", belongs to the static site only. It is not in
the app and must not be added there.

## Cold start

A cold start is the first request after the demo has been idle. Vercel has to
start the container, then Python, matplotlib, OpenCV and Tesseract load before
the form can answer. The form tells the visitor this can take up to 60 seconds.
That figure is the plan's estimate and is **UNVERIFIED**: the gate measured a
warm request, not a cold one.

## Vercel steps (owner)

1. Create a Vercel account with GitHub sign-in. Choose the Hobby plan. Do not
   add billing details or a paid plan.
2. Import the GitHub repository `0xPolybit/innodata-hackathon`.
3. Leave the project root at the repository root. `vercel.json` contains
   `{"framework": "container"}`, which selects the Container runtime and the
   root `Dockerfile`. Do not create a `Dockerfile.vercel`: it would take
   priority and hide the tested image.
4. Deploy. The build runs `uv sync --frozen --no-dev` and installs Tesseract
   from Debian. There is no build command and no output directory to set.
5. The container reads `PORT` and binds `0.0.0.0`; the image defaults to 3000
   when `PORT` is absent.
6. After the deploy, check `/`, `/about`, `/sample/`, `/api/health` and
   `/api/version`, then submit the untouched form once. Confirm the results
   page, every accepted task at 7/7 checks, and a ZIP download.
7. Add no environment variables and no keys. The hosted app calls no model.
   `.dockerignore` excludes `.env` and every `.env.*` file, so a key cannot
   enter the image.
8. Hobby is for non-commercial use. This deployment is a hackathon demo: no
   ads, payments or commercial service.

The Container runtime is in beta. Project settings and limits can change; if
Vercel rejects the configuration, use the fallback rather than fighting it
during the deadline.

## If the container fails

A build or runtime failure is a stop signal for the container path, not a
reason to guess. Record the exact error first. Then:

1. Restore the static configuration in `vercel.json` exactly as it was:

   ```json
   {"outputDirectory": "site", "cleanUrls": true}
   ```

2. Remove the `Dockerfile` from the deploy: delete it, or move it out of the
   branch being deployed. A container file left in place keeps the build on
   the wrong path.
3. Commit and redeploy. This serves the committed sample report only: `/` is
   the static landing page and `/sample/` is the saved run. The form and the
   live generator are unavailable.
4. Keep the generator available on a laptop with `tf serve`, and show that in
   the video. The local command is in the README.
5. If the failure is only a missing system package or Tesseract, fix the
   `apt-get install` line in the `Dockerfile`, rebuild, and rerun the gate
   before changing the deployment.

Do not keep two Vercel projects. One URL is either the container app or the
static sample site.

## Local commands

Needs Docker Desktop with the engine running. From the repository root:

```powershell
docker build -t taskfactory:spike .

docker run -d --name tf-spike -p 3000:3000 -e PORT=3000 taskfactory:spike

python scripts/spike_gate.py --base http://127.0.0.1:3000

docker stop tf-spike
docker rm tf-spike
```

The gate prints JSON and exits 0 on success, 1 on any failure. Do not leave the
container running.

Useful manual checks while it runs:

```powershell
curl.exe -s -o NUL -w "%{http_code} %{content_type}`n" http://127.0.0.1:3000/
curl.exe -s -o NUL -w "%{http_code} %{content_type}`n" http://127.0.0.1:3000/about
curl.exe -s -o NUL -w "%{http_code} %{content_type}`n" http://127.0.0.1:3000/sample/
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:3000/api/health
```

The container has no `.git`, so locally `/api/version` shows
`"commit": "unknown"`. Vercel sets `VERCEL_GIT_COMMIT_SHA` for the hosted app.
To see the 40-character SHA locally, add it to the run command (PowerShell):

```powershell
$sha = git rev-parse HEAD
docker run -d --name tf-spike -p 3000:3000 -e PORT=3000 -e VERCEL_GIT_COMMIT_SHA=$sha taskfactory:spike
```

## What the gate is

The gate is one real default request through the public form endpoint. It is
the 25 November stop/go check: if it fails, the live generator ships as Option
A (the static sample site) and generation stays on a laptop.

`scripts/spike_gate.py` talks to a running server with the standard library
only. It:

1. Calls `GET /api/health` and expects `status: ok`.
2. Calls `GET /api/version` and expects a commit value.
3. Posts the published defaults to `/api/generate`: seed `20261206`, 3 charts
   per type, bar and line, tourism, all five question types, standard
   difficulty, question printed on the image.
4. Times the request with `time.perf_counter` and reads the whole body.
5. Counts the inline `data:image/png` charts and reads the Attempted, Accepted
   and Rejected numbers from the results page.
6. Checks every accepted card reports `7 of 7 checks passed`.
7. Checks for the words `gemini`, `openrouter` and `api_key` in the body.

The limits are: body under 4,500,000 bytes, elapsed under 180 seconds, at least
14 tasks attempted, and every attempted task passing 7/7 checks. It prints a
JSON summary and exits 0 only when every gate passes.

The plan says 15 tasks. The real pipeline attempts 14 at this seed (15
planned): the margin rule skips one planned task. That is why the gate is
"attempted at least 14 and every attempted task 7/7", not "exactly 15".

## Measured results, 20 November 2026

These are real numbers from the commands above on the build machine, not
targets.

| Item | Value |
|---|---|
| Base image | `python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90` |
| Image size | 841 MB (`taskfactory:spike`) |
| Build context | 61 files, about 915 KB; no `.env`, tests, samples, docs, audit, `.git`, `.venv` or `out` |
| Tesseract in image | 5.5.0, English data installed |
| Health | `{"status": "ok", "python": "3.13.18"}` |
| Version | `0.1.0`, commit `unknown` locally (no `.git`; Vercel supplies the SHA) |
| Attempted / accepted / rejected | 14 / 14 / 0 |
| Check result | 14 cards, each `7 of 7 checks passed` |
| Inline chart images | 14 |
| Response body | 968,203 bytes (limit 4,500,000) |
| Generation time | 9.6 seconds (limit 180) |
| Forbidden text | none of `gemini`, `openrouter`, `api_key` |
| Gate exit code | 0 |

Generation was warm: the server had already answered `/api/health`. A cold
first request may be slower; the gate's limit already leaves room for that.

## Known limits

- The default form plans 15 task slots. At the default seed the pipeline
  attempts 14 because the margin rule skips one; the page says so.
- Any choice above 24 planned tasks is refused.
- The hosted platform limit is 300 seconds per request. The app's own budget is
  280 seconds. A timed-out run cannot be killed; it holds the one-generation
  lock until it ends, and its result is discarded.
- A request body is capped at 4096 bytes, the results page at 4,000,000 bytes,
  and kept artifacts at 3,500,000 bytes. The platform's response limit is about
  4.5 MB.
- One generation per process. A second concurrent request gets 503 and should
  retry after a minute.
- The free monthly compute allowance is 4 CPU-hours. The app cannot read it;
  Vercel's platform page reports exhaustion.
- There is no per-IP rate limiting. The cap and the platform are the only
  limits.
- PNG bytes may differ across machines. JSON files, questions, answers and run
  IDs are deterministic for the same form, seed and commit.
- The Container runtime is in beta and Hobby is non-commercial.
- The hosted app calls no model and has no key field. Benchmarking stays local.
