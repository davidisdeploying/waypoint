#!/usr/bin/env python3
"""Starts the real server on an ephemeral test port against a throwaway DB,
ingests fixture data, and hits key routes + static assets over real HTTP.

Exit code 0 = all checks passed. Prints each check's outcome.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def request(url, method="GET", data=None, headers=None):
    headers = headers or {}
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8"))
        except Exception:
            payload = None
        return e.code, payload


def request_raw(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main():
    failures = []

    def check(label, cond):
        status = "PASS" if cond else "FAIL"
        print(f"[{status}] {label}")
        if not cond:
            failures.append(label)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "smoke.db"
        port = free_port()
        env = dict(os.environ)
        env["STUDY_LIBRARY_DB"] = str(db_path)
        env["STUDY_LIBRARY_PORT"] = str(port)
        env["STUDY_LIBRARY_HOST"] = "127.0.0.1"

        # Seed via the fixture-based ingest so the smoke test has no dependency
        # on the real vault corpus being present on this machine.
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        from lib import db as db_mod
        from ingest.ingest import ingest_all
        from ingest.plan import seed_plan
        from ingest.diagnostics_importer import import_questions, seed_diagnostic_scopes
        from fixtures import build_all_sources, build_diagnostics_practice_source

        conn = db_mod.connect(db_path)
        db_mod.init_db(conn)
        sources = build_all_sources(Path(tmp) / "sources")
        ingest_all(conn, sources)
        seed_plan(conn)

        # Diagnostics: ingest the aplus-practice-tests-slugged fixture (paired
        # with the domains the review-guide fixture already seeded above),
        # import its questions, seed scopes, then pad one domain's pool with
        # synthetic questions so it clears min_valid_questions/enabled=1 for
        # a real end-to-end diagnostic flow below.
        diag_src = build_diagnostics_practice_source(Path(tmp) / "diag-sources")
        ingest_all(conn, [diag_src])
        import_questions(conn)
        seed_diagnostic_scopes(conn)
        scope_row = conn.execute(
            "SELECT id, exam_id, domain_id FROM diagnostic_scopes WHERE slug = 'aplus-week1-domain-1'"
        ).fetchone()
        if scope_row:
            ts = "2026-01-01T00:00:00+00:00"
            for i in range(20):
                conn.execute(
                    "INSERT INTO question_bank(stable_id, exam_id, domain_id, objective_id, mapping_granularity, "
                    "question_book_slug, question_section_id, question_number, answer_book_slug, answer_section_id, "
                    "prompt, options_json, correct_answers_json, explanation, provenance, content_hash, "
                    "requires_figure, critical, active, created_at, updated_at) "
                    "VALUES (?, ?, ?, NULL, 'domain', 'aplus-practice-tests', NULL, ?, 'aplus-practice-tests', NULL, "
                    "?, ?, '[0]', 'exp', 'prov', ?, 0, 0, 1, ?, ?)",
                    (f"smoke-test-{i}", scope_row["exam_id"], scope_row["domain_id"], 6000 + i,
                     f"Smoke Q{i}?", json.dumps(["a", "b", "c", "d"]), f"smoke-hash-{i}", ts, ts),
                )
            conn.execute(
                "UPDATE diagnostic_scopes SET enabled = 1, question_target = 20, min_valid_questions = 2 WHERE id = ?",
                (scope_row["id"],),
            )
            conn.commit()
        diag_scope_id = scope_row["id"] if scope_row else None
        conn.close()

        proc = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "app.py")],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.time() + 10
            up = False
            while time.time() < deadline:
                try:
                    status, _ = request(base + "/api/health")
                    up = status == 200
                    break
                except (urllib.error.URLError, ConnectionRefusedError):
                    time.sleep(0.2)
            check("server started and /api/health responds", up)
            if not up:
                print(proc.stdout.read().decode("utf-8", "replace"))
                return 1

            status, body = request(base + "/api/health")
            check("health status ok", status == 200 and body.get("status") == "ok")

            status, raw = request_raw(base + "/")
            check("index.html served", status == 200 and b"Study Library" in raw)

            status, raw = request_raw(base + "/js/app.js")
            check("app.js served", status == 200 and b"function" in raw)

            status, body = request(base + "/api/dashboard")
            check("dashboard loads", status == 200 and "readiness_label" in body)

            status, body = request(base + "/api/books")
            check("books lists 4 fixture books (3 core + diagnostics practice)",
                  status == 200 and len(body.get("books", [])) == 4)

            status, body = request(base + "/api/search?q=devices")
            check("search returns results with citations", status == 200 and body["results"] and "stable_id" in body["results"][0])

            status, body = request(base + "/api/objectives")
            check("objectives list non-empty", status == 200 and len(body.get("objectives", [])) > 0)

            status, body = request(base + "/api/mastery-map?exam=220-1201")
            check(
                "mastery map keeps objective and domain evidence separate",
                status == 200
                and body.get("exams", [{}])[0].get("code") == "220-1201"
                and "not presented as exact objective mastery" in body.get("evidence_note", ""),
            )

            status, body = request(base + "/api/plan")
            check("plan has 12 weeks", status == 200 and len(body.get("weeks", [])) == 12)

            status, body = request(base + "/api/waypoint/summary")
            check("waypoint summary has schema_version", status == 200 and body.get("schema_version"))

            # Mutation without CSRF must be rejected.
            status, body = request(base + "/api/sessions", method="POST",
                                    data={"occurred_at": "2026-01-01T00:00:00Z", "duration_minutes": 30})
            check("mutation without CSRF token rejected (403)", status == 403)

            status, body = request(base + "/api/csrf-token")
            token = body.get("csrf_token")
            check("csrf token issued", status == 200 and bool(token))

            status, body = request(
                base + "/api/sessions", method="POST",
                data={"occurred_at": "2026-01-01T00:00:00Z", "duration_minutes": 30},
                headers={"X-CSRF-Token": token},
            )
            check("mutation with CSRF token accepted (201)", status == 201)

            status, body = request(base + "/api/export")
            check("export has schema_version + plan", status == 200 and body.get("schema_version") and body.get("plan"))
            check("export includes diagnostic_scopes/attempts", "diagnostic_scopes" in body and "diagnostic_attempts" in body)

            # --- Diagnostics flow ------------------------------------------------
            status, body = request(base + "/api/diagnostics/scopes")
            check("diagnostics scopes list loads", status == 200 and len(body.get("scopes", [])) > 0)

            if diag_scope_id:
                status, body = request(base + f"/api/diagnostics/scopes/{diag_scope_id}/start", method="POST",
                                        data={"mode": "diagnostic"})
                check("diagnostic start rejected without CSRF (403)", status == 403)

                status, attempt = request(
                    base + f"/api/diagnostics/scopes/{diag_scope_id}/start", method="POST",
                    data={"mode": "diagnostic"}, headers={"X-CSRF-Token": token},
                )
                check("diagnostic attempt starts (201)", status == 201)
                check("in-progress attempt redacts correct answers", attempt.get("answers_redacted") is True
                      and "correct_answers" not in attempt["responses"][0])

                status, fetched = request(base + f"/api/diagnostics/attempts/{attempt['id']}")
                check("GET attempt still redacted while in progress", fetched.get("answers_redacted") is True)

                # Answer half correctly, half wrong, to force a fail with gaps.
                responses = []
                for i, r in enumerate(attempt["responses"]):
                    correct = [0]
                    selected = correct if i < 10 else [1]
                    responses.append({"question_id": r["question_id"], "selected": selected, "confidence": "high"})
                status, result = request(
                    base + f"/api/diagnostics/attempts/{attempt['id']}/submit", method="POST",
                    data={"responses": responses}, headers={"X-CSRF-Token": token},
                )
                check("submit accepted (200)", status == 200)
                check("failing attempt reports gaps with non-practice citations",
                      not result.get("passed") and len(result.get("gaps", [])) > 0
                      and all(rd["book_slug"] != "aplus-practice-tests"
                              for g in result["gaps"] for rd in g["readings"]))

                status, again = request(
                    base + f"/api/diagnostics/attempts/{attempt['id']}/submit", method="POST",
                    data={"responses": responses}, headers={"X-CSRF-Token": token},
                )
                check("double submit rejected (409)", status == 409)

                for g in result.get("gaps", []):
                    status, _ = request(base + f"/api/remediation/{g['remediation_id']}", method="POST",
                                         data={}, headers={"X-CSRF-Token": token})
                if result.get("gaps"):
                    check("mark-reviewed accepted (200)", status == 200)

                status, retest = request(
                    base + f"/api/diagnostics/scopes/{diag_scope_id}/start", method="POST",
                    data={"mode": "retest"}, headers={"X-CSRF-Token": token},
                )
                check("retest available after all gaps reviewed (201)", status == 201)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    if failures:
        print(f"\n{len(failures)} check(s) failed: {failures}")
        return 1
    print("\nAll smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
