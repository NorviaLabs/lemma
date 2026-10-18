"""Start Lemma: `python -m lemma` or `lemma`."""

from __future__ import annotations

import argparse
import os
import signal
import threading
import webbrowser

from . import __version__, dev, jev, server
from .server import make_server


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lemma", description="Start Lemma on this computer and open it in your browser.")
    ap.add_argument("--port", type=int, default=8765, help="port to listen on (default 8765; the next free port is used if taken)")
    ap.add_argument("--host", default=os.environ.get("LEMMA_HOST", "127.0.0.1"), help="address to listen on (default 127.0.0.1, this computer only; 0.0.0.0 hosts Lemma for others)")
    ap.add_argument("--allowed-hosts", default=os.environ.get("LEMMA_ALLOWED_HOSTS", ""), help="comma-separated domain names a hosted Lemma is reached by, e.g. tools.example.com")
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    ap.add_argument("--dev", action="store_true", help="development mode: restart on Python changes and live-reload the browser")
    ap.add_argument("--version", action="version", version=f"Lemma {__version__}")
    args = ap.parse_args(argv)
    if args.dev and not dev.is_child():
        return dev.supervise(args.port, open_browser=not args.no_browser)
    server.DEV = args.dev
    allowed = tuple(h for h in args.allowed_hosts.split(",") if h.strip())
    try:
        httpd = make_server(args.port, exact=args.dev, host=args.host, allowed_hosts=allowed)
    except ValueError as e:
        ap.error(str(e))
    # Treat `kill` like Ctrl+C.
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    url = f"http://localhost:{httpd.server_address[1]}/"
    if server.HOSTED:
        print(f"Lemma is hosted on {args.host}:{httpd.server_address[1]} for {', '.join(allowed)}  (press Ctrl+C to stop)", flush=True)
    elif not args.dev:  # in dev mode the supervisor prints the address
        print(f"Lemma is running at {url}  (only reachable from this computer; press Ctrl+C to stop)")
    if not jev.available():
        print(f"Search and lesson building are off: {jev.MISSING}", flush=True)
    if not args.no_browser and not server.HOSTED:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        if not args.dev:
            print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
