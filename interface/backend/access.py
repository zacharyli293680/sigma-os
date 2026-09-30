#!/usr/bin/env python3
"""
access.py — who may reach the interface from off this machine.

The backend still binds to loopback and nothing about that changed. What did
change (2026-09-30) is that `tailscale serve` now proxies port 8787 to the
tailnet, so a request can arrive from a phone. Tailscale is the wall: only a
device signed in to Zach's tailnet can connect at all, and Serve stamps every
proxied request with `Tailscale-User-Login`, stripping any copy a client sent.
This module is the second lock behind that wall, so a misconfigured proxy — a
`tailscale funnel` run by mistake, a shared node, a rule that drifted — is
refused by the app itself rather than trusted.

The rule, stated once:

    a request whose Host is loopback is local and passes;
    any other Host must carry Tailscale-User-Login equal to the one
    login named in runtime/privacy.config.json, or it is refused.

Why Host rather than the peer address: Serve connects from 127.0.0.1 too, so
the socket cannot tell a proxied request from a local one. The Host header can
— a browser on this machine says `localhost:8787`, a proxied one says
`<node>.<tailnet>.ts.net`, and a Funnel request would say the same with no
login header. Forging a loopback Host requires reaching the socket directly,
which requires being on the machine, which is the existing boundary.

The allowed login lives in `privacy.config.json` beside `model_allow` because
that file already holds the vault's trust decisions and is gitignored like
every config that names a person. A missing or unreadable config means **no
remote login is allowed** — the failure direction is over-blocking, which is
loud, never under-blocking, which is silent. Same shape as the model boundary.

Pure ASGI rather than `BaseHTTPMiddleware` on purpose: the conversation and
the tutor stream over SSE, and the base class buffers a body it did not write.
This one either passes the scope through untouched or answers 403 itself.
"""
import json
from functools import lru_cache
from pathlib import Path

_RUNTIME = Path(__file__).resolve().parents[2] / "runtime"

LOGIN_HEADER = b"tailscale-user-login"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")


@lru_cache(maxsize=1)
def remote_login() -> str:
    """The one login allowed through the tailnet, lower-cased; "" if none is
    configured. Cached like the model boundary: the interface reads its config
    at startup, and `sigma ui` is restarted after an edit."""
    try:
        cfg = json.loads((_RUNTIME / "privacy.config.json").read_text(encoding="utf-8"))
        return str(cfg.get("remote_login", "")).strip().lower()
    except Exception:
        return ""


def host_of(headers) -> str:
    """The Host header, lower-cased, without its port. IPv6 literals keep their
    brackets so `[::1]` compares as one token."""
    for k, v in headers:
        if k == b"host":
            h = v.decode("latin-1").strip().lower()
            if h.startswith("["):
                lit, _, rest = h.partition("]")
                # Only a port may follow the bracket; anything else is not a
                # host literal and must not compare equal to one.
                if rest and not rest.startswith(":"):
                    return h
                return lit + "]"
            return h.split(":")[0]
    return ""


def login_of(headers) -> str:
    for k, v in headers:
        if k == LOGIN_HEADER:
            return v.decode("latin-1").strip().lower()
    return ""


def decide(headers) -> tuple:
    """(allowed, reason). Reason is empty when allowed; otherwise it is the one
    line the log carries, which never echoes a login it refused — a log that
    prints every wrong guess is a log that collects them."""
    host = host_of(headers)
    if host in LOCAL_HOSTS:
        return True, ""
    login = login_of(headers)
    if not login:
        return False, f"no tailscale login on host {host!r}"
    allowed = remote_login()
    if not allowed:
        return False, f"remote login not configured; refused {host!r}"
    if login != allowed:
        return False, f"login not allowed on host {host!r}"
    return True, ""


class RemoteAccess:
    """ASGI middleware: the rule above, applied to every HTTP request — the
    API, the SSE streams and the static dashboard alike — before any router
    or mount sees it. Non-HTTP scopes (lifespan) pass through."""

    def __init__(self, app, log=None):
        self.app = app
        self.log = log or (lambda msg: None)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        ok, why = decide(scope.get("headers", ()))
        if ok:
            return await self.app(scope, receive, send)
        self.log(f"refused {scope.get('method', '?')} {scope.get('path', '?')}: {why}")
        body = json.dumps({"error": "forbidden",
                           "fix": "reach Sigma from a device on the tailnet, "
                                  "as the login named in privacy.config.json"}).encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
