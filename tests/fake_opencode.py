#!/usr/bin/env python3
"""A stand-in for the `opencode` program, used by the tests. Implements just enough of `opencode serve`."""
import base64, json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

if "--version" in sys.argv:
    print("9.9.9-fake"); sys.exit(0)
port = int(sys.argv[sys.argv.index("--port") + 1])
password = os.environ["OPENCODE_SERVER_PASSWORD"]
config = json.loads(os.environ["OPENCODE_CONFIG_CONTENT"])
assert config["agent"]["lemma"]["tools"] == {"*": False} and config["agent"]["lemma"]["permission"] == {"*": "deny"}
assert "--pure" in sys.argv and sys.argv[sys.argv.index("--hostname") + 1] == "127.0.0.1"
log = open(os.environ["FAKE_OC_LOG"], "a")
sessions = {}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def authed(self):
        ok = self.headers.get("Authorization") == "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()
        if not ok: self.send(401, {"error": "unauthorized"})
        return ok
    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
    def do_GET(self):
        if not self.authed(): return
        if self.path == "/agent": return self.send(200, [{"name": "lemma"}])
        if self.path == "/config/providers":
            return self.send(200, {"providers": [{"id": "opencode-go", "models": {"gpt-5.6-luna": {"name": "GPT-5.6 Luna", "limit": {"context": 1050000}}, "glm-5.3": {"name": "GLM-5.3", "limit": {"context": 1000000}}, "old": {"name": "Old", "status": "deprecated"}}}]})
        self.send(404, {})
    def do_POST(self):
        if not self.authed(): return
        b = self.body()
        if self.path == "/session":
            sid = f"ses_{len(sessions) + 1}"; sessions[sid] = []
            return self.send(200, {"id": sid})
        if self.path.endswith("/message"):
            sid = self.path.split("/")[2]
            sessions[sid].append(b)
            log.write(json.dumps({"event": "message", "session": sid, "agent": b["agent"], "model": b["model"], "nparts": len(b["parts"]), "has_system": bool(b.get("system"))}) + "\n"); log.flush()
            text = b["parts"][-1]["text"]
            if "FAIL" in text:
                return self.send(200, {"info": {"error": {"name": "APIError", "data": {"message": "quota exceeded"}}}, "parts": []})
            reply = json.dumps({"turn": len(sessions[sid]), "model": b["model"]["modelID"]})
            return self.send(200, {"info": {"finish": "stop"}, "parts": [{"type": "step-start"}, {"type": "text", "text": reply}, {"type": "step-finish"}]})
        self.send(404, {})
    def do_DELETE(self):
        if not self.authed(): return
        log.write(json.dumps({"event": "delete", "session": self.path.split("/")[2]}) + "\n"); log.flush()
        self.send(200, True)

HTTPServer(("127.0.0.1", port), H).serve_forever()
