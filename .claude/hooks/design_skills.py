"""PreToolUse hook for the Skill tool.

When a superpowers design or planning skill is launched, remind Claude to load the
engineering reference skills first. Hooks can't invoke skills themselves; they
inject context, and Claude loads the skills with the Skill tool.
"""
import json
import sys

TRIGGERS = {"superpowers:brainstorming", "superpowers:writing-plans"}
REQUIRED = [
    "ddia-systems",
    "clean-architecture",
    "domain-driven-design",
    "pragmatic-programmer",
    "clean-code",
    "supabase-postgres-best-practices",
]
CANDIDATES = [
    "system-design",
    "release-it",
    "software-design-philosophy",
    "superpowers:test-driven-development",
    "refactoring-patterns",
    "frontend-design (UI work)",
]

payload = json.load(sys.stdin)
skill = str((payload.get("tool_input") or {}).get("skill", ""))

if skill in TRIGGERS:
    message = (
        f"{skill} is starting. Before designing or planning, load these reference skills "
        f"with the Skill tool (in parallel, if not already loaded this session): "
        f"{', '.join(REQUIRED)}. Also load any other skill relevant to the task, for example: "
        f"{', '.join(CANDIDATES)}. Apply them as lenses in the design and plan, and list in "
        f"the spec/plan which skills informed which decisions."
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message}}))
