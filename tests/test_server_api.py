import http.client
import json
import re
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import ops.server as server_module
from ops.server import Handler
from ops.state_store import WaypointStateStore


def valid_state():
    return {
        "meta": {"name": "David", "startDate": "2026-09-01"},
        "certs": [
            {
                "id": "aplus",
                "order": 1,
                "name": "CompTIA A+",
                "kind": "CompTIA",
                "code": "220-1201 / 220-1202",
                "exam": "",
                "pass": "",
                "status": "todo",
                "price": 506,
                "cu": 8,
                "wlo": 5,
                "whi": 6,
                "started": "",
                "actualHours": None,
                "estHoursLow": 140,
                "estHoursHigh": 200,
            }
        ],
        "courses": [],
        "log": [],
        "studyEndpoint": "/api/waypoint/summary",
        "studySummary": None,
        "studySummaryReceivedAt": None,
    }


class ServerApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.state_store = WaypointStateStore(
            Path(self.tempdir.name) / "waypoint.db"
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tempdir.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        request_headers = {"Host": f"127.0.0.1:{self.port}"}
        request_headers.update(headers or {})
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        payload = response.read()
        result = (response.status, dict(response.getheaders()), payload)
        connection.close()
        return result

    def post_state(self, revision, state=None, extra_headers=None):
        payload = json.dumps(
            {"expected_revision": revision, "state": state or valid_state()}
        ).encode()
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
            "Origin": f"http://127.0.0.1:{self.port}",
            "X-Waypoint-CSRF": "1",
        }
        headers.update(extra_headers or {})
        return self.request("POST", "/api/waypoint/state", payload, headers)

    def test_state_lifecycle_and_conflict(self):
        status, _, body = self.request("GET", "/api/waypoint/state")
        self.assertEqual(status, 404)
        self.assertIsNone(json.loads(body)["state"])

        status, _, body = self.post_state(0)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["revision"], 1)

        status, _, body = self.request("GET", "/api/waypoint/state")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["state"]["meta"]["name"], "David")

        status, _, body = self.post_state(0)
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["current_revision"], 1)

    def test_state_mutation_requires_same_origin_csrf(self):
        payload = json.dumps(
            {"expected_revision": 0, "state": valid_state()}
        ).encode()
        status, _, _ = self.request(
            "POST",
            "/api/waypoint/state",
            payload,
            {"Content-Type": "application/json", "Content-Length": str(len(payload))},
        )
        self.assertEqual(status, 403)

        status, _, _ = self.post_state(
            0, extra_headers={"Origin": "https://attacker.example"}
        )
        self.assertEqual(status, 403)

    def test_legacy_app_routes_redirect_to_guided_pwa(self):
        status, headers, body = self.request("GET", "/study")
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/v2/study")
        self.assertEqual(body, b"")

        status, headers, _ = self.request("GET", "/study-library/#next")
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/v2/study")

        status, headers, _ = self.request("GET", "/sw.js")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Service-Worker-Allowed"), "/")

    def test_v2_shell_routes_and_assets_are_marked(self):
        status, headers, body = self.request("GET", "/v2/study")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Waypoint-App"), "2")
        self.assertIn(b'id="root"', body)
        self.assertIn(b'href="/v2/favicon.ico"', body)
        self.assertIn(b"/v2/apple-touch-icon-dark.png?v=1", body)

        asset_match = re.search(rb'src="(/v2/assets/[^"]+\.js)"', body)
        self.assertIsNotNone(asset_match)
        status, headers, _ = self.request("GET", asset_match.group(1).decode())
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Waypoint-Asset"), "2")
        self.assertIn("immutable", headers.get("Cache-Control", ""))

        status, headers, body = self.request("GET", "/v2/sw.js")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Service-Worker-Allowed"), "/v2/")
        self.assertIn(b"waypoint-v2", body)

        for path in (
            "/favicon.ico",
            "/v2/favicon.ico",
            "/v2/apple-touch-icon-dark.png",
            "/v2/icon-192-dark.png",
            "/v2/icon-512-dark.png",
        ):
            status, headers, asset = self.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertTrue(asset, path)
            if path.startswith("/v2/"):
                self.assertEqual(headers.get("X-Waypoint-Asset"), "2")

    def test_legacy_state_contract_remains_available_for_rollback(self):
        status, _, body = self.request("GET", "/api/waypoint/state")
        self.assertEqual(status, 404)
        payload = json.loads(body)
        self.assertEqual(payload["schema_version"], 1)
        self.assertIsNone(payload["state"])

    def test_gateway_injects_internal_service_credential(self):
        class UpstreamHandler(BaseHTTPRequestHandler):
            received_token = None
            received_trusted_mutation = None

            def log_message(self, _fmt, *_args):
                pass

            def do_GET(self):
                type(self).received_token = self.headers.get("X-Waypoint-Service-Token")
                body = b'{"books":[]}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                type(self).received_token = self.headers.get("X-Waypoint-Service-Token")
                type(self).received_trusted_mutation = self.headers.get(
                    "X-Waypoint-Trusted-Mutation"
                )
                request_body = self.rfile.read(int(self.headers["Content-Length"]))
                payload = json.loads(request_body)
                body = json.dumps({
                    "schema_version": 1,
                    "revision": payload["expected_revision"] + 1,
                    "state": payload["state"],
                    "updated_at": "2026-07-30T00:00:00Z",
                    "migration_id": None,
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        original = (
            server_module.STUDY_LIBRARY_HOST,
            server_module.STUDY_LIBRARY_PORT,
            server_module.STUDY_LIBRARY_TOKEN,
        )
        server_module.STUDY_LIBRARY_HOST = "127.0.0.1"
        server_module.STUDY_LIBRARY_PORT = upstream.server_address[1]
        server_module.STUDY_LIBRARY_TOKEN = "private-test-token"
        try:
            status, _, body = self.request("GET", "/api/v2/study/books")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), {"books": []})
            self.assertEqual(UpstreamHandler.received_token, "private-test-token")

            payload = json.dumps({
                "expected_revision": 0,
                "state": valid_state(),
            }).encode()
            status, _, body = self.request(
                "POST",
                "/api/v2/waypoint/state",
                payload,
                {
                    "Content-Type": "application/json",
                    "Content-Length": str(len(payload)),
                    "Origin": f"http://127.0.0.1:{self.port}",
                    "X-Waypoint-CSRF": "1",
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["revision"], 1)
            self.assertEqual(
                UpstreamHandler.received_trusted_mutation,
                "1",
            )
        finally:
            (
                server_module.STUDY_LIBRARY_HOST,
                server_module.STUDY_LIBRARY_PORT,
                server_module.STUDY_LIBRARY_TOKEN,
            ) = original
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=2)

    def test_public_share_host_cannot_mutate_state(self):
        # Regression: waypointjourney.* is not behind Cloudflare Access, and the same-origin
        # CSRF check is a browser defense -- Origin and Host are both attacker-controlled in a
        # direct request, so it passes trivially. Without a gateway-level block, a well-formed
        # POST from that hostname would overwrite real state.
        payload = json.dumps(
            {"expected_revision": 0, "state": valid_state()}
        ).encode()
        public_host = "waypointjourney.example.com"
        status, _, _ = self.request(
            "POST",
            "/api/waypoint/state",
            payload,
            {
                "Host": public_host,
                "Content-Type": "application/json",
                "Content-Length": str(len(payload)),
                "Origin": f"https://{public_host}",
                "X-Waypoint-CSRF": "1",
            },
        )
        self.assertEqual(status, 404)

        # The same request on the normal hostname still succeeds, so this is a
        # hostname restriction and not a broken mutation path.
        status, _, body = self.post_state(0)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["revision"], 1)

    def test_public_share_host_exposes_only_allowlisted_read_endpoints(self):
        public_host = "waypointjourney.example.com"
        headers = {"Host": public_host}

        # Endpoints the shared page does not need are not reachable at all, including
        # the whole generic study proxy and the legacy state route.
        for path in (
            "/api/v2/study/plan",
            "/api/v2/study/books",
            "/api/v2/study/analytics",
            "/api/v2/study/coach/ask",
            "/api/v2/study/daily-session/history",
            "/api/waypoint/state",
            "/api/waypoint/summary",
        ):
            status, _, _ = self.request("GET", path, headers=headers)
            self.assertEqual(status, 404, path)

        # The static app shell still serves on that hostname, so the page itself loads.
        status, headers_out, body = self.request("GET", "/v2/journey", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(headers_out.get("X-Waypoint-App"), "2")
        self.assertEqual(
            headers_out.get("X-Robots-Tag"), "noindex, nofollow, noarchive"
        )
        self.assertIn(b'id="root"', body)

        # An allowlisted path is not blocked by the host gate: it reaches the state
        # handler and returns its normal empty-store answer rather than a 404 from the gate.
        status, _, body = self.request(
            "GET", "/api/v2/waypoint/state", headers=headers
        )
        self.assertNotEqual(status, 404)

    def test_invalid_content_length_is_rejected(self):
        status, _, body = self.request(
            "POST",
            "/api/waypoint/state",
            b"",
            {
                "Content-Length": "not-a-number",
                "Origin": f"http://127.0.0.1:{self.port}",
                "X-Waypoint-CSRF": "1",
            },
        )
        self.assertEqual(status, 400)
        self.assertIn(b"invalid content length", body)


if __name__ == "__main__":
    unittest.main()
