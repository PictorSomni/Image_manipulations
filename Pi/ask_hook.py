"""Hook Claude Code (PreToolUse / PostToolUse sur AskUserQuestion).

Claude Code n'écrit la question dans l'historique qu'après la réponse :
ce hook la dépose dans ~/.claude_ask.json pendant qu'elle attend, pour
que Claude Pi (Mobile/claude_web.py) l'affiche et notifie aussitôt.
"""
import json
import os
import sys
import time

ASK = os.path.expanduser("~/.claude_ask.json")

try:
    data = json.load(sys.stdin)
    if data.get("hook_event_name") == "PreToolUse":
        qs = (data.get("tool_input") or {}).get("questions") or []
        with open(ASK + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"at": time.time(), "q": [
                {"t": q.get("question", ""),
                 "o": [o.get("label", "") for o in q.get("options", [])],
                 "multi": bool(q.get("multiSelect"))} for q in qs]},
                f, ensure_ascii=False)
        os.replace(ASK + ".tmp", ASK)
    elif os.path.exists(ASK):
        os.remove(ASK)
except Exception:  # ne jamais gêner Claude Code
    pass
