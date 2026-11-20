# Deploying TaskFactory

Status: spike passed on 20 November 2026. Hosted on Vercel's Container
runtime (beta on all plans), Hobby plan, no billing details and no API keys.
The same container also serves the committed sample site, so there is one
deployment, not two.

## What the gate is

The gate is one real default request through the public form endpoint. It is
the 25 November stop/go check: if it fails, the live generator ships as Option
A (the static sample site) and generation stays on a laptop.

`scripts/spike_gate.py` talks to a running server with the standard library
only. It:

1. Calls `GET /api/health` and expects `status: ok`.
2. Calls `GET /api/version` and expects a commit value.
3. Posts the published defaults to `/api/generate`:
   seed `20261206`, 3 charts per type, bar and line, tourism, all five
   question types, standard difficulty, question printed on the image.
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

## Vercel steps (owner)

1. Create a Vercel account with GitHub sign-in. Choose the Hobby plan. Do not
   add billing details or a paid plan.
2. Import the GitHub repository `0xPolybit/innodata-hackathon`.
3. Leave the project root at the repository root. `vercel.json` contains
   `{"framework": "container"}`, which selects the Container runtime and the
   root `Dockerfile`. Do not create a `Dockerfile.vercel`: it would take
   priority and hide the tested image.
4. Deploy. The build runs `uv sync --frozen --no-dev` and installs Tesseract
   from Debian. There is no build command or output directory to set.
5. The container reads `PORT` and binds `0.0.0.0`; the image defaults to 3000
   when `PORT` is absent.
6. After the deploy, check `/`, `/about`, `/sample/`, `/api/health` and
   `/api/version`, then submit the untouched form once and confirm 14
   attempted, every accepted task 7/7, and a ZIP download.
7. Add no environment variables and no keys. The hosted app calls no model.
   `.dockerignore` excludes `.env` and every `.env.*` file, so a key cannot
   enter the image.
8. Hobby is for non-commercial use. This deployment is a hackathon demo: no
   ads, payments, or commercial service.

The Container runtime is in beta. Project settings and limits can change; if
Vercel rejects the configuration, use the fallback below rather than fighting
it during the deadline.

## If the container fails

A build or runtime failure is a stop signal for the container path, not a
reason to guess. Record the exact error first. Then:

1. Restore the static configuration in `vercel.json` exactly as it was:

   ```json
   {"outputDirectory": "site", "cleanUrls": true}
   ```

2. Commit and redeploy. This serves the committed sample report only:
   `/` is the static landing page and `/sample/` is the saved run. The form
   and the live generator are unavailable, and the landing page already says
   the live generator is coming.
3. Keep the generator available on a laptop with `tf serve`, and show that in
   the video. The local command is in the README.
4. If the failure is only a missing system package or Tesseract, fix the
   `apt-get install` line in the `Dockerfile`, rebuild, and rerun the gate
   before changing the deployment.

Do not keep two Vercel projects. One URL is either the container app or the
static sample site.
