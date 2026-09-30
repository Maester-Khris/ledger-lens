# Agent instructions (Antigravity / agy)

Project context, conventions and git rules are shared with Claude Code — the
single source of truth is CLAUDE.md:

@[CLAUDE.md](CLAUDE.md)

## agy-specific
- Custom commands referenced in CLAUDE.md (`/start-sprint`, `/end-sprint`,
  `/promote-release`, `/audit`) are Claude Code commands; their definitions
  live in `.claude/commands/*.md` — read the file and follow its steps.
- `git add` / `commit` / `push`, installs, deletes and anything touching
  Docker or the database prompt for approval by design (see
  `.agents/hooks.json`). Batch related staging into one `git add a b c`
  so the user approves once per logical change.
- Never add a `Co-Authored-By` trailer for any AI assistant.
