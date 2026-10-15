# /start-sprint

Cut a new branch from `preview`, push it to set up remote tracking, and seed
`CHANGELOG.md` with the sprint's scope as the branch's first commit.

## Invocation
```
/start-sprint <short-description>
```
`<short-description>` becomes the branch suffix (kebab-case, matches `CLAUDE.md`'s
`type/short-description` branch convention). Infer the `type` prefix
(`feat`|`fix`|`chore`|`refactor`|`docs`|`test`) from what the sprint's scope actually
is — default to `feat` if it introduces new capability.

---

## Step 1 — Preflight

```bash
git branch --show-current
git status --short
git fetch origin main preview
git log origin/main..origin/preview --oneline
git log origin/preview..origin/main --oneline
```

**If `git status --short` shows uncommitted changes:** stop.
```
⛔ Uncommitted changes present on '<branch>'. Commit or stash first.
```

**If `preview` is BEHIND `main`** (`origin/preview..origin/main` is non-empty — main
has commits preview lacks): stop. Preview is stale relative to production and must
be fast-forwarded first (same operation as `/end-sprint` Step 6):
```
⛔ preview is behind main by N commit(s) — fast-forward preview before starting
a new sprint:
git checkout preview && git merge main && git push origin preview
```

**If `preview` is AHEAD of `main`** (docs/process commits, or merged-but-not-yet-
released work): expected per this repo's branch strategy — `preview` leads, `main`
catches up via PR. Report the gap for visibility, then proceed — this is not a stop
condition.

---

## Step 2 — Create the branch from preview

```bash
git checkout preview
git pull origin preview
git checkout -b <type>/<short-description> preview
```

---

## Step 3 — Push and set upstream tracking

```bash
git push -u origin <type>/<short-description>
```

Establishes the branch on `origin` so plain `git push`/`git pull` work for the rest
of the sprint without re-specifying `-u origin <branch>`.

---

## Step 4 — Seed CHANGELOG.md with the sprint's scope

Read `CHANGELOG.md`'s existing format before writing anything — most recent entry
first, `## [Sprint N — Closed] · <Title>`, a bold `**Closed — <date>.**`/`**Started
— <date>**` status line, scoped `### Completed`/`### Deferred` checklists (any
prior entry shows the exact shape). Determine the next sprint number by counting
existing `## [Sprint N` headers in the file and incrementing. Insert a new entry
at the **top** of the file, directly under the title/format header:

```markdown
## [Sprint <N> — In Progress] · <Title>

**Started — <YYYY-MM-DD> · branch: `<type>/<short-description>`**

### Scope
- [ ] `<scope>` — <planned item> → **Epic <N.M>**
...

### Reference
- <links to any planning/audit docs produced this session, e.g.
  docs/superpowers/specs|plans/... if one exists for this sprint>
```

Scope bullets come from whatever was actually agreed in this session (a plan, an
audit, a discussion) — never invent scope that wasn't discussed. Each bullet keeps
a `` `scope` `` prefix matching commit scopes used in this repo (e.g. `db`, `api`,
`ledger`, `documents`, `frontend`, `ui`, `design`, `chores`). Nothing in a
`### Scope` section is checked off yet; this entry gets its `[x]` boxes filled in
by later commits during the sprint. `/end-sprint` does not touch `CHANGELOG.md` —
once the sprint's PR merges, flip the header from `In Progress` to `Closed` and
add a `**Closed — <date>.**` line by hand (or as part of the merge commit) before
starting the next sprint.

**Epic linking (mandatory per `CLAUDE.md`'s CHANGELOG convention):** every scope
bullet that maps to an epic in `artifacts/product-backlog.md` ends with
`→ **Epic N.M**`. If a bullet has no corresponding epic (exploratory work outside
the epic-numbered backlog), write `**Not epic-tracked**` next to it instead of
silently omitting the link or inventing an epic number.

---

## Step 5 — Commit

```bash
git add CHANGELOG.md
git diff --staged --stat
git commit -m "docs: scope <sprint-name> sprint in changelog"
```

Per `CLAUDE.md` hygiene: name the file explicitly (never `git add -A`), review the
staged diff before committing. Do not push again after this commit — `/end-sprint`
handles the push when the sprint's actual work is ready to go up.

---

## Hard stops

| Condition | Action |
|---|---|
| Uncommitted changes present | `⛔ Uncommitted changes present. Commit or stash first.` |
| `preview` is behind `main` | `⛔ preview is behind main — fast-forward before starting a new sprint.` |
| `CHANGELOG.md`'s existing format doesn't match what's expected | Stop and ask rather than guessing a new format |
