#!/usr/bin/env python3
"""
access.py — the second lock behind Tailscale Serve.

The interesting cases are the refusals and the one thing that must not break:

  · a loopback Host passes with no header at all, because the local browser
    and the Vite dev server never carry one;
  · a tailnet Host with no login is a Funnel or a stray proxy, refused;
  · a tailnet Host with the wrong login is somebody else's node, refused;
  · a missing config refuses everyone remote — fail closed, like model_allow;
  · a client cannot smuggle a loopback Host through a bracketed IPv6 or a port;
  · an SSE response streams through unchanged, chunk by chunk, because the
    middleware is pure ASGI — the one property BaseHTTPMiddleware would cost.
"""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runtime"))
sys.path.insert(0, str(REPO / "interface" / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  — logs out of runtime/

from fastapi import FastAPI                        # noqa: E402
from fastapi.responses import StreamingResponse    # noqa: E402
from fastapi.testclient import TestClient          # noqa: E402

import access                                      # noqa: E402

TS_HOST = "win-2mhekgnh77i.tailffbbc7.ts.net"
LOGIN = "zach@example.com"


def make_app(refusals):
    app = FastAPI()
    app.add_middleware(access.RemoteAccess, log=refusals.append)

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    @app.get("/api/stream")
    def stream():
        async def gen():
            for i in range(3):
                yield f"data: {i}\n\n"
                await asyncio.sleep(0)
        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


class AccessBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._saved = access._RUNTIME
        access._RUNTIME = self.root
        access.remote_login.cache_clear()
        self.refusals = []
        self.client = TestClient(make_app(self.refusals))

    def tearDown(self):
        access._RUNTIME = self._saved
        access.remote_login.cache_clear()
        self.tmp.cleanup()

    def configure(self, login=LOGIN):
        (self.root / "privacy.config.json").write_text(
            json.dumps({"model_allow": [], "remote_login": login}), encoding="utf-8")
        access.remote_login.cache_clear()

    def get(self, path="/api/ping", host="localhost:8787", login=None):
        headers = {"host": host}
        if login is not None:
            headers["tailscale-user-login"] = login
        return self.client.get(path, headers=headers)


class LocalPasses(AccessBase):
    def test_localhost_without_header(self):
        self.configure()
        self.assertEqual(self.get(host="localhost:8787").status_code, 200)

    def test_loopback_ip_and_dev_server_port(self):
        self.configure()
        self.assertEqual(self.get(host="127.0.0.1:5173").status_code, 200)

    def test_ipv6_loopback(self):
        self.configure()
        self.assertEqual(self.get(host="[::1]:8787").status_code, 200)

    def test_local_passes_even_with_no_config(self):
        # No config at all: the machine is still the machine.
        self.assertEqual(self.get().status_code, 200)
        self.assertEqual(self.refusals, [])


class RemoteRefusals(AccessBase):
    def test_tailnet_host_without_login_is_refused(self):
        self.configure()
        r = self.get(host=TS_HOST)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"], "forbidden")
        self.assertEqual(len(self.refusals), 1)
        self.assertIn("no tailscale login", self.refusals[0])

    def test_wrong_login_is_refused_and_not_echoed(self):
        self.configure()
        r = self.get(host=TS_HOST, login="stranger@example.com")
        self.assertEqual(r.status_code, 403)
        self.assertNotIn("stranger", self.refusals[0])

    def test_no_config_refuses_every_remote_login(self):
        r = self.get(host=TS_HOST, login=LOGIN)
        self.assertEqual(r.status_code, 403)
        self.assertIn("not configured", self.refusals[0])

    def test_unparseable_config_fails_closed(self):
        (self.root / "privacy.config.json").write_text("{not json", encoding="utf-8")
        access.remote_login.cache_clear()
        self.assertEqual(self.get(host=TS_HOST, login=LOGIN).status_code, 403)

    def test_static_paths_are_gated_too(self):
        self.configure()
        # Nothing is mounted at / here, so a pass would be a 404 — the point is
        # that the middleware answers before any router or mount is consulted.
        self.assertEqual(self.get(path="/", host=TS_HOST).status_code, 403)
        self.assertEqual(self.get(path="/assets/x.js", host=TS_HOST).status_code, 403)

    def test_lookalike_hosts_are_not_local(self):
        self.configure()
        for host in ("localhost.evil.com", "127.0.0.1.nip.io", "[::1]x", "localhost2"):
            with self.subTest(host=host):
                self.assertEqual(self.get(host=host).status_code, 403)


class RemotePasses(AccessBase):
    def test_right_login_passes(self):
        self.configure()
        self.assertEqual(self.get(host=TS_HOST, login=LOGIN).status_code, 200)
        self.assertEqual(self.refusals, [])

    def test_login_match_is_case_insensitive(self):
        self.configure(login="Zach@Example.com")
        self.assertEqual(self.get(host=TS_HOST, login="zach@EXAMPLE.com").status_code, 200)

    def test_sse_streams_through_unbuffered(self):
        # Measured at the ASGI layer, not through the test client, which
        # coalesces chunks on its own: the middleware must forward each
        # http.response.body message as the app sends it, never gather them.
        self.configure()
        app = make_app(self.refusals)
        scope = {"type": "http", "method": "GET", "path": "/api/stream",
                 "query_string": b"", "headers": [
                     (b"host", TS_HOST.encode()),
                     (b"tailscale-user-login", LOGIN.encode())]}
        sent = []
        delivered = False

        async def receive():
            # One request body, then block: Starlette's disconnect listener
            # polls receive() in a loop and a fake that answers instantly
            # starves the streaming task. It is cancelled when the stream ends.
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.Event().wait()

        async def send(msg):
            sent.append(msg)

        asyncio.run(app(scope, receive, send))
        start = [m for m in sent if m["type"] == "http.response.start"]
        bodies = [m for m in sent if m["type"] == "http.response.body"]
        self.assertEqual(start[0]["status"], 200)
        self.assertEqual(b"".join(m.get("body", b"") for m in bodies),
                         b"data: 0\n\ndata: 1\n\ndata: 2\n\n")
        self.assertGreaterEqual(len(bodies), 3, "the stream was gathered into one body")


class Decide(unittest.TestCase):
    """The pure function, for the header parsing edge cases."""

    def test_host_strips_port_and_case(self):
        self.assertEqual(access.host_of([(b"host", b"LocalHost:8787")]), "localhost")
        self.assertEqual(access.host_of([(b"host", b"[::1]:8787")]), "[::1]")
        self.assertEqual(access.host_of([]), "")

    def test_missing_host_is_not_local(self):
        ok, why = access.decide([])
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
