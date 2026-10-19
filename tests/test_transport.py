"""A hosted OpenLemma is HTTPS only: browsers are told to stay on HTTPS, and a plain-HTTP visit is sent there."""

from __future__ import annotations

import http.client
import unittest
from unittest.mock import patch

from hosting import SITE, HostedServer
from lemma import server

HTTPS = {"LEMMA_PUBLIC_URL": f"https://{SITE}"}


class HostedTransport(unittest.TestCase):
    def test_every_response_tells_browsers_to_stay_on_https(self):
        with HostedServer(HTTPS) as site:
            for method, path in (("GET", "/"), ("GET", "/api/status"), ("GET", "/static/app.js"), ("GET", "/nope"), ("POST", "/api/lessons")):
                with self.subTest(path=path):
                    s, r, _ = site.req(method, path, body={} if method == "POST" else None)
                    self.assertEqual(r.getheader("Strict-Transport-Security"), "max-age=31536000", (s, path))

    def test_a_plain_http_visit_moves_to_https(self):
        # Cloudflare's tunnel is the only way in, and it says which scheme the visitor used.
        with HostedServer(HTTPS) as site:
            s, r, _ = site.req("GET", "/privacy?x=1", headers={"X-Forwarded-Proto": "http"})
            self.assertEqual((s, r.getheader("Location")), (301, f"https://{SITE}/privacy?x=1"))
            s, r, _ = site.req("GET", "/privacy", headers={"X-Forwarded-Proto": "https"})
            self.assertEqual(s, 200)

    def test_redirects_never_take_a_host_from_the_request_line(self):
        with HostedServer(HTTPS, hosts=(SITE, f"www.{SITE}")) as site:
            c = http.client.HTTPConnection("127.0.0.1", site.port, timeout=10)
            c.putrequest("GET", "@evil.test/", skip_host=True)
            c.putheader("Host", f"www.{SITE}")
            c.endheaders()
            r = c.getresponse()
            r.read()
            c.close()
            self.assertEqual((r.status, r.getheader("Location")), (301, f"https://{SITE}/"))

    def test_api_writes_are_limited_per_visitor_address(self):
        # Cloudflare names the visitor's address; reads such as progress polling are never limited.
        with HostedServer(HTTPS) as site, patch.object(server, "RATE_LIMIT", 3):
            ann, bob = {"CF-Connecting-IP": "203.0.113.7"}, {"CF-Connecting-IP": "198.51.100.9"}
            sent = [site.req("POST", "/api/event", {"name": "lesson_open"}, headers=ann)[0] for _ in range(4)]
            self.assertEqual(sent, [200, 200, 200, 429])
            s, r, raw = site.req("POST", "/api/event", {"name": "lesson_open"}, headers=ann)
            self.assertEqual((s, r.getheader("Retry-After")), (429, str(server.RATE_WINDOW)))
            self.assertIn(b"Too many requests", raw)
            self.assertEqual(site.req("GET", "/api/status", headers=ann)[0], 200)
            self.assertEqual(site.req("POST", "/api/event", {"name": "lesson_open"}, headers=bob)[0], 200)

    def test_a_local_server_sends_neither(self):
        httpd = server.make_server(0)
        try:
            import threading
            threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
            c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
            c.request("GET", "/api/status", headers={"X-Forwarded-Proto": "http"})
            r = c.getresponse()
            r.read()
            c.close()
            self.assertEqual(r.status, 200)
            self.assertIsNone(r.getheader("Strict-Transport-Security"))
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
