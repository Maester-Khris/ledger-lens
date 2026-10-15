# Pre-launch P1 (frontend half): CORS and the Vercel frontend — Spec and Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This project:** Gemini executes Tasks 1 and 2 in order; Claude reviews at each **REVIEW CHECKPOINT** before the next task starts. Stop at every checkpoint and hand over: the commit hash, the test output, and `git status`. Task 3 is done by the operator (the user), not by Gemini.

**Goal:** Make the deployed frontend (Vercel, `https://ledgerlens.nknext.dev`) able to call the deployed
API (Railway, `https://ledger-lens-production-f77a.up.railway.app`) from a browser, including the streamed
chat answers and the pdf.js document viewer. This finishes the "direct calls with `VITE_API_BASE` + CORS"
part of backlog P1 (CORS is recorded under P3 in the changelog, but the deployed frontend cannot work
without it, so it is built here).

**Architecture:** One backend function adds FastAPI's built-in `CORSMiddleware` from a `FRONTEND_URL`
setting; one frontend helper normalises `VITE_API_BASE`. No new dependency, no new route, no schema change.

**Tech Stack:** FastAPI (Starlette `CORSMiddleware`, already installed); React (Vite) + TypeScript; pytest, vitest.

## Design (why it is built this way)

- **Direct cross-origin calls, not a Vercel rewrite.** Chosen in backlog P1: a rewrite may buffer the SSE
  chat stream. Consequence: every browser call from the Vercel origin to Railway is cross-origin, so the API
  must answer CORS preflights.
- **Which requests need a preflight.** The frontend sends `Content-Type: application/json`, `X-Guest-Id`
  (every call via `guestHeaders()`), and `Idempotency-Key` (ledger reversal). pdf.js loads the PDF with
  `getDocument({ url })`, which sends `Range` headers. All four are non-safelisted request headers, so all
  four must be in `allow_headers`, or the browser blocks the call before it leaves.
- **pdf.js range support.** pdf.js reads `Accept-Ranges`, `Content-Range` and `Content-Length` from the
  response; cross-origin these are hidden unless exposed, so they go in `expose_headers` (without them pdf.js
  still works by downloading the whole file, but exposing them keeps range loading on).
- **Methods.** The API uses only GET and POST (no PUT/PATCH/DELETE routes), so allow `GET, POST, OPTIONS`.
- **No credentials.** The API uses no cookies or auth headers, so `allow_credentials` stays off (the default).
  That also means `*` would technically work, but an explicit origin list is the safer default for a public API.
