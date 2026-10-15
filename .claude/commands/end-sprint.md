# /end-sprint

Push the current branch, open a PR against `preview` (never `main` — feature
branches land on `preview` first, `main` only receives promoted releases via
`/promote-release`), verify it's actually mergeable (status checks + SonarCloud,
with real root-cause detail on failure, not just "failed"), merge if clean, then
sync local `preview` to match.

## Invocation
```
/end-sprint
```
No arguments — always operates on the current branch.

---

## Step 1 — Preflight

```bash
git branch --show-current
git status --short
```

**If the current branch is `main` or `preview`:** stop immediately.
```
⛔ On protected branch '<branch>'. Nothing to end-sprint from here —
switch to the feature branch first.
```

**If `git status --short` shows uncommitted changes:** stop.
```
⛔ Uncommitted changes present. This command pushes and opens a PR —
it does not commit on your behalf. Commit or stash first.
```

**If the branch has no commits ahead of `preview`:**
```bash
git log preview..HEAD --oneline
```
If empty: stop.
```
⛔ No commits ahead of preview on '<branch>' — nothing to end-sprint.
```

---

## Step 2 — Push

```bash
git push -u origin <branch>
```

If the push reports "everything up-to-date," continue anyway — a PR may still need
creating (e.g. this command is being re-run after an earlier failure).

---

## Step 3 — Create the PR (skip if one already exists)

```bash
gh pr view <branch> --json number,url,state 2>/dev/null
```

**If an open PR already exists for this branch:** use it, skip creation, report:
```
PR already exists: <url>
```

**Otherwise, create one:**
1. Gather context for the body:
   ```bash
   git log preview..HEAD --oneline
   git diff preview..HEAD --stat
   ```
2. Draft a title (short, under 70 chars, derived from the branch name / commit theme)
   and a body with `## Summary` (bullets from the commit log, grouped by theme) and
   `## Test plan` (checklist — infer from what the commits touch: build checks,
   test suites run, manual verification done).
3. Create it:
   ```bash
   gh pr create --base preview --head <branch> --title "<title>" --body "$(cat <<'EOF'
   ## Summary
   - <bullet>

   ## Test plan
   - [x] <what was verified>
   EOF
   )"
   ```
4. Report the PR URL.

---

## Step 4 — Check mergeability

```bash
gh pr view <number> --json mergeable,mergeStateStatus,statusCheckRollup
```

Report every check in `statusCheckRollup` by name and status — do not summarize away
a failure. Specifically:

- **GitHub Actions / "branch test" workflows** — if `statusCheckRollup` contains no
  `CheckRun` entries with a `workflowName`, that means no GitHub Actions workflow is
  configured on this repo. Report that plainly (`No GitHub Actions configured — nothing
  to check here`) rather than treating it as a failure or silently skipping it.
- **SonarCloud** — if the check's `conclusion` is `FAILURE`, do not stop at "Sonar
  failed." Get the actual issue(s):
  ```bash
  gh pr view <number> --json comments --jq '.comments[] | select(.body | contains("Quality Gate")) | .body'
  ```
  and cross-reference with SonarCloud's public API for the specific failing issue(s)
  (adjust `componentKeys` to this repo's actual Sonar project key):
  ```bash
  curl -s "https://sonarcloud.io/api/issues/search?componentKeys=<org>_<repo>&pullRequest=<number>&resolved=false" | python3 -m json.tool
  ```
  Report the exact rule, file, and line — not just the gate verdict.
- **Vercel / other status contexts** — report pass/fail as-is.

**Decision:**
- If `mergeStateStatus` is `CLEAN` **and** every completed check is a pass/neutral →
  proceed to Step 5.
- If `mergeStateStatus` is anything else (`UNSTABLE`, `BLOCKED`, `DIRTY`, ...) or any
  check failed → **stop, do not merge.** Report the exact failing check(s) and their
  root cause (per above), and wait for direction. Do not guess a fix and do not merge
  anyway.

---

## Step 5 — Merge (only if Step 4 is fully green)

```bash
gh pr merge <number> --merge
```

Matches this repo's existing history (`Merge pull request #N ...` commits) — do not
use `--squash` or `--rebase` unless explicitly told to.

Confirm:
```bash
gh pr view <number> --json state,mergedAt,mergeCommit
```

---

## Step 6 — Local sync

The PR merged directly into `preview` (Step 5), so there's no cross-branch merge to
do — just bring the local `preview` branch up to date with what GitHub now has, so
the next feature branch is cut from current work:

```bash
git checkout preview
git pull origin preview
```

`preview` → `main` promotion is a separate step, handled by `/promote-release` —
not part of this command.

---

## Hard stops

| Condition | Action |
|---|---|
| Current branch is `main` or `preview` | `⛔ On protected branch. Nothing to end-sprint from here.` |
| Uncommitted changes present | `⛔ Uncommitted changes present. Commit or stash first.` |
| No commits ahead of `preview` | `⛔ No commits ahead of preview — nothing to end-sprint.` |
| `gh` not authenticated | `⛔ gh is not authenticated — run 'gh auth login' first.` |
| Any status check failed or `mergeStateStatus` not `CLEAN` | Stop before Step 5. Report exact failing check(s) with root cause. Do not merge. |
| `gh pr merge` fails (e.g. remote moved, branch protection) | Stop. Report the exact error. Do not retry with `--force` or bypass flags without being told to. |
