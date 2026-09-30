# /promote-release

Promote `preview` to `main`: open a PR from `preview` into `main`, verify it's
actually mergeable (status checks + SonarCloud, with real root-cause detail on
failure, not just "failed" — same rigor as `/end-sprint`), merge if clean.

This is the only path anything takes into `main`. Individual feature branches
merge into `preview` via `/end-sprint`; this command promotes the accumulated
`preview` state to production once it's ready to ship.

## Invocation
```
/promote-release
```
No arguments — always promotes `preview` → `main`.

---

## Step 1 — Preflight

This operates on remote refs, not the working tree, so it doesn't require being on
any particular local branch. Confirm `preview` is actually ahead of `main`:

```bash
git fetch origin
git log origin/main..origin/preview --oneline
```

If empty: stop.
```
⛔ preview is not ahead of main — nothing to promote.
```

---

## Step 2 — Create the PR (skip if one already exists)

```bash
gh pr list --base main --head preview --json number,url,state 2>/dev/null
```

**If an open `preview`→`main` PR already exists:** use it, skip creation, report:
```
PR already exists: <url>
```

**Otherwise, create one:**
1. Gather context for the body:
   ```bash
   git log origin/main..origin/preview --oneline
   git diff origin/main..origin/preview --stat
   ```
2. Draft a release-style title (e.g. `Release 2026-08-30: <n> features`) and a body
   with `## Summary` (grouped by feature branch/theme, pulled from the merge commits
   on `preview`) and `## Included` (list each merged feature PR/branch if
   identifiable from merge commit messages).
3. Create it:
   ```bash
   gh pr create --base main --head preview --title "<title>" --body "$(cat <<'EOF'
   ## Summary
   - <bullet>

   ## Included
   - <feature branch / PR>
   EOF
   )"
   ```
4. Report the PR URL.

---

## Step 3 — Check mergeability

Identical mechanics to `/end-sprint` Step 4 — same fields, same rigor:

```bash
gh pr view <number> --json mergeable,mergeStateStatus,statusCheckRollup
```

Report every check in `statusCheckRollup` by name and status — do not summarize away
a failure. Specifically:

- **GitHub Actions / "branch test" workflows** — if `statusCheckRollup` contains no
  `CheckRun` entries with a `workflowName`, that means no GitHub Actions workflow is
  configured on this repo. Report that plainly (`No GitHub Actions configured —
  nothing to check here`) rather than treating it as a failure or silently skipping
  it.
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
  Report the exact rule, file, and line, not just the gate verdict.
- **Vercel / other status contexts** — report pass/fail as-is.

**Decision:**
- If `mergeStateStatus` is `CLEAN` **and** every completed check is a pass/neutral →
  proceed to Step 4.
- If `mergeStateStatus` is anything else (`UNSTABLE`, `BLOCKED`, `DIRTY`, ...) or any
  check failed → **stop, do not merge.** Report the exact failing check(s) and their
  root cause (per above), and wait for direction. Do not guess a fix and do not merge
  anyway.

---

## Step 4 — Merge (only if Step 3 is fully green)

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

## Step 5 — Local sync (only if a local `main` branch is kept)

`preview` is unaffected by this promotion, so no next-branch setup is needed there.
If a local `main` tracking branch exists and needs updating for reference:

```bash
git fetch origin
git checkout main
git merge origin/main
```

Skip this entirely if no local `main` branch is kept around.

---

## Hard stops

| Condition | Action |
|---|---|
| `preview` not ahead of `main` | `⛔ preview is not ahead of main — nothing to promote.` |
| `gh` not authenticated | `⛔ gh is not authenticated — run 'gh auth login' first.` |
| Any status check failed or `mergeStateStatus` not `CLEAN` | Stop before Step 4. Report exact failing check(s) with root cause. Do not merge. |
| `gh pr merge` fails (e.g. remote moved, branch protection) | Stop. Report the exact error. Do not retry with `--force` or bypass flags without being told to. |
