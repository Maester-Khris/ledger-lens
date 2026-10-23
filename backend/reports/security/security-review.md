# /security-review: sprint diff `git diff preview...HEAD` (2026-10-16)

Scope: backend/app, backend/scripts, backend/alembic, requirements files. Reports, docs and tests are excluded.
The review was read-only and kept only findings with confidence 8 or above.

**Result: no high-confidence vulnerabilities were introduced by this diff.**

## Tenant-scoping checks
- **Document list (one query):** `documents/dao.py:197-202` always filters on `Document.tenant_id`.
- **Vault lookup (one array parameter):** `documents/dao.py:247-249` filters on `tenant_id`, and the token list is a typed `ARRAY(Text)` bind.
- **HMAC keyed once:** `documents/redact.py:70-80` seeds the HMAC with `"{tenant_id}|"`, so tokens are byte-identical to the per-call HMAC. The maker is built per call.
- **Compiled graph:** `assistant/graph.py:88-94` reads the context from each run's config and there is no checkpointer. `service.py:225-231` builds a new `ToolContext` per request.
- **Redis limiter key:** `rate_limit.py:57-58` builds `rl:{name}:{guest uuid | ip}`. Keys and values go to a fixed Lua script as `KEYS`/`ARGV`, so nothing can be injected.

## Dropped candidates (false positives, or below confidence 8)
1. **Question PII is now committed to the vault on every turn** (`service.py:117`). Exploiting it needs the pre-existing `session_id` exposure through `GET /tool-invocations`, plus a model echo that passes citation verification. Confidence 4. Hardening, out of this diff: bind `session_id` to the guest.
2. **Stub vector index or mock base URL:** set from environment variables only, which are trusted.
3. **Redis limiter fails open:** rate limiting and availability are excluded from this review.
4. **New raw-PII paths to the model:** none. The new prompt content comes from `text_redacted` or tokenised text.
5. **Shared tool-binding cache across concurrent turns:** the bindings are stateless runnables.
6. **`_turn_inputs` fallback to `ctx.session`:** the fallback is reached only in tests.
7. **Model-chosen `document_ids`:** pre-existing, and the search stays tenant-scoped.
8. **`json.loads` on tool output:** plain JSON parsing, no deserialisation risk.
9. **`fee_text.py` regex:** business logic only.
10. **Load-test compose, mock and nginx:** local only, bound to 127.0.0.1, with placeholder credentials.
11. **New pinned dependencies** (`redis`, `py-spy`, `tiktoken`): library age is out of scope here (covered by S2).
12. **`alembic/env.py` logging change:** no new sensitive logging.
