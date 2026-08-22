"""Controlled verification of pinned official vendor sources.

This command hashes live vendor bytes and records an append-only audit event.
It never changes a pinned hash, source disposition, or compiled pack.
"""
import hashlib
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

from lib import certification_spines, compiler


MAX_SOURCE_BYTES = 25 * 1024 * 1024
USER_AGENT = "Waypoint-Certification-Compiler/1.0 source-integrity-check"


class VerificationError(RuntimeError):
    pass


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _trusted_https(url, allowed_hosts):
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.hostname.lower() in allowed_hosts
    )


class _TrustedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts):
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _trusted_https(newurl, self.allowed_hosts):
            raise VerificationError(
                f"refusing redirect to untrusted official-source URL: {newurl}"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(opener, request, timeout):
    if opener is None:
        raise AssertionError("opener must be initialized")
    if hasattr(opener, "open"):
        return opener.open(request, timeout=timeout)
    return opener(request, timeout=timeout)


def verify_official_sources(conn, manifest_path=None, opener=None, timeout=30):
    manifest = compiler.load_manifest(manifest_path)
    allowed_hosts = {host.lower() for host in manifest["official_hosts"]}
    if opener is None:
        opener = urllib.request.build_opener(_TrustedRedirectHandler(allowed_hosts))

    checked_at = now_iso()
    results = []
    for source in manifest["sources"]:
        if source["source_type"] not in {"official_objectives", "official_vendor"}:
            continue
        requested_url = source.get("source_url") or ""
        expected = source["source_sha256"].lower()
        registry = conn.execute(
            "SELECT id FROM source_registry WHERE source_key = ?",
            (source["source_key"],),
        ).fetchone()
        if not registry:
            raise VerificationError(
                f"source '{source['source_key']}' is not compiled into the registry"
            )

        status = "error"
        observed = None
        final_url = None
        error = None
        etag = None
        last_modified = None
        content_length = None
        try:
            if not _trusted_https(requested_url, allowed_hosts):
                raise VerificationError(
                    f"official source URL is not trusted HTTPS: {requested_url}"
                )
            request = urllib.request.Request(
                requested_url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*;q=0.1"},
            )
            with _open(opener, request, timeout) as response:
                final_url = response.geturl()
                if not _trusted_https(final_url, allowed_hosts):
                    raise VerificationError(
                        f"final URL is not trusted HTTPS: {final_url}"
                    )
                headers = response.headers
                etag = headers.get("ETag")
                last_modified = headers.get("Last-Modified")
                declared_length = headers.get("Content-Length")
                if declared_length:
                    content_length = int(declared_length)
                    if content_length > MAX_SOURCE_BYTES:
                        raise VerificationError(
                            f"source exceeds {MAX_SOURCE_BYTES} byte limit"
                        )
                digest = hashlib.sha256()
                total = 0
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_SOURCE_BYTES:
                        raise VerificationError(
                            f"source exceeds {MAX_SOURCE_BYTES} byte limit"
                        )
                    digest.update(chunk)
                content_length = total
                observed = digest.hexdigest()
                status = "match" if observed == expected else "drift"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        conn.execute(
            "INSERT INTO source_verification_runs("
            "source_id, expected_sha256, observed_sha256, requested_url, final_url, "
            "status, http_etag, http_last_modified, content_length, checked_at, error, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                registry["id"], expected, observed, requested_url, final_url,
                status, etag, last_modified, content_length, checked_at, error,
                checked_at,
            ),
        )
        if status == "match":
            conn.execute(
                "UPDATE source_registry SET verified_at = ?, updated_at = ? WHERE id = ?",
                (checked_at, checked_at, registry["id"]),
            )
        results.append({
            "source_key": source["source_key"],
            "status": status,
            "expected_sha256": expected,
            "observed_sha256": observed,
            "requested_url": requested_url,
            "final_url": final_url,
            "checked_at": checked_at,
            "error": error,
        })

    conn.commit()
    return {
        "certification_code": manifest["certification_code"],
        "checked_at": checked_at,
        "status": (
            "match" if results and all(r["status"] == "match" for r in results)
            else "review_required"
        ),
        "sources": results,
    }


def verify_spine_sources(certification_id=None, opener=None, timeout=30):
    """Verify pinned official documents for the shared certification registry.

    This is deliberately read-only.  A changed hash or a page-only source is
    reported for operator review; the registry is never rewritten from network
    content.
    """
    spines = certification_spines.list_spines()
    if certification_id:
        spines = [item for item in spines if item["id"] == certification_id]
        if not spines:
            raise VerificationError(
                f"unknown certification spine: {certification_id}"
            )
    sources = [
        (certification, exam, exam["official_source"])
        for certification in spines
        for exam in certification["exams"]
    ]
    allowed_hosts = {
        urlparse(source["url"]).hostname.lower()
        for _, _, source in sources
        if urlparse(source["url"]).hostname
    }
    if opener is None:
        opener = urllib.request.build_opener(_TrustedRedirectHandler(allowed_hosts))

    checked_at = now_iso()
    results = []
    for certification, exam, source in sources:
        requested_url = source["url"]
        expected = source.get("sha256")
        if source["verification_status"] != "hash_verified":
            results.append({
                "certification_id": certification["id"],
                "exam_code": exam["code"],
                "status": "manual_review_required",
                "expected_sha256": expected,
                "observed_sha256": None,
                "requested_url": requested_url,
                "final_url": None,
                "checked_at": checked_at,
                "error": "registry source is not yet pinned to a document hash",
            })
            continue

        status = "error"
        observed = None
        final_url = None
        error = None
        try:
            if not _trusted_https(requested_url, allowed_hosts):
                raise VerificationError(
                    f"official source URL is not trusted HTTPS: {requested_url}"
                )
            request = urllib.request.Request(
                requested_url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*;q=0.1"},
            )
            with _open(opener, request, timeout) as response:
                final_url = response.geturl()
                if not _trusted_https(final_url, allowed_hosts):
                    raise VerificationError(f"final URL is not trusted HTTPS: {final_url}")
                declared_length = response.headers.get("Content-Length")
                if declared_length and int(declared_length) > MAX_SOURCE_BYTES:
                    raise VerificationError(
                        f"source exceeds {MAX_SOURCE_BYTES} byte limit"
                    )
                digest = hashlib.sha256()
                total = 0
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_SOURCE_BYTES:
                        raise VerificationError(
                            f"source exceeds {MAX_SOURCE_BYTES} byte limit"
                        )
                    digest.update(chunk)
                observed = digest.hexdigest()
                status = "match" if observed == expected else "drift"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        results.append({
            "certification_id": certification["id"],
            "exam_code": exam["code"],
            "status": status,
            "expected_sha256": expected,
            "observed_sha256": observed,
            "requested_url": requested_url,
            "final_url": final_url,
            "checked_at": checked_at,
            "error": error,
        })

    return {
        "registry_version": certification_spines.load_registry()["registry_version"],
        "checked_at": checked_at,
        "status": (
            "match" if results and all(item["status"] == "match" for item in results)
            else "review_required"
        ),
        "sources": results,
    }