- **`FRONTEND_URL` is a comma-separated list of origins, each with its scheme and no trailing slash**
  (a browser's `Origin` header is exactly `https://host`). A trailing slash is stripped; a missing scheme
  **raises at startup**, so a typo fails the deploy loudly instead of silently blocking every browser call.
- **Unset means no middleware.** Local dev uses the Vite `/api` proxy (same origin), so with `FRONTEND_URL`
  unset nothing is installed and local behaviour is unchanged.
- **Only the production domain is allowed.** Vercel preview deployments get other origins and will be
  blocked. That is intended; add a preview URL to the comma-separated list if one is ever needed.
- **`VITE_API_BASE`** is baked into the bundle at build time. A trailing slash would produce `//documents`
  URLs, so the frontend strips trailing slashes. With the variable unset the default stays `/api` (local dev).

## Global Constraints

- Branch `feat/pre-launch-demo` (already checked out). Never commit to `main`/`preview`. Stage files
  explicitly (never `git add -A` or `git add .`). Conventional commits. **No AI co-author line.** Do not push.
- The working tree already contains an **uncommitted edit to `backend/app/config.py`** (the `.env.demo.local`
  loading at the top of the file). Keep it. It is committed together with Task 1, in the same commit.
- Do not touch `backend/.env`, `backend/.env.demo` or `backend/.env.demo.local` (local, gitignored, not part of this work).
- No new Python dependency and no new npm package.
- Python: type hints on every function signature. TypeScript: no `any`.
- Run backend commands as `/home/niki/Documents/workenv/pydev/bin/<tool>` from `backend/`. Never create a `.venv`.
- Routes stay thin and there is no direct DB access outside `dao.py`; this plan adds neither.

## Review Focus

1. **The preflight must allow exactly the four request headers the frontend sends** (`Content-Type`,
   `X-Guest-Id`, `Idempotency-Key`, `Range`). Check the test asserts all four, not just one.
2. **A disallowed origin must get no `Access-Control-Allow-Origin` header**, and the allowed origin must get
   exactly its own value back (not `*`).
3. **A bad `FRONTEND_URL` must raise, not be skipped.** `ledgerlens.nknext.dev` (no scheme) is the exact
   mistake already made once in `.env.demo`.
4. **Unset `FRONTEND_URL` must install nothing**, so local development is unchanged.
5. **The `config.py` commit contains both changes** (`FRONTEND_ORIGINS` and the `.env.demo.local` loading), and nothing else.

---

### Task 1: Backend CORS (`FRONTEND_URL` → middleware)

**Files:**
- Modify: `backend/app/config.py`, `backend/app/main.py`, `backend/.env.example`
- Create: `backend/tests/test_cors.py`

**Interfaces:**
- Produces: `config.parse_frontend_origins(raw: str | None) -> list[str]`, `config.FRONTEND_ORIGINS: list[str]`,
  `app.main.install_cors(app: FastAPI, origins: list[str]) -> None`.

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_cors.py` with exactly:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import parse_frontend_origins
from app.main import install_cors

ALLOWED = "https://ledgerlens.nknext.dev"
REQUEST_HEADERS = "content-type,x-guest-id,idempotency-key,range"


def make_client(origins: list[str]) -> TestClient:
    app = FastAPI()

    @app.get("/x")
    def x() -> dict[str, bool]:
        return {"ok": True}

    install_cors(app, origins)
    return TestClient(app)


def test_preflight_from_the_frontend_origin_allows_every_header_the_frontend_sends():
    response = make_client([ALLOWED]).options(
        "/x",
        headers={"Origin": ALLOWED, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": REQUEST_HEADERS},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED
    allowed = response.headers["access-control-allow-headers"].lower()
    for header in REQUEST_HEADERS.split(","):
        assert header in allowed


def test_preflight_from_another_origin_is_refused_without_an_allow_origin_header():
    response = make_client([ALLOWED]).options(
        "/x", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_simple_request_from_the_frontend_origin_gets_the_origin_and_exposed_headers():
    response = make_client([ALLOWED]).get("/x", headers={"Origin": ALLOWED})
    assert response.headers["access-control-allow-origin"] == ALLOWED
    exposed = response.headers["access-control-expose-headers"].lower()
    for header in ("accept-ranges", "content-range", "content-length"):
        assert header in exposed


def test_no_origins_installs_no_middleware():
    response = make_client([]).get("/x", headers={"Origin": ALLOWED})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_parse_splits_on_commas_and_strips_spaces_and_trailing_slashes():
    assert parse_frontend_origins(" https://a.dev/ , http://localhost:5173 ") == ["https://a.dev", "http://localhost:5173"]


@pytest.mark.parametrize("raw", [None, "", "  ", " , "])
def test_parse_returns_empty_when_unset_or_blank(raw):
    assert parse_frontend_origins(raw) == []


@pytest.mark.parametrize("raw", ["ledgerlens.nknext.dev", "https://a.dev,b.dev", "*"])
def test_parse_rejects_an_entry_without_a_scheme(raw):
    with pytest.raises(ValueError, match="scheme"):
        parse_frontend_origins(raw)
```

- [ ] **Step 2: Run them and confirm they fail** —
`/home/niki/Documents/workenv/pydev/bin/pytest tests/test_cors.py -q`. Expected: collection error
(`ImportError: cannot import name 'parse_frontend_origins'`).

- [ ] **Step 3: Add the setting to `backend/app/config.py`** — keep the existing edit at the top of the file.
Directly after the `PINECONE_TIMEOUT_SECONDS = ...` line, add:

```python
def parse_frontend_origins(raw: str | None) -> list[str]:
    """FRONTEND_URL: comma-separated browser origins allowed to call the API. A scheme is required."""
    origins = [part.strip().rstrip("/") for part in (raw or "").split(",") if part.strip()]
    for origin in origins:
        if not origin.startswith(("https://", "http://")):
            raise ValueError(f"FRONTEND_URL entry {origin!r} needs a scheme, e.g. https://example.com")
    return origins


# Unset (local dev uses the Vite /api proxy, same origin) means no CORS middleware is installed.
FRONTEND_ORIGINS = parse_frontend_origins(os.environ.get("FRONTEND_URL"))
```

- [ ] **Step 4: Wire the middleware in `backend/app/main.py`** — add two imports, one function, one call.

Imports (add next to the existing ones):
```python
from fastapi.middleware.cors import CORSMiddleware

from app import config
```

Function (add above `app = FastAPI(...)`):
```python
def install_cors(app: FastAPI, origins: list[str]) -> None:
    """Direct browser calls from the Vercel frontend. No origins configured means no middleware."""
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        # Content-Type/X-Guest-Id/Idempotency-Key are sent by api.ts; Range is sent by pdf.js.
        allow_headers=["Content-Type", "X-Guest-Id", "Idempotency-Key", "Range"],
        expose_headers=["Accept-Ranges", "Content-Range", "Content-Length", "ETag"],
        max_age=600,
    )
```

Call (add directly after `install_problem_handlers(app)`):
```python
install_cors(app, config.FRONTEND_ORIGINS)
```

- [ ] **Step 5: Document the variable** — in `backend/.env.example`, add after the `# --- Observability: Langfuse ---`
block (end of file) this block, with a blank line before it:

```
# --- Deployed frontend (CORS) ---
# Comma-separated browser origins allowed to call the API, each with its scheme and no trailing slash.
# Leave empty locally: the Vite /api proxy makes local calls same-origin. A value without a scheme stops the app at startup.
FRONTEND_URL=
```

- [ ] **Step 6: Run the tests and confirm they pass** —
`/home/niki/Documents/workenv/pydev/bin/pytest tests/test_cors.py -q` → all pass. Then the whole non-stress
suite: `/home/niki/Documents/workenv/pydev/bin/pytest -q` (needs the local Postgres container running; if it
is not, stop and report, do not skip). Expect no failures.

- [ ] **Step 7: Commit** — `git add backend/app/config.py backend/app/main.py backend/.env.example backend/tests/test_cors.py`,
then `git diff --staged --stat` (exactly those four files), then
`git commit -m "feat(api): allow the deployed frontend origin with CORS from FRONTEND_URL"`.

**REVIEW CHECKPOINT 1.** Hand over the commit hash, the `pytest tests/test_cors.py` and full-suite output, and `git status`.

---

### Task 2: Frontend `VITE_API_BASE` normalisation

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/api.test.ts`, `frontend/.env.example`

**Interfaces:**
- Produces: `normalizeApiBase(raw: string | undefined): string` exported from `frontend/src/api.ts`; `API_BASE` keeps its type and meaning.

- [ ] **Step 1: Write the failing test** — in `frontend/src/api.test.ts`, add `normalizeApiBase` to the existing
import from `./api`, and append at the end of the file:

```ts
it('defaults the API base to /api and strips trailing slashes', () => {
  expect(normalizeApiBase(undefined)).toBe('/api');
  expect(normalizeApiBase('https://api.example.com')).toBe('https://api.example.com');
  expect(normalizeApiBase('https://api.example.com/')).toBe('https://api.example.com');
  expect(normalizeApiBase('https://api.example.com//')).toBe('https://api.example.com');
});
```

- [ ] **Step 2: Run it and confirm it fails** — `cd frontend && npm test`. Expected: the new test fails
(`normalizeApiBase is not a function` or a TypeScript error).

- [ ] **Step 3: Implement** — in `frontend/src/api.ts`, replace line 1
(`export const API_BASE: string = import.meta.env.VITE_API_BASE ?? '/api';`) with:

```ts
// VITE_API_BASE is the deployed API origin (set in Vercel, baked in at build time); unset means the local Vite /api proxy.
export function normalizeApiBase(raw: string | undefined): string {
  return (raw ?? '/api').replace(/\/+$/, '');
}
export const API_BASE: string = normalizeApiBase(import.meta.env.VITE_API_BASE);
```

- [ ] **Step 4: Document the variable** — append to `frontend/.env.example` (keep the existing lines):

```
# The deployed API origin, scheme included, no trailing slash. Set this in Vercel; it is baked in at build time.
# Leave unset locally: the default /api goes through the Vite dev proxy.
VITE_API_BASE=
```

- [ ] **Step 5: Verify** — from `frontend/`: `npm test` (all pass, including the new test), `npm run build`
(must pass), `npm run lint` (no new errors or warnings).

- [ ] **Step 6: Commit** — `git add frontend/src/api.ts frontend/src/api.test.ts frontend/.env.example`,
`git diff --staged --stat` (exactly those three files), then
`git commit -m "feat(frontend): normalise VITE_API_BASE and document it for the Vercel build"`.

**REVIEW CHECKPOINT 2.** Hand over the commit hash, the `npm test`, `npm run build` and `npm run lint` output, and `git status`.

---

### Task 3: Operator steps (the user, not Gemini) and smoke check

Run after Claude has reviewed and pushed Tasks 1 and 2.

- [ ] **Railway (API service → Variables):** set `FRONTEND_URL=https://ledgerlens.nknext.dev`
  (scheme included, no trailing slash). Note: `backend/.env.demo` currently has `FRONTEND_URL=ledgerlens.nknext.dev`
  without a scheme; fix it there too, because a value without a scheme now stops the API at startup, which is the intended loud failure.
- [ ] **Railway:** confirm Railway redeploys from the pushed branch and `/health` and `/health/db` answer.
- [ ] **Vercel, environment variable:** `frontend/.env.vercel` (local, gitignored) holds `VITE_API_BASE`. In the project's
  Settings > Environment Variables use Import .env and choose that file, scope Production. It is named `.env.vercel`, not
  `.env`, on purpose: Vite loads `.env` for `npm run dev` too, which would send local calls to Railway, where CORS refuses
  localhost. The value is build-time, so redeploy after importing.
- [ ] **Vercel, project settings:** Root Directory `frontend`, Framework Preset Vite.
- [ ] **Vercel, production branch:** the custom domain serves the Production deployment, which is built from the
  project's Production Branch (default `main`, which does not have this app yet). Set the Production Branch to
  `feat/pre-launch-demo` until the release is promoted, then set it back to `main`. Without this the domain shows an old or empty build.
- [ ] **Vercel, branch and preview URLs:** Vercel also gives every branch a `*.vercel.app` URL. Those origins are not in
  `FRONTEND_URL`, so calls from them are refused by CORS; that is intended. Use `https://ledgerlens.nknext.dev` for testing.
- [ ] **Vercel:** the custom domain `ledgerlens.nknext.dev` is attached (done) and serves over HTTPS.
- [ ] **Preflight smoke test** from any terminal; expect a `200`, an `access-control-allow-origin` equal to the frontend origin, and the four headers in `access-control-allow-headers`:

```bash
curl -si -X OPTIONS https://ledger-lens-production-f77a.up.railway.app/chat \
  -H "Origin: https://ledgerlens.nknext.dev" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type,x-guest-id,idempotency-key,range" | head -15
```

- [ ] **Wrong-origin check:** the same command with `-H "Origin: https://evil.example"` must return `400` and no `access-control-allow-origin` line.
- [ ] **Browser check on `https://ledgerlens.nknext.dev`** (DevTools → Network open, no CORS errors in the console):
  the Documents screen lists the 4 contracts; the Chat screen streams a cited answer (the response is `text/event-stream`);
  clicking a citation opens the PDF viewer and the PDF renders; the dashboard tiles load.
- [ ] **Known gap until P9:** approvals and field reviews from the deployed site still write real rows. Keep the demo private and unannounced.

## Definition of done

- `pytest tests/test_cors.py` and the full backend suite pass; `npm test`, `npm run build` and `npm run lint` pass.
- Two commits on `feat/pre-launch-demo` (Task 1 includes `config.py`'s two changes), both reviewed by Claude and then pushed.
- The smoke checks in Task 3 pass on the deployed pair, and the CHANGELOG P1 and CORS lines are ticked with a dated note.
