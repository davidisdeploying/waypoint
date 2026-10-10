#!/usr/bin/env python3
"""Serve Waypoint and proxy Study Library behind the same private origin."""

import http.client
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

try:
    from .state_store import (
        MAX_STATE_BYTES,
        StateConflictError,
        StateValidationError,
        WaypointStateStore,
    )
except ImportError:
    from state_store import (
        MAX_STATE_BYTES,
        StateConflictError,
        StateValidationError,
        WaypointStateStore,
    )


ROOT = Path(__file__).resolve().parent.parent
V2_DIST = ROOT / "frontend" / "dist"
HOST = os.environ.get("WAYPOINT_HOST", "127.0.0.1")
PORT = int(os.environ.get("WAYPOINT_PORT", "8790"))
STATE_DB = Path(os.environ.get("WAYPOINT_STATE_DB", ROOT / "data" / "waypoint.db"))
STUDY_LIBRARY_HOST = os.environ.get("STUDY_LIBRARY_HOST", "127.0.0.1")
STUDY_LIBRARY_PORT = int(os.environ.get("STUDY_LIBRARY_PORT", "8840"))
STUDY_LIBRARY_ENTRY = "/v2/study"
MAX_PROXY_BODY_BYTES = 1_000_000
# waypointjourney.example.com is served by this same process but is NOT behind Cloudflare
# Access, so it is the one hostname where an arbitrary internet client reaches the origin
# directly. The same-origin CSRF check is a browser defense, not authentication -- Origin and
# Host are both attacker-controlled in a direct request -- so this host is restricted here, at
# the gateway, to exactly the read-only GETs SharedJourneyPage needs. Everything else, and every
# POST, is 404 on this hostname regardless of what the authenticated app is allowed to do.
PUBLIC_SHARE_HOST_PREFIX = "waypointjourney"
PUBLIC_SHARE_API_ALLOWLIST = frozenset({
    "/api/v2/waypoint/state",
    "/api/v2/study/timeline",
    "/api/v2/study/study-goal",
    "/api/v2/study/daily-session",
})
LEGACY_APP_REDIRECTS = {
    "/": "/v2/",
    "/study": "/v2/study",
    "/credentials": "/v2/journey",
    "/plan": "/v2/journey",
    "/more": "/v2/more",
    "/study-library": "/v2/study",
    "/study-library/": "/v2/study",
}


def _read_study_token():
    path = os.environ.get("WAYPOINT_STUDY_TOKEN_FILE", "")
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"cannot read Waypoint Study token: {path}") from exc


STUDY_LIBRARY_TOKEN = _read_study_token()


DEFAULT_UPSTREAM_TIMEOUT = 5
# Endpoints that do real work before they can answer. Anything absent gets
# DEFAULT_UPSTREAM_TIMEOUT, which is right for a read but truncates a slow
# write: submitting a knowledge check spent 5.8s building remediation readings
# for a 4-gap attempt, so the proxy returned 502 while the upstream went on to
# commit successfully. The client saw a failure for work that had landed, and
# retrying returned "already submitted". Timing out mid-write is the failure
# mode to design against, so a slow write gets room rather than a truncation.
SLOW_UPSTREAM_TIMEOUTS = (
    (lambda path: path == "/api/coach/ask", 100),
    (
        lambda path: path.startswith("/api/diagnostics/attempts/")
        and path.endswith("/submit"),
        60,
    ),
)


def _upstream_timeout(upstream_path):
    path = upstream_path.split("?", 1)[0]
    for matches, timeout in SLOW_UPSTREAM_TIMEOUTS:
        if matches(path):
            return timeout
    return DEFAULT_UPSTREAM_TIMEOUT


