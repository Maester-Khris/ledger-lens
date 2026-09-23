# /audit

Audit the repository, a specific package, or a specific epic to produce an
accurate picture of what is done, what is partial, and what is not started.

## Invocation
```
/audit                      — full repo audit
/audit <package>            — single package audit (backend|frontend)
/audit <epic>                — specific backlog epic audit (e.g. "Epic 1.3")

# Examples:
/audit
/audit backend
/audit "Epic 1.3"
```

---

## Step 1 — Determine audit scope

Parse the invocation arguments:
- No args → audit both packages: `backend`, `frontend`, against the full backlog
- One arg matching `backend`/`frontend` → audit that package only
- One arg matching an epic reference (e.g. `Epic 1.3`) → audit only that epic's scope

---

## Step 2 — Load context

Read in this order before scanning anything:

```
CLAUDE.md                      — stack, structure, current scope summary
artifacts/product-backlog.md   — source of truth for planned epics, in order
CHANGELOG.md                   — what has actually shipped, by sprint
docs/superpowers/specs/        — design specs (list filenames, read if scope overlaps)
docs/superpowers/plans/        — implementation plans (list filenames, read if scope overlaps)
```

Confirm loaded context in one line:
```
Context loaded: CLAUDE.md, product-backlog.md, CHANGELOG.md [+ extras]
```

---

## Step 3 — Scan

Run the following scans based on scope. Do not skip scans — each one feeds
a different section of the audit output. Avoid raw `grep`/`find` over
`frontend/node_modules`, `backend/.venv`, `**/__pycache__`, `frontend/dist` —
they're gitignored, not project code, and burn tokens for zero signal. If
`graphify-out/graph.json` exists, prefer `graphify query`/`graphify explain`
over grep for anything beyond a specific known file/line.

### Always run (any scope)

```bash
# Current branch and unmerged work
git branch --show-current
git log preview..HEAD --oneline

# Uncommitted changes
git status --short
```

### backend scans

```bash
# Migrations present
ls backend/alembic/versions

# Routes registered
grep -rn "@router\.\|APIRouter" backend/app/routes --include="*.py"

# DAO methods available
grep -n "def \|async def " backend/app/ledger/dao.py

# Tests present
find backend/tests -name "test_*.py" | sort

# TODO / stubs / placeholders
grep -rn "TODO\|FIXME\|NotImplementedError\|pass  #" backend/app --include="*.py"
```

### frontend scans

```bash
# Screens/components present
find frontend/src/screens frontend/src/components -type f 2>/dev/null | sort

# Mock/static data still in use (pre-API-wiring signal)
grep -rn "mock\|MOCK\|hardcoded\|placeholder" frontend/src --include="*.ts" --include="*.tsx"

# Routes/pages wired
grep -rn "Route\|useNavigate\|Link " frontend/src --include="*.tsx"
```

### Epic-specific scans (when an epic arg is provided)

```bash
# Find the epic's checklist in the backlog
grep -A 15 "<epic reference>" artifacts/product-backlog.md

# Find related code by keyword from the epic title
grep -rln "<keyword>" backend/app --include="*.py"
grep -rln "<keyword>" frontend/src --include="*.tsx" --include="*.ts"
```

---

## Step 4 — Produce audit report

Output a structured report. Never skip a section.
Mark every item with one of: ✅ Done | ⚠️ Partial | ❌ Not started

### Report format

```
# Audit Report — <scope> — <date>

## Source of truth
Sprint:        [current sprint from CHANGELOG, if any]
Branch:        [current branch]
Ahead of preview: [N commits — list them or "none"]
Uncommitted:   [N files or "clean"]

---

## Epic inventory (from artifacts/product-backlog.md)

| Epic | Item | Status | Evidence |
|---|---|---|---|
| 1.1 | accounts/postings/entries schema | ✅ Done | backend/alembic/versions/0001_create_ledger_tables.py |
| 1.3 | POST /postings endpoint | ❌ Not started | no route found in backend/app/routes |

---

## Backend endpoint audit

| Method | Path | Handler | Test exists |
|---|---|---|---|
| GET | /health | routes/health.py | ✅ |

---

## Frontend wiring audit

| Screen | Data source | Wired to backend? |
|---|---|---|
| Dashboard | static | ❌ No |

---

## Gap summary

### Must fix before next sprint
- [ ] <item> — <reason>

### Deferred (already in backlog/Icebox)
- [ ] <item> — backlog reference

### Not in any plan yet (newly discovered)
- [ ] <item> — <evidence>

---

## Recommended next actions
1. <highest priority gap, per backlog execution order>
2. <second priority>
3. <third priority>
```

---

## Hard stops

| Condition | Action |
|---|---|
| `artifacts/product-backlog.md` not found | `⛔ product-backlog.md missing — cannot determine planned vs completed scope` |
| Package directory not found | `⛔ Package <name> not found in repo root` |
| Epic reference matches nothing in the backlog | `⚠️ No matching epic found — check the reference or run /audit with no args` |

---

## Notes

- Never guess status from memory — every status must be backed by a scan result
  or an explicit CHANGELOG/backlog entry.
- If a backlog item is checked `[x]` but no matching code/test is found, mark
  ⚠️ Partial and note the discrepancy rather than trusting the checkbox.
- Do not modify any file during an audit run.
