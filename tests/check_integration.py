#!/usr/bin/env python3
"""
Integration check script for Waypoint Study Intelligence section.
Verifies live repo integrity, contract keys, JS syntax, validator logic,
certification IDs, clean git status, and manual test matrix.
"""

import sys
import os
import hashlib
import json
import re
import subprocess
import tempfile

WORKTREE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_REPO_PATH = os.environ.get("WAYPOINT_REPO_PATH", WORKTREE_DIR)


def check_live_repo():
    print("[1/8] Verifying production repository layout and tracked source...")
    live_index = os.path.join(LIVE_REPO_PATH, "index.html")
    if not os.path.exists(live_index):
        sys.exit(f"FAIL: Live index.html not found at {live_index}")

    with open(live_index, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()

    if not os.path.exists(os.path.join(LIVE_REPO_PATH, "ops", "server.py")):
        sys.exit("FAIL: Production proxy server is missing.")

    res = subprocess.run(["git", "-C", LIVE_REPO_PATH, "rev-parse", "HEAD"], capture_output=True, text=True)
    head = res.stdout.strip()
    if not head:
        sys.exit("FAIL: Could not resolve production repository HEAD.")

    res_status = subprocess.run(["git", "-C", LIVE_REPO_PATH, "status", "--porcelain"], capture_output=True, text=True)
    if res_status.stdout.strip() and os.environ.get("WAYPOINT_ALLOW_DIRTY") != "1":
        sys.exit(f"FAIL: Live repo is dirty!\n{res_status.stdout}")

    print(f"  ✓ Repository resolved at {head[:7]}; index SHA-256 {sha}.")


def check_worktree_contract():
    print("[2/8] Verifying integration section, controls, and contract keys in worktree index.html...")
    wt_index = os.path.join(WORKTREE_DIR, "index.html")
    with open(wt_index, "r", encoding="utf-8") as f:
        content = f.read()
        
    required_strings = [
        '<span class="sec-num">03</span><h2>Study intelligence</h2>',
        '<div class="metrics" data-route-section="dashboard"><div class="wrap"><div class="mgrid">',
        '<nav class="appnav" aria-label="Primary navigation">',
        'href="/study" data-route-link="study"',
        'href="/credentials" data-route-link="credentials"',
        'href="/plan" data-route-link="plan"',
        'href="/more" data-route-link="more"',
        'id="pwa-sync-state"',
        'id="btn-state-migrate"',
        "navigator.serviceWorker.register('/sw.js'",
        "fetch('/api/waypoint/state'",
        'class="brand-lockup"',
        'src="/assets/brand/waypoint-lockup.svg"',
        'href="/favicon.svg"',
        'href="/apple-touch-icon.png"',
        'href="/site.webmanifest"',
        'id="sec-study-intel"',
        'id="set-study-endpoint"',
        'id="set-study-endpoint-settings"',
        'id="btn-study-fetch"',
        'id="btn-study-file"',
        'id="file-study-import"',
        'id="study-status-bar"',
        'id="study-intel-content"',
        'schema_version',
        'certification_id',
        'current_exam',
        'current_week',
        'week_title',
        'next_task',
        'readiness_components',
        'weak_objectives',
        'practice_average_recent',
        'objective_coverage_pct',
        'plan_progress_pct',
        'study_library_url',
        'diagnostics',
        'current_gap_count',
        'current_scope',
        'diagnostic_checks_available',
        'diagnostic_checks_passed',
        'domain_mastery_pct',
        'domain_mastery_pct_label',
        'retention_due_count',
        'retention_due_next_at',
        'progress',
        'current_week_tasks',
        'study_minutes_last_7_days',
        'current_streak_days',
        'domain_mastery',
        'practice_trend',
        'adaptive_curriculum',
        'Adaptive ',
        'Progress and Mastery Evidence',
        'days after the knowledge check are provisional',
        'Knowledge Checks',
        'domain diagnostic mastery',
        'Focused review available in Study Library',
        'Optional knowledge check available before this section.',
        'Retention review due',
        'Open Study Next',
        'fetchStudySummary(S.studyEndpoint',
        '@media (max-width:640px)',
        'validateStudySummary',
        'fetchStudySummary',
        'importStudySummaryJSON',
        'renderStudyIntel',
        'displayWeekTitle'
        ,'id="study-coach-panel"'
        ,'id="study-coach-question"'
        ,'id="btn-study-coach-ask"'
        ,'data-coach-mode="today"'
        ,'data-coach-mode="gaps"'
        ,'data-coach-mode="practice"'
        ,'Claude Max subscription'
        ,'validateStudyCoachResponse'
        ,'runStudyCoach'
        ,'/api/coach/ask'
        ,'practice-question bank is excluded'
    ]
    
    for s in required_strings:
        if s not in content:
            sys.exit(f"FAIL: Missing required contract element/key '{s}' in worktree index.html")

    if "counselor-confirmed case" in content:
        sys.exit("FAIL: Waypoint falsely states that paired-course assumptions are counselor-confirmed.")
    if "paired-course assumption still needs counselor confirmation" not in content:
        sys.exit("FAIL: Pending counselor-confirmation disclosure is missing.")
            
    print("  ✓ All required section headers, control IDs, and contract keys present.")

    proxy_path = os.path.join(WORKTREE_DIR, "ops", "server.py")
    with open(proxy_path, "r", encoding="utf-8") as f:
        proxy_content = f.read()
    for required_proxy_source in (
        'STUDY_LIBRARY_ENTRY = "/v2/study"',
        'path.startswith(("/api/", "/css/", "/js/"))',
        '"X-CSRF-Token"',
        # Per-route upstream timeouts. The old contract pinned a single line,
        # 'timeout = 100 if upstream_path == "/api/coach/ask" else 5', which
        # gave every other endpoint 5s -- long enough for a read, but not for
        # submitting a knowledge check, which returned 502 while the upstream
        # went on to commit. What matters now is that slow writes declare a
        # timeout rather than inheriting the read default.
        "DEFAULT_UPSTREAM_TIMEOUT = 5",
        "def _upstream_timeout(upstream_path):",
        'path.endswith("/submit")',
        "timeout = _upstream_timeout(upstream_path)",
        "def do_POST",
        'LEGACY_APP_REDIRECTS = {',
        'path == "/api/waypoint/state"',
        'parsed.path == "/api/v2/waypoint/state"',
        '"X-Waypoint-Trusted-Mutation"',
        '"X-Waypoint-CSRF"',
        '"X-Waypoint-App"',
        '"Service-Worker-Allowed"',
        'parsed.path.startswith("/api/v2/study/")',
        'V2_DIST = ROOT / "frontend" / "dist"',
        '"/api/v2/waypoint/state"',
        '"X-Waypoint-Asset"',
    ):
        if required_proxy_source not in proxy_content:
            sys.exit(f"FAIL: Missing production proxy contract: {required_proxy_source}")

    required_brand_files = (
        "assets/brand/waypoint-lockup.svg",
        "assets/brand/waypoint-mark.svg",
        "assets/brand/waypoint-mark-cut.svg",
        "assets/brand/waypoint-mark-mono.svg",
        "assets/brand/waypoint-lockup-mono.svg",
        "assets/brand/waypoint-app-icon-dark.svg",
        "favicon.ico",
        "favicon.svg",
        "favicon-16.png",
        "favicon-32.png",
        "favicon-48.png",
        "apple-touch-icon.png",
        "apple-touch-icon-dark.png",
        "icon-192.png",
        "icon-192-dark.png",
        "icon-512.png",
        "icon-512-dark.png",
        "site.webmanifest",
        "sw.js",
        "ops/state_store.py",
        "ops/waypoint-backup.service",
        "ops/waypoint-backup.timer",
        "scripts/backup.py",
        "frontend/package.json",
        "frontend/pnpm-lock.yaml",
        "frontend/dist/index.html",
        "frontend/dist/sw.js",
        "docs/ARCHITECTURE-V2.md",
    )
    for relative_path in required_brand_files:
        if not os.path.isfile(os.path.join(WORKTREE_DIR, relative_path)):
            sys.exit(f"FAIL: Missing finalized Waypoint brand asset: {relative_path}")

    source_package_files = (
        "README.md",
        "waypoint-mark.svg",
        "waypoint-lockup.svg",
        "waypoint-mark-cut.svg",
        "waypoint-mark-mono.svg",
        "waypoint-lockup-mono.svg",
        "favicon.svg",
        "favicon-32.png",
        "favicon-16.png",
        "favicon-48.png",
        "apple-touch-icon.png",
        "icon-192.png",
        "icon-512.png",
    )
    source_package_dir = os.path.join(WORKTREE_DIR, "assets", "brand", "source-package")
    for filename in source_package_files:
        if not os.path.isfile(os.path.join(source_package_dir, filename)):
            sys.exit(f"FAIL: Missing original Waypoint source-package file: {filename}")

    deployed_asset_map = {
        "waypoint-mark.svg": "assets/brand/waypoint-mark.svg",
        "waypoint-lockup.svg": "assets/brand/waypoint-lockup.svg",
        "waypoint-mark-cut.svg": "assets/brand/waypoint-mark-cut.svg",
        "waypoint-mark-mono.svg": "assets/brand/waypoint-mark-mono.svg",
        "waypoint-lockup-mono.svg": "assets/brand/waypoint-lockup-mono.svg",
        "favicon.svg": "favicon.svg",
        "favicon-32.png": "favicon-32.png",
        "favicon-16.png": "favicon-16.png",
        "favicon-48.png": "favicon-48.png",
    }
    for source_filename, deployed_path in deployed_asset_map.items():
        with open(os.path.join(source_package_dir, source_filename), "rb") as source_file:
            source_bytes = source_file.read()
        with open(os.path.join(WORKTREE_DIR, deployed_path), "rb") as deployed_file:
            deployed_bytes = deployed_file.read()
        if source_bytes != deployed_bytes:
            sys.exit(
                f"FAIL: Deployed asset differs from original source package: {deployed_path}"
            )

    app_icons = {
        "apple-touch-icon.png": (180, 180),
        "apple-touch-icon-dark.png": (180, 180),
        "icon-192.png": (192, 192),
        "icon-192-dark.png": (192, 192),
        "icon-512.png": (512, 512),
        "icon-512-dark.png": (512, 512),
    }
    for relative_path, expected_dimensions in app_icons.items():
        with open(os.path.join(WORKTREE_DIR, relative_path), "rb") as icon_file:
            icon = icon_file.read(33)
        if icon[:8] != b"\x89PNG\r\n\x1a\n":
            sys.exit(f"FAIL: App icon is not a PNG: {relative_path}")
        width = int.from_bytes(icon[16:20], "big")
        height = int.from_bytes(icon[20:24], "big")
        color_type = icon[25]
        if (width, height) != expected_dimensions:
            sys.exit(
                f"FAIL: App icon dimensions are {(width, height)}, expected "
                f"{expected_dimensions}: {relative_path}"
            )
        if color_type != 2:
            sys.exit(f"FAIL: App icon must be opaque RGB PNG: {relative_path}")

    # The dark diamond already satisfies the shared installed-icon standard:
    # 77.8% visible fill (inside the 76-79% raster band), centered at 60,60.
    dark_icon_source = open(
        os.path.join(WORKTREE_DIR, "assets", "brand", "waypoint-app-icon-dark.svg"),
        "r", encoding="utf-8",
    ).read()
    if 'M60 19 L101 60 L60 101 L19 60 Z' not in dark_icon_source:
        sys.exit("FAIL: Waypoint app-icon diamond geometry changed unexpectedly.")
    diamond_fill = (2 * (41 + 4 * (2 ** 0.5))) / 120
    if not 0.76 <= diamond_fill <= 0.79:
        sys.exit(f"FAIL: Waypoint app-icon fill left the standard band: {diamond_fill:.4f}")

    with open(os.path.join(source_package_dir, "waypoint-mark.svg"), "rb") as source_file:
        canonical_mark = source_file.read()
    with open(os.path.join(WORKTREE_DIR, "assets", "brand", "waypoint-mark.svg"), "rb") as deployed_file:
        if deployed_file.read() != canonical_mark:
            sys.exit("FAIL: Canonical app icon SVG differs from finalized Waypoint mark.")

    if 'const SHELL_VERSION = "waypoint-shell-v4";' not in open(
        os.path.join(WORKTREE_DIR, "sw.js"), "r", encoding="utf-8"
    ).read():
        sys.exit("FAIL: Service-worker version was not advanced for adaptive app icons.")

    v2_index = open(
        os.path.join(WORKTREE_DIR, "frontend", "dist", "index.html"),
        "r",
        encoding="utf-8",
    ).read()
    for required_v2_icon_contract in (
        'href="/v2/favicon.ico"',
        '"/v2/apple-touch-icon-dark.png?v=1"',
        'matchMedia("(prefers-color-scheme: dark)")',
    ):
        if required_v2_icon_contract not in v2_index:
            sys.exit(
                f"FAIL: V2 icon contract missing {required_v2_icon_contract!r}."
            )


def check_js_syntax():
    print("[3/8] Checking JavaScript syntax via node --check...")
    wt_index = os.path.join(WORKTREE_DIR, "index.html")
    with open(wt_index, "r", encoding="utf-8") as f:
        content = f.read()
        
    match = re.search(r"<script>(.*?)</script>", content, re.DOTALL)
    if not match:
        sys.exit("FAIL: Could not extract <script> block from index.html")
        
    js_content = match.group(1)
    
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tf:
        tf.write(js_content)
        temp_js_path = tf.name
        
    try:
        res = subprocess.run(["node", "--check", temp_js_path], capture_output=True, text=True)
        if res.returncode != 0:
            sys.exit(f"FAIL: node --check failed:\n{res.stderr}")
    finally:
        if os.path.exists(temp_js_path):
            os.remove(temp_js_path)
            
    print("  ✓ Inline JavaScript syntax check passed (node --check).")


def check_cert_ids():
    print("[4/8] Checking default cert IDs and absence of sophia...")
    wt_index = os.path.join(WORKTREE_DIR, "index.html")
    with open(wt_index, "r", encoding="utf-8") as f:
        content = f.read()
        
    expected_ids = ['aplus', 'netplus', 'secplus', 'cloudplus', 'ccna', 'ccsp']
    for cid in expected_ids:
        if f"id:'{cid}'" not in content and f'id:"{cid}"' not in content:
            sys.exit(f"FAIL: Expected cert id '{cid}' missing in index.html DEFAULTS")
            
    if "'sophia'" in content.lower() or '"sophia"' in content.lower():
        match = re.search(r"certs:\[(.*?)\]", content, re.DOTALL)
        if match and "sophia" in match.group(1).lower():
            sys.exit("FAIL: Sophia cert found in DEFAULTS array!")
            
    print("  ✓ Default six certification IDs verified; sophia is absent.")


def check_no_hardcoded_endpoints():
    print("[5/8] Verifying no http(s) Study Library endpoint hardcoded in index.html...")
    wt_index = os.path.join(WORKTREE_DIR, "index.html")
    with open(wt_index, "r", encoding="utf-8") as f:
        content = f.read()
        
    matches = re.findall(r'https?://[^\s"\'>]+', content)
    forbidden_matches = [m for m in matches if 'api/waypoint' in m or 'study' in m.lower() and not m.startswith('http://100.')]
    if forbidden_matches:
        sys.exit(f"FAIL: Found hardcoded Study Library endpoint URL: {forbidden_matches}")

    if "studyEndpoint:'/api/waypoint/summary'" not in content:
        sys.exit("FAIL: Canary same-origin summary endpoint is not the default.")
        
    print("  ✓ No hardcoded Study Library API endpoint URL in index.html.")


def check_validator_logic():
    print("[6/8] Testing Study Library summary validator & URL safety in Node...")
    wt_index = os.path.join(WORKTREE_DIR, "index.html")
    with open(wt_index, "r", encoding="utf-8") as f:
        content = f.read()
        
    match = re.search(r"<script>(.*?)</script>", content, re.DOTALL)
    js_content = match.group(1)
    
    mock_dom = """
    var elements = {};
    function makeEl(){ return { value: '', innerHTML: '', textContent: '', hidden: false, addEventListener: function(){}, setAttribute: function(){}, removeAttribute: function(){}, closest: function(){return null;} }; }
    var document = {
      getElementById: function(id) {
        if (!elements[id]) elements[id] = makeEl();
        return elements[id];
      },
      addEventListener: function() {}
    };
    var window = { addEventListener: function(){}, matchMedia: function(){return {matches:false};} };
    var navigator = { onLine: true };
    var localStorage = { getItem: function(){ return null; }, setItem: function(){} };
    """
    
    test_harness = mock_dom + "\n" + js_content + """
    // Unit tests for validateStudySummary
    var validPayload = {
      schema_version: 1,
      generated_at: "2026-07-29T14:00:00Z",
      certification_id: "aplus",
      certification_name: "CompTIA A+",
      current_exam: "220-1201",
      current_week: 1,
      week_title: "Core 1 Foundations",
      next_task: { id: "t1", title: "Subnetting Drills", type: "practice", description: "15 questions" },
      total_hours: 12.5,
      hours_last_7_days: 4.0,
      completed_tasks: 10,
      total_tasks: 48,
      objective_coverage: 0.25,
      practice_average_recent: null,
      weak_objectives: [],
      readiness_label: "getting started (heuristic)",
      readiness_components: { plan_progress_pct: 20, practice_average_recent_pct: null, objective_coverage_pct: 25 },
      study_library_url: "https://study.local/waypoint",
      study_library_path: "/waypoint",
      progress: {
        generated_at: "2026-07-29T14:00:00Z",
        current_exam: "220-1201",
        current_week: 1,
        week_title: "Core 1 Foundations",
        current_week_tasks: { total: 4, completed: 0, exempted: 0, remaining: 4 },
        study_minutes_last_7_days: 0,
        study_sessions_last_7_days: 0,
        days_studied_last_7_days: 0,
        current_streak_days: 0,
        last_activity_at: null,
        diagnostic_attempts_submitted: 0,
        diagnostic_attempts_passed: 0,
        domains_mastered: 0,
        domains_available: 5,
        domain_mastery: [{
          code: "1.0", name: "Mobile Devices", scope_id: 1,
          scope_name: "Week 1 knowledge check", status: "unassessed",
          retention_due_at: null, latest_raw_score_pct: null,
          latest_effective_score_pct: null, latest_attempt_at: null,
          open_gap_count: 0
        }],
        practice_trend: [],
        evidence_note: "Domain mastery is based on submitted diagnostic checks. It is not exact-objective mastery, hands-on/PBQ proof, or exam readiness."
      },
      adaptive_curriculum: {
        schema_version: "1",
        generated_at: "2026-07-29T14:00:00Z",
        current_exam: "220-1201",
        current_week: 1,
        week_title: "Core 1 Foundations",
        days: 2,
        minutes_per_day: 45,
        provisional: true,
        replan_after_item_id: "diagnostic:1",
        schedule: [
          { day: 1, date: "2026-07-29", target_minutes: 45, items: [{
            id: "diagnostic:1", kind: "knowledge_check", eyebrow: "Start here",
            title: "Week 1 knowledge check", description: "Check what you know.",
            reason: "Check first.", due_at: null, action: {type: "diagnostic"},
            estimated_minutes: 35, conditional_on: null
          }], note: "Check first." },
          { day: 2, date: "2026-07-30", target_minutes: 45, items: [{
            id: "task:1", kind: "plan_task", eyebrow: "Reading",
            title: "Read Mobile Devices", description: "Focused reading.",
            reason: "Next task.", due_at: null, action: {type: "task"},
            estimated_minutes: 45, conditional_on: "diagnostic:1"
          }], note: "Rebuild after the knowledge check." }
        ],
        source_counts: { retention_due: 0, open_gaps: 0, incomplete_current_week_tasks: 4 },
        policy: []
      }
    };

    var res1 = validateStudySummary(validPayload);
    if (!res1.valid) throw new Error("Valid payload rejected: " + res1.error);

    // Initial honest diagnostic payload test
    var initialDiagnosticPayload = JSON.parse(JSON.stringify(validPayload));
    initialDiagnosticPayload.diagnostics = {
      current_gap_count: 0,
      current_scope: {
        id: 1,
        name: "Week 1: Core 1 Foundations",
        slug: "week-1-core-1-foundations",
        status: "unassessed",
        retention_due_at: null
      },
      diagnostic_checks_available: 6,
      diagnostic_checks_passed: 0,
      domain_mastery_pct: 0,
      domain_mastery_pct_label: "domain diagnostic mastery",
      retention_due_count: 0,
      retention_due_next_at: null
    };

    var resDiagInit = validateStudySummary(initialDiagnosticPayload);
    if (!resDiagInit.valid) throw new Error("Valid initial diagnostic payload rejected: " + resDiagInit.error);

    // Minimal payload with honest null evidence
    var validMinimalPayload = {
      schema_version: 1,
      certification_id: "secplus",
      current_exam: "SY0-701",
      total_tasks: 0,
      completed_tasks: 0,
      readiness_label: "getting started",
      readiness_components: {},
      generated_at: null,
      current_week: null,
      week_title: null,
      next_task: null,
      practice_average_recent: null,
      weak_objectives: [],
      study_library_url: null
    };
    var resMin = validateStudySummary(validMinimalPayload);
    if (!resMin.valid) throw new Error("Valid minimal payload with nulls rejected: " + resMin.error);

    // Rejection tests:
    function assertInvalid(payload, label) {
      var r = validateStudySummary(payload);
      if (r.valid) throw new Error("Expected invalid for (" + label + "), but validator accepted it!");
    }

    var pNoSchema = JSON.parse(JSON.stringify(validPayload));
    delete pNoSchema.schema_version;
    assertInvalid(pNoSchema, "missing schema_version");

    var pCertId = JSON.parse(JSON.stringify(validPayload));
    pCertId.certification_id = 123;
    assertInvalid(pCertId, "invalid certification_id type");

    var pNoRc = JSON.parse(JSON.stringify(validPayload));
    delete pNoRc.readiness_components;
    assertInvalid(pNoRc, "missing readiness_components");

    var pGenAt = JSON.parse(JSON.stringify(validPayload));
    pGenAt.generated_at = 12345;
    assertInvalid(pGenAt, "wrong generated_at type number");

    var pTotalTasksNaN = JSON.parse(JSON.stringify(validPayload));
    pTotalTasksNaN.total_tasks = NaN;
    assertInvalid(pTotalTasksNaN, "total_tasks NaN");

    var pTotalTasksInf = JSON.parse(JSON.stringify(validPayload));
    pTotalTasksInf.total_tasks = Infinity;
    assertInvalid(pTotalTasksInf, "total_tasks Infinity");

    var pTotalTasksNeg = JSON.parse(JSON.stringify(validPayload));
    pTotalTasksNeg.total_tasks = -5;
    assertInvalid(pTotalTasksNeg, "total_tasks negative");

    var pTotalHoursStr = JSON.parse(JSON.stringify(validPayload));
    pTotalHoursStr.total_hours = "12.5";
    assertInvalid(pTotalHoursStr, "total_hours string");

    var pPracNaN = JSON.parse(JSON.stringify(validPayload));
    pPracNaN.practice_average_recent = NaN;
    assertInvalid(pPracNaN, "practice_average_recent NaN");

    var pCompExceeds = JSON.parse(JSON.stringify(validPayload));
    pCompExceeds.completed_tasks = 50;
    pCompExceeds.total_tasks = 48;
    assertInvalid(pCompExceeds, "completed_tasks > total_tasks");

    var pNextTaskStr = JSON.parse(JSON.stringify(validPayload));
    pNextTaskStr.next_task = "invalid string";
    assertInvalid(pNextTaskStr, "next_task string");

    var pNextTaskArr = JSON.parse(JSON.stringify(validPayload));
    pNextTaskArr.next_task = [1, 2, 3];
    assertInvalid(pNextTaskArr, "next_task array");

    var pNextTaskBadTitle = JSON.parse(JSON.stringify(validPayload));
    pNextTaskBadTitle.next_task = { title: 12345 };
    assertInvalid(pNextTaskBadTitle, "next_task title number");

    var pWeakObjStr = JSON.parse(JSON.stringify(validPayload));
    pWeakObjStr.weak_objectives = "not an array";
    assertInvalid(pWeakObjStr, "weak_objectives not array");

    var pWeakObjBadElem = JSON.parse(JSON.stringify(validPayload));
    pWeakObjBadElem.weak_objectives = [123];
    assertInvalid(pWeakObjBadElem, "weak_objectives array with number element");

    var pWeakObjBadProp = JSON.parse(JSON.stringify(validPayload));
    pWeakObjBadProp.weak_objectives = [{ unknownProp: "test" }];
    assertInvalid(pWeakObjBadProp, "weak_objectives object with unallowed property");

    var pStudyUrlNum = JSON.parse(JSON.stringify(validPayload));
    pStudyUrlNum.study_library_url = 999;
    assertInvalid(pStudyUrlNum, "study_library_url number");

    // Rejection tests for diagnostics block
    var pDiagStr = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pDiagStr.diagnostics = "invalid_string";
    assertInvalid(pDiagStr, "diagnostics string");

    var pDiagArr = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pDiagArr.diagnostics = [1, 2];
    assertInvalid(pDiagArr, "diagnostics array");

    var pGapNeg = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pGapNeg.diagnostics.current_gap_count = -1;
    assertInvalid(pGapNeg, "current_gap_count negative");

    var pGapNaN = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pGapNaN.diagnostics.current_gap_count = NaN;
    assertInvalid(pGapNaN, "current_gap_count NaN");

    var pGapStr = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pGapStr.diagnostics.current_gap_count = "0";
    assertInvalid(pGapStr, "current_gap_count string");

    var pChkAvailNeg = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pChkAvailNeg.diagnostics.diagnostic_checks_available = -1;
    assertInvalid(pChkAvailNeg, "diagnostic_checks_available negative");

    var pChkPassExceeds = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pChkPassExceeds.diagnostics.diagnostic_checks_passed = 8;
    pChkPassExceeds.diagnostics.diagnostic_checks_available = 6;
    assertInvalid(pChkPassExceeds, "diagnostic_checks_passed > diagnostic_checks_available");

    var pMasteryHigh = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pMasteryHigh.diagnostics.domain_mastery_pct = 150;
    assertInvalid(pMasteryHigh, "domain_mastery_pct > 100");

    var pMasteryLow = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pMasteryLow.diagnostics.domain_mastery_pct = -5;
    assertInvalid(pMasteryLow, "domain_mastery_pct < 0");

    var pMasteryLabelNum = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pMasteryLabelNum.diagnostics.domain_mastery_pct_label = 123;
    assertInvalid(pMasteryLabelNum, "domain_mastery_pct_label number");

    var pRetCountNeg = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pRetCountNeg.diagnostics.retention_due_count = -2;
    assertInvalid(pRetCountNeg, "retention_due_count negative");

    var pRetNextNum = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pRetNextNum.diagnostics.retention_due_next_at = 12345;
    assertInvalid(pRetNextNum, "retention_due_next_at number");

    var pScopeStr = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pScopeStr.diagnostics.current_scope = "invalid_scope";
    assertInvalid(pScopeStr, "current_scope string");

    var pScopeIdStr = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pScopeIdStr.diagnostics.current_scope.id = "1";
    assertInvalid(pScopeIdStr, "current_scope.id string");

    var pScopeNameNum = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pScopeNameNum.diagnostics.current_scope.name = 100;
    assertInvalid(pScopeNameNum, "current_scope.name number");

    var pScopeSlugNum = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pScopeSlugNum.diagnostics.current_scope.slug = 100;
    assertInvalid(pScopeSlugNum, "current_scope.slug number");

    var pScopeStatusNum = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pScopeStatusNum.diagnostics.current_scope.status = 100;
    assertInvalid(pScopeStatusNum, "current_scope.status number");

    var pScopeRetDueNum = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    pScopeRetDueNum.diagnostics.current_scope.retention_due_at = 12345;
    assertInvalid(pScopeRetDueNum, "current_scope.retention_due_at number");

    // Rejection tests for progress/adaptive blocks
    var pProgressStr = JSON.parse(JSON.stringify(validPayload));
    pProgressStr.progress = "invalid";
    assertInvalid(pProgressStr, "progress string");

    var pProgressCounts = JSON.parse(JSON.stringify(validPayload));
    pProgressCounts.progress.current_week_tasks.remaining = 9;
    assertInvalid(pProgressCounts, "progress task counts exceed total");

    var pDomainScore = JSON.parse(JSON.stringify(validPayload));
    pDomainScore.progress.domain_mastery[0].latest_raw_score_pct = 120;
    assertInvalid(pDomainScore, "domain score over 100");

    var pAdaptiveDays = JSON.parse(JSON.stringify(validPayload));
    pAdaptiveDays.adaptive_curriculum.days = 20;
    assertInvalid(pAdaptiveDays, "adaptive days over 14");

    var pAdaptiveItem = JSON.parse(JSON.stringify(validPayload));
    pAdaptiveItem.adaptive_curriculum.schedule[0].items[0].title = 123;
    assertInvalid(pAdaptiveItem, "adaptive item title number");

    // URL safety tests
    var dangerousUrls = [
      "javascript:alert(1)",
      "data:text/html,<h1>bad</h1>",
      "file:///etc/passwd",
      "//evil.com/api",
      "http://user:pass@evil.com/api",
      "https://user@evil.com/api"
    ];

    dangerousUrls.forEach(function(u) {
      if (isSafeUrl(u)) throw new Error("isSafeUrl accepted dangerous URL: " + u);
      if (validateEndpointUrl(u) !== null) throw new Error("validateEndpointUrl accepted dangerous URL: " + u);
      if (getSafeStudyLibraryUrl(u) !== "") throw new Error("getSafeStudyLibraryUrl accepted dangerous URL: " + u);
    });

    var safeRelative = "/study-api/waypoint/summary";
    if (!isSafeUrl(safeRelative)) throw new Error("isSafeUrl rejected safe relative URL: " + safeRelative);
    if (validateEndpointUrl(safeRelative) !== safeRelative) throw new Error("validateEndpointUrl failed for safe relative URL");
    if (getSafeStudyLibraryUrl(safeRelative) !== safeRelative) throw new Error("getSafeStudyLibraryUrl failed for safe relative URL");

    var safeHttps = "https://study.local/waypoint";
    if (!isSafeUrl(safeHttps)) throw new Error("isSafeUrl rejected safe https URL: " + safeHttps);
    if (validateEndpointUrl(safeHttps) !== safeHttps) throw new Error("validateEndpointUrl failed for safe https URL");
    if (getSafeStudyLibraryUrl(safeHttps) !== safeHttps) throw new Error("getSafeStudyLibraryUrl failed for safe https URL");

    // Deep-link omission test in renderStudyIntel
    S.studyEndpoint = "/study-api/waypoint/summary";
    var payloadWithJs = JSON.parse(JSON.stringify(validPayload));
    payloadWithJs.study_library_url = "javascript:alert(1)";
    payloadWithJs.study_library_path = "/waypoint";
    S.studySummary = payloadWithJs;
    renderStudyIntel();

    var htmlOutput = elements["study-intel-content"].innerHTML;
    if (htmlOutput.indexOf("href=") !== -1 || htmlOutput.indexOf("Open Study Next") !== -1) {
      throw new Error("renderStudyIntel rendered deep link for invalid study_library_url!");
    }

    // Deep-link inclusion test for safe URL
    var payloadWithSafeUrl = JSON.parse(JSON.stringify(validPayload));
    payloadWithSafeUrl.study_library_url = "https://study.local/waypoint";
    S.studySummary = payloadWithSafeUrl;
    renderStudyIntel();
    var htmlOutput2 = elements["study-intel-content"].innerHTML;
    if (htmlOutput2.indexOf('href="https://study.local/waypoint"') === -1 || htmlOutput2.indexOf("Open Study Next") === -1) {
      throw new Error("renderStudyIntel failed to render safe deep link!");
    }
    if (htmlOutput2.indexOf("Progress and Mastery Evidence") === -1) throw new Error("Missing progress dashboard");
    if (htmlOutput2.indexOf("0 / 5") === -1) throw new Error("Missing domain mastery count");
    if (htmlOutput2.indexOf("Adaptive 2-Day Plan") === -1) throw new Error("Missing adaptive plan");
    if (htmlOutput2.indexOf("Week 1 knowledge check") === -1) throw new Error("Missing adaptive first action");

    // Diagnostic UI assertions: Initial honest payload
    S.studySummary = initialDiagnosticPayload;
    renderStudyIntel();
    var htmlDiagInit = elements["study-intel-content"].innerHTML;
    if (htmlDiagInit.indexOf("Week 1: Core 1 Foundations") === -1) throw new Error("Missing scope name in rendered output");
    if (htmlDiagInit.indexOf("unassessed") === -1) throw new Error("Missing unassessed status label");
    if (htmlDiagInit.indexOf("0 / 6 checks passed") === -1) throw new Error("Missing checks passed count");
    if (htmlDiagInit.indexOf("0% domain diagnostic mastery") === -1) throw new Error("Missing 0% domain diagnostic mastery label");
    if (htmlDiagInit.indexOf("0 gaps") === -1) throw new Error("Missing 0 gaps display");
    if (htmlDiagInit.indexOf("Optional knowledge check available before this section.") === -1) throw new Error("Missing unassessed notice near next action");
    if (htmlDiagInit.indexOf("domain-level diagnostic evidence") === -1) throw new Error("Missing honesty disclaimer note");

    // Diagnostic UI assertions: Gaps payload
    var payloadWithGaps = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    payloadWithGaps.diagnostics.current_gap_count = 2;
    S.studySummary = payloadWithGaps;
    renderStudyIntel();
    var htmlGaps = elements["study-intel-content"].innerHTML;
    if (htmlGaps.indexOf("Focused review available in Study Library") === -1) throw new Error("Missing gaps notice near next action");
    if (htmlGaps.indexOf("2 gaps") === -1) throw new Error("Missing 2 gaps badge");

    // Diagnostic UI assertions: Retention due payload
    var payloadWithRetention = JSON.parse(JSON.stringify(initialDiagnosticPayload));
    payloadWithRetention.diagnostics.retention_due_count = 1;
    payloadWithRetention.diagnostics.retention_due_next_at = "2026-08-01T00:00:00Z";
    S.studySummary = payloadWithRetention;
    renderStudyIntel();
    var htmlRet = elements["study-intel-content"].innerHTML;
    if (htmlRet.indexOf("Retention review due in Study Library") === -1) throw new Error("Missing retention review notice near next action");

    // Diagnostic UI assertions: Older payload without diagnostics
    S.studySummary = validPayload;
    renderStudyIntel();
    var htmlOld = elements["study-intel-content"].innerHTML;
    if (htmlOld.indexOf("Diagnostic checks progress unavailable in this summary version.") === -1) throw new Error("Missing absent diagnostics empty state");

    // Render non-throwing test for minimal payload
    S.studySummary = validMinimalPayload;
    renderStudyIntel();

    console.log("ALL_VALIDATOR_TESTS_PASSED");
    """
    
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tf:
        tf.write(test_harness)
        temp_js_path = tf.name
        
    try:
        res = subprocess.run(["node", temp_js_path], capture_output=True, text=True)
        if "ALL_VALIDATOR_TESTS_PASSED" not in res.stdout:
            sys.exit(f"FAIL: Validator unit tests failed:\n{res.stderr}\n{res.stdout}")
    finally:
        if os.path.exists(temp_js_path):
            os.remove(temp_js_path)
            
    print("  ✓ Summary validator & URL safety successfully tested in Node (all edge cases, URL rejections/acceptances, and deep-link omission verified).")




def check_git_diff_and_status():
    print("[7/8] Verifying worktree git diff & status...")
    res = subprocess.run(["git", "-C", WORKTREE_DIR, "status", "--porcelain"], capture_output=True, text=True)
    untracked = [line for line in res.stdout.strip().split("\n") if line.strip()]
    
    allowed_prefixes = (
        ".gitignore", "index.html", "README.md", "tests/", "tests/check_integration.py",
        "ops/", "assets/", "favicon.ico", "favicon.svg", "favicon-16.png", "favicon-32.png",
        "favicon-48.png", "apple-touch-icon.png", "apple-touch-icon-dark.png",
        "icon-192.png", "icon-192-dark.png", "icon-512.png", "icon-512-dark.png",
        "site.webmanifest", "sw.js", "scripts/", "frontend/", "docs/", "study-library/",
    )
    modified_files = set()
    for line in untracked:
        parts = line.strip().split()
        if len(parts) >= 2:
            fname = parts[-1]
            if not any(fname.startswith(p) for p in allowed_prefixes):
                modified_files.add(fname)
            
    if modified_files:
        sys.exit(f"FAIL: Unexpected modified files in worktree: {modified_files}")
        
    print("  ✓ Worktree touches only intended production UI, brand, proxy, and test files.")



def print_manual_test_matrix():
    print("[8/8] Documenting Manual Test Matrix...")
    matrix = """
  MANUAL TEST MATRIX:
  --------------------------------------------------------------------------------------
  Test Case                           | Expected Behavior
  --------------------------------------------------------------------------------------
  1. No Summary Connected (Default)   | Shows 'Disconnected' status & helpful non-alarming
                                      | prompt banner to enter URL or import JSON file.
  2. Load Initial No-Progress JSON    | Correctly displays 220-1201, Week 1, 0/48 tasks,
                                      | 0h, 0% coverage, 'Not enough evidence' for practice,
                                      | empty weak objectives message, and readiness breakdown.
  3. Fetch Direct Endpoint URL        | Fetches with AbortController (5s timeout), validates
                                      | schema, updates status bar & metrics, saves state.
  4. Invalid Schema / Malformed File | Shows non-alarming error prompt ('Validation failed'),
                                      | preserves previous valid summary state without crash.
  5. Weak Objectives Display (<= 3)   | Renders up to 3 weak objectives with badges; shows
                                      | empty-state message if weak objectives list is empty.
  6. Persistence & Backup Export      | Preserves endpoint and summary in localStorage (v1).
                                      | Export backup includes study state; import restores it.
  7. Reset All Action                 | Clears certs, logs, and resets study endpoint/summary.
  8. Progress Evidence                | Shows week completed/exempted/remaining separately,
                                      | seven-day minutes, recorded-day streak, and domain rows.
  9. Adaptive Plan                    | Shows up to seven days; post-check tasks are visibly
                                      | provisional until the knowledge-check result replans them.
  --------------------------------------------------------------------------------------
    """
    print(matrix)


def main():
    print("=== Waypoint Study Intelligence Integration Check ===")
    check_live_repo()
    check_worktree_contract()
    check_js_syntax()
    check_cert_ids()
    check_no_hardcoded_endpoints()
    check_validator_logic()
    check_git_diff_and_status()
    print_manual_test_matrix()
    print("=== ALL INTEGRATION VERIFICATION CHECKS PASSED ===")


if __name__ == "__main__":
    main()
