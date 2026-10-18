"""A stand-in for the `claude` command (Claude Code). Lemma's tests point claudecode.CLAUDE at it.

`claude auth status --json` prints $FAKE_CLAUDE_AUTH. `claude -p` appends its arguments and each
message it reads to $FAKE_CLAUDE_LOG, and answers every message the way Claude Code's stream-json does.
"""

import json
import os
import sys
import time

args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    print(os.environ.get("FAKE_CLAUDE_AUTH", '{"loggedIn": false}'))
    sys.exit(0)


def log(entry):
    with open(os.environ["FAKE_CLAUDE_LOG"], "a") as f:
        f.write(json.dumps(entry) + "\n")


def emit(event):
    print(json.dumps(event), flush=True)


log({"args": args, "cwd": os.getcwd(), "api_key": "ANTHROPIC_API_KEY" in os.environ})
model = args[args.index("--model") + 1]
emit({"type": "system", "subtype": "init", "model": model, "tools": []})
for turn, line in enumerate(sys.stdin, 1):
    message = json.loads(line)["message"]
    log({"message": message})
    content = message["content"]
    text = content if isinstance(content, str) else content[-1]["text"]
    if "FAIL" in text:
        emit({"type": "result", "subtype": "success", "is_error": True, "result": "API Error: model overloaded"})
        continue
    if "LIMIT" in text:
        emit({"type": "result", "subtype": "success", "is_error": True, "result": "Claude usage limit reached. Your limit resets at 5pm"})
        continue
    if "SLOW" in text:
        time.sleep(30)
    if "CRASH" in text:
        sys.exit(1)
    reply = json.dumps({"turn": turn, "model": model})
    emit({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "hm"}}})
    emit({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": reply}}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": reply, "stop_reason": "max_tokens" if "LONG" in text else "end_turn"})
