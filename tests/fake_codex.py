#!/usr/bin/env python3
"""A stand-in for the `codex` program, used by the tests. Records each call and answers like `codex exec --json`."""
import json, os, sys

args = sys.argv[1:]
log = os.environ.get("FAKE_CODEX_LOG")
if args[:2] == ["login", "status"]:
    print("Logged in using ChatGPT" if os.environ.get("FAKE_CODEX_LOGGED_IN", "1") == "1" else "Not logged in")
    sys.exit(0)
if args[:2] == ["debug", "models"]:
    print(json.dumps({"models": [
        {"slug": "gpt-6.1-sol", "display_name": "GPT-6.1-Sol", "visibility": "list", "context_window": 272000},
        {"slug": "tiny", "display_name": "Tiny", "visibility": "list", "context_window": 1000},
        {"slug": "hidden", "display_name": "Hidden", "visibility": "hide", "context_window": 272000}]}))
    sys.exit(0)
if args == ["--version"]:
    print("codex-cli 9.9.9-fake")
    sys.exit(0)
assert args[0] == "exec" and args[-1] == "-", args
prompt = sys.stdin.read()
if log:
    with open(log, "a") as f:
        f.write(json.dumps({"args": args, "prompt": prompt}) + "\n")
print(json.dumps({"type": "thread.started", "thread_id": "fake"}))
print(json.dumps({"type": "item.completed", "item": {"type": "error", "message": "a configuration warning, not a failure"}}))
if "FAIL" in prompt:
    print(json.dumps({"type": "turn.failed", "error": {"message": "usage limit reached"}}))
    sys.exit(1)
turn = prompt.count("=== Message ") or 1
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"turn": turn, "model": args[args.index("-m") + 1]})}}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}))
