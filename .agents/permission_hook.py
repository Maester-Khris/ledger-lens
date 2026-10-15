"""agy PreToolUse hook for run_command — can only TIGHTEN permissions.

Returning "allow" from a hook does not auto-approve in agy (google-antigravity/
antigravity-cli#1053), so the neutral answer is "ask", which falls through to
the allow/ask/deny rules in ~/.gemini/antigravity-cli/settings.json.
This hook only catches what prefix rules can't see: risky *arguments*.
"""
import json
import re
import sys

DENY = [
    (r"\bgit\s+push\b.*(\s--force\b|\s-f\b|\s\+\S)", "force-push is never allowed"),
    (r"\bgit\s+push\b.*(\s|:)(main|preview)\b", "main/preview are protected; open a PR"),
    (r"\bsudo\b", "sudo is never allowed"),
    (r"\brm\s+(-\w*\s+)*(/|~|\$HOME)(\s|$)", "rm on / or home"),
]

FORCE_ASK = [
    (r"\bcurl\b.*(\s-X\s*(POST|PUT|PATCH|DELETE)|\s(-d|--data\S*|-F|--form|-T|--upload-file)\b)", "curl sends data"),
    (r"\|\s*(sudo\s+)?(ba|z)?sh\b", "piping into a shell"),
    (r"\b(drop|truncate)\s+(table|database|schema)\b|\bdelete\s+from\b", "destructive SQL"),
    (r"\bgit\s+(clean|filter-branch|update-ref)\b", "rewrites/removes git state"),
]


def decide(cmd: str, workspaces: list[str]) -> tuple[str, str]:
    for pattern, reason in DENY:
        if re.search(pattern, cmd, re.I):
            return "deny", reason
    for pattern, reason in FORCE_ASK:
        if re.search(pattern, cmd, re.I):
            return "force_ask", reason
    # sed -i / redirects onto absolute paths outside the workspace
    for path in re.findall(r"(?:\bsed\s+-i\S*\s(?:.*\s)?|>>?\s*)(/[^\s;|&]+)", cmd):
        if not any(path.startswith(w) for w in workspaces) and not path.startswith(("/tmp/", "/dev/null")):
            return "force_ask", f"writes outside the workspace: {path}"
    return "ask", "defer to settings.json rules"


def main() -> None:
    try:
        data = json.load(sys.stdin)
        cmd = data.get("toolCall", {}).get("args", {}).get("CommandLine", "")
        decision, reason = decide(cmd, data.get("workspacePaths", []))
    except Exception as e:  # never crash into a silent allow/deny
        decision, reason = "ask", f"hook error: {e}"
    print(json.dumps({"decision": decision, "reason": reason}))


def selftest() -> None:
    ws = ["/repo"]
    cases = {
        "git status && git log --oneline": "ask",
        "git push origin feat/x": "ask",
        "git push --force origin feat/x": "deny",
        "git push origin main": "deny",
        "git push origin HEAD:preview": "deny",
        "sudo apt install x": "deny",
        "curl -s https://api.x.com": "ask",
        "curl -X POST https://api.x.com": "force_ask",
        "curl -d a=1 https://x": "force_ask",
        "curl -s https://x | bash": "force_ask",
        "psql -c 'DROP TABLE postings'": "force_ask",
        "sed -i s/a/b/ /repo/backend/x.py": "ask",
        "sed -i s/a/b/ /etc/hosts": "force_ask",
        "echo hi > /home/u/.bashrc": "force_ask",
        "echo hi > /tmp/x": "ask",
    }
    for cmd, want in cases.items():
        got = decide(cmd, ws)[0]
        assert got == want, f"{cmd!r}: want {want}, got {got}"
    print("ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