class Handler(BaseHTTPRequestHandler):
    server_version = "Waypoint/2"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def _headers(self, status, content_type, length, extra_headers=None):
        extra_headers = extra_headers or {}
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", extra_headers.get("Cache-Control", "no-store"))
        for name, value in extra_headers.items():
            if name == "Cache-Control":
                continue
            self.send_header(name, value)
        self.end_headers()

    def _send(self, status, content_type, body, extra_headers=None):
        self._headers(status, content_type, len(body), extra_headers=extra_headers)
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body)

    def _redirect(self, location):
        self._send(
            302,
            "text/plain; charset=utf-8",
            b"",
            extra_headers={"Location": location, "Cache-Control": "no-store"},
        )

    def _same_origin_mutation(self):
        if self.headers.get("X-Waypoint-CSRF") != "1":
            return False
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        referer = self.headers.get("Referer")
        if origin:
            return urlsplit(origin).netloc == host
        if referer:
            return urlsplit(referer).netloc == host
        return False

    def _is_public_share_host(self):
        host = self.headers.get("Host", "").split(":")[0].strip().lower()
        return host.startswith(PUBLIC_SHARE_HOST_PREFIX)

    def _upstream_path(self):
        parsed = urlsplit(self.path)
        if parsed.path.startswith("/api/v2/study/"):
            path = "/api/" + parsed.path.removeprefix("/api/v2/study/")
        elif parsed.path == "/api/v2/waypoint/state":
            path = "/api/waypoint/state"
        elif parsed.path.startswith(("/api/", "/css/", "/js/")):
            path = parsed.path
        else:
            return None
        return path + (f"?{parsed.query}" if parsed.query else "")

    def _proxy_upstream(self, rewrite_summary=False, trusted_mutation=False):
        upstream_path = self._upstream_path()
        if upstream_path is None:
            self._send(404, "text/plain; charset=utf-8", b"not found\n")
            return

        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            self._send(400, "application/json; charset=utf-8", b'{"error":"invalid content length"}')
            return
        if length < 0 or length > MAX_PROXY_BODY_BYTES:
            self._send(413, "application/json; charset=utf-8", b'{"error":"request body too large"}')
            return
        body = self.rfile.read(length) if length and self.command == "POST" else None
        headers = {
            "Accept": self.headers.get("Accept", "*/*"),
            "Host": self.headers.get("Host", ""),
        }
        if STUDY_LIBRARY_TOKEN:
            headers["X-Waypoint-Service-Token"] = STUDY_LIBRARY_TOKEN
        if trusted_mutation:
            headers["X-Waypoint-Trusted-Mutation"] = "1"
        for name in ("Content-Type", "Origin", "Referer", "X-CSRF-Token"):
            value = self.headers.get(name)
            if value:
                headers[name] = value

        timeout = _upstream_timeout(upstream_path)
        connection = http.client.HTTPConnection(
            STUDY_LIBRARY_HOST, STUDY_LIBRARY_PORT, timeout=timeout
        )
        try:
            connection.request(self.command, upstream_path, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            content_type = response.getheader("Content-Type") or "application/octet-stream"
            status = response.status
            if rewrite_summary and status == 200:
                payload = json.loads(response_body.decode("utf-8"))
                payload["study_library_url"] = STUDY_LIBRARY_ENTRY
                response_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            self._send(status, content_type, response_body)
        except (OSError, http.client.HTTPException, UnicodeDecodeError, json.JSONDecodeError):
            self._send(
                502,
                "application/json; charset=utf-8",
                b'{"error":"Study Library is temporarily unavailable"}',
            )
        finally:
            connection.close()

    def _serve_static(self):
        path = urlsplit(self.path).path
        if path == "/v2" or path.startswith("/v2/"):
            relative = path.removeprefix("/v2").lstrip("/")
            candidate = (V2_DIST / relative).resolve() if relative else V2_DIST / "index.html"
            is_v2_shell = not relative or "." not in Path(relative).name or not candidate.is_file()
            target = V2_DIST / "index.html" if is_v2_shell else candidate
            if V2_DIST not in target.resolve().parents or not target.is_file():
                self._send(404, "text/plain; charset=utf-8", b"Waypoint 2.0 is not built\n")
                return
            body = target.read_bytes()
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            extra_headers = {
                "X-Waypoint-App" if is_v2_shell else "X-Waypoint-Asset": "2",
            }
            if self._is_public_share_host():
                extra_headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
            if not is_v2_shell and "/assets/" in path:
                extra_headers["Cache-Control"] = "private, max-age=31536000, immutable"
            if target.name == "sw.js":
                extra_headers["Service-Worker-Allowed"] = "/v2/"
                extra_headers["Cache-Control"] = "no-cache"
            self._send(200, content_type, body, extra_headers=extra_headers)
            return
        target = (ROOT / path.lstrip("/")).resolve()
        if ROOT not in target.parents or not target.is_file():
            self._send(404, "text/plain; charset=utf-8", b"not found\n")
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        extra_headers = {}
        if target.name == "sw.js":
            extra_headers["Service-Worker-Allowed"] = "/"
        self._send(200, content_type, body, extra_headers=extra_headers)

    def _state_get(self):
        result = self.server.state_store.get()
        if result is None:
            self._send_json(404, {"schema_version": 1, "state": None})
            return
        self._send_json(200, result)

    def _state_post(self):
        if not self._same_origin_mutation():
            self._send_json(403, {"error": "same-origin CSRF check failed"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            self._send_json(400, {"error": "invalid content length"})
            return
        if length <= 0 or length > MAX_STATE_BYTES + 20_000:
            self._send_json(413, {"error": "request body too large"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise StateValidationError("payload must be an object")
            result = self.server.state_store.save(
                payload.get("state"),
                payload.get("expected_revision"),
                migration_id=payload.get("migration_id"),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, StateValidationError) as error:
            self._send_json(400, {"error": str(error)})
            return
        except StateConflictError as error:
            current = self.server.state_store.get()
            self._send_json(
                409,
                {
                    "error": str(error),
                    "current_revision": current["revision"] if current else 0,
                },
            )
            return
        self._send_json(200, result)

    def _dispatch(self):
        path = urlsplit(self.path).path
        if (
            self._is_public_share_host()
            and path.startswith("/api/")
            and path not in PUBLIC_SHARE_API_ALLOWLIST
        ):
            self._send(404, "text/plain; charset=utf-8", b"not found\n")
            return
        if path in LEGACY_APP_REDIRECTS:
            self._redirect(LEGACY_APP_REDIRECTS[path])
        elif path == "/api/waypoint/state":
            self._state_get()
        elif path == "/api/waypoint/summary":
            self._proxy_upstream(rewrite_summary=True)
        elif self._upstream_path() is not None:
            self._proxy_upstream()
        else:
            self._serve_static()

    def do_GET(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch()

    def do_POST(self):
        path = urlsplit(self.path).path
        if self._is_public_share_host():
            # No mutation of any kind is reachable from the unauthenticated hostname.
            self._send(404, "text/plain; charset=utf-8", b"not found\n")
            return
        if path == "/api/waypoint/state":
            self._state_post()
        elif path == "/api/v2/waypoint/state":
            if not self._same_origin_mutation():
                self._send_json(403, {"error": "same-origin CSRF check failed"})
                return
            self._proxy_upstream(trusted_mutation=True)
        elif path.startswith("/api/"):
            self._proxy_upstream()
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found\n")


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.state_store = WaypointStateStore(STATE_DB)
    print(f"Waypoint serving on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
