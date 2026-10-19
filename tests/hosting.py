"""A hosted Lemma on a loopback port for tests: its environment and server globals are restored afterwards."""

from __future__ import annotations

import http.client
import json
import os
import threading

import test_lemma  # noqa: F401  sets a temporary LEMMA_HOME and installs the Jev stand-in
from lemma import metrics, server

SITE = "tools.example.com"


class HostedServer:
    def __init__(self, env: dict, hosts=(SITE,)):
        self.env, self.hosts = env, hosts

    def __enter__(self):
        self.old_env = {k: os.environ.get(k) for k in self.env}
        self.old_globals = (server.HOSTED, server.ALLOWED_HOSTS, server.DEV, metrics.ENABLED)
        os.environ.update(self.env)
        self.httpd = server.make_server(0, host="0.0.0.0", allowed_hosts=self.hosts)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.HOSTED, server.ALLOWED_HOSTS, server.DEV, metrics.ENABLED = self.old_globals
        server.REQUEST.user = None
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def req(self, method, path, body=None, cookies=None, headers=None):
        """(status, response, raw body). `cookies` is {name: value}; a dict or list body is sent as JSON."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": SITE, "Origin": f"https://{SITE}"}
        if cookies:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
        h.update(headers or {})
        data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
        c.request(method, path, data, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, r, raw


def set_cookies(response) -> dict:
    """{name: (value, attributes)} from every Set-Cookie header of a response."""
    out = {}
    for line in response.msg.get_all("Set-Cookie") or []:
        pair, _, attrs = line.partition(";")
        name, _, value = pair.partition("=")
        out[name.strip()] = (value, attrs)
    return out
