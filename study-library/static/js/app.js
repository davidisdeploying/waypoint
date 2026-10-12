(function () {
  "use strict";

  const state = { csrfToken: null, examCache: null };

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function snippetToHtml(snippet) {
    // server wraps matches in [ ]; escape first, then turn markers into <mark>
    return escapeHtml(snippet).replace(/\[/g, "<mark>").replace(/\]/g, "</mark>");
  }

  function toast(message, isError) {
    const t = document.getElementById("toast");
    t.textContent = message;
    t.hidden = false;
    t.className = "toast" + (isError ? " error" : "");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { t.hidden = true; }, 4000);
  }

  async function api(path, opts) {
    opts = opts || {};
    const headers = Object.assign({}, opts.headers || {});
    if (opts.method && opts.method !== "GET") {
      headers["Content-Type"] = "application/json";
      if (!state.csrfToken) await ensureCsrf();
      headers["X-CSRF-Token"] = state.csrfToken;
    }
    const res = await fetch(path, Object.assign({}, opts, { headers }));
    let data = null;
    try { data = await res.json(); } catch (e) { /* no body */ }
    if (!res.ok) {
      const msg = (data && data.error) || `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return data;
  }

  async function ensureCsrf() {
    const data = await api("/api/csrf-token");
    state.csrfToken = data.csrf_token;
  }

  // --- Diagnostics API helpers --------------------------------------------

  const diag = {
    listScopes: () => api("/api/diagnostics/scopes"),
    getScope: (id) => api(`/api/diagnostics/scopes/${id}`),
    start: (scopeId, mode) => api(`/api/diagnostics/scopes/${scopeId}/start`, { method: "POST", body: JSON.stringify({ mode }) }),
    getAttempt: (id) => api(`/api/diagnostics/attempts/${id}`),
    submit: (id, responses) => api(`/api/diagnostics/attempts/${id}/submit`, { method: "POST", body: JSON.stringify({ responses }) }),
    results: (id) => api(`/api/diagnostics/attempts/${id}/results`),
    markReviewed: (id) => api(`/api/remediation/${id}`, { method: "POST", body: JSON.stringify({}) }),
  };

  function formatDate(iso) {
    if (!iso) return "";
    try { return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }); }
    catch (e) { return iso; }
  }

  function masteryBadge(scope) {
    if (!scope) return "";
    if (!scope.enabled) {
      return `<span class="knowledge-badge disabled">Not enough questions yet for a knowledge check</span>`;
    }
    const status = scope.mastery_status || "unassessed";
    if (status === "provisional_mastery" || status === "mastered_after_remediation") {
      const due = scope.retention_due_at;
      const overdue = due && due <= new Date().toISOString();
      const label = status === "mastered_after_remediation" ? "Mastered after remediation" : "Mastered by diagnostic";
      return `<span class="knowledge-badge mastered">${escapeHtml(label)} — retention ${overdue ? "due now" : "due " + escapeHtml(formatDate(due))}</span>`;
    }
    if (status === "needs_remediation") {
      return `<span class="knowledge-badge gap">${scope.open_gap_count || 0} gap(s) to review</span>`;
    }
    return `<span class="knowledge-badge unassessed">Not checked yet</span>`;
  }

  function knowledgeActionsHtml(scope) {
    if (!scope) return "";
    if (!scope.enabled) {
      return `<p class="empty-state">This section doesn't have enough imported questions for a reliable check yet.</p>`;
    }
    const status = scope.mastery_status || "unassessed";
    const due = scope.retention_due_at;
    const overdue = due && due <= new Date().toISOString();
    const buttons = [];
    if (status === "unassessed") {
      buttons.push(`<button type="button" class="secondary" data-diag-action="diagnostic" data-scope-id="${scope.id}">Check what I already know</button>`);
    } else if (status === "needs_remediation") {
      const disabled = scope.open_gap_count > 0 ? "disabled" : "";
      const title = scope.open_gap_count > 0 ? `title="Review all ${scope.open_gap_count} gap(s) below before retesting"` : "";
      buttons.push(`<button type="button" class="secondary" data-diag-action="retest" data-scope-id="${scope.id}" ${disabled} ${title}>Fresh retest</button>`);
    } else if (overdue) {
      buttons.push(`<button type="button" class="secondary" data-diag-action="retention" data-scope-id="${scope.id}">Retention check</button>`);
    }
    buttons.push(`<button type="button" class="secondary" data-diag-view-scope="${scope.id}">Details</button>`);
    return `<div class="filters">${buttons.join("")}</div>`;
  }

  function diagnosticsSummaryCardHtml(dg) {
    if (!dg) return "";
    return `<div class="card">
      <h2>Knowledge checks</h2>
      <div class="grid">
        ${statTile("Checks passed", `${dg.diagnostic_checks_passed} / ${dg.diagnostic_checks_available}`)}
        ${statTile("Open gaps", dg.current_gap_count)}
        ${statTile("Retention checks due", dg.retention_due_count)}
        ${statTile("Domain mastery", dg.domain_mastery_pct !== null ? dg.domain_mastery_pct + "%" : null)}
      </div>
      <p class="empty-state">${escapeHtml(dg.domain_mastery_pct_label)}</p>
    </div>`;
  }

  function wireKnowledgeActions(root) {
    root.querySelectorAll("[data-diag-action]").forEach((btn) => {
      btn.addEventListener("click", () => openDiagnostic(parseInt(btn.dataset.scopeId, 10), btn.dataset.diagAction));
    });
    root.querySelectorAll("[data-diag-view-scope]").forEach((btn) => {
      btn.addEventListener("click", () => openScopeDetail(parseInt(btn.dataset.diagViewScope, 10)));
    });
  }

  // --- Diagnostic runner (paged assessment) -------------------------------

  let runner = null; // { scope, attempt, index, answers: Map }

  function showDiagnosticView() {
    document.querySelectorAll(".tab").forEach((btn) => btn.removeAttribute("aria-current"));
    document.querySelectorAll(".view").forEach((panel) => {
      panel.hidden = panel.dataset.viewPanel !== "diagnostic";
    });
    location.hash = "diagnostic";
  }

  function backFromDiagnostic() {
    runner = null;
    activate("next");
  }

  async function openDiagnostic(scopeId, mode) {
    showDiagnosticView();
    const panel = document.getElementById("view-diagnostic");
    panel.innerHTML = '<p class="empty-state">Starting check…</p>';
    try {
      let attempt;
      try {
        attempt = await diag.start(scopeId, mode);
      } catch (e) {
        if (/in-progress attempt already exists/i.test(e.message)) {
          const scope = await diag.getScope(scopeId);
          const existing = scope.recent_attempts.find((a) => a.state === "in_progress");
          if (existing) attempt = await diag.getAttempt(existing.id);
          else throw e;
        } else {
          throw e;
        }
      }
      const scope = await diag.getScope(scopeId);
      runner = { scope, attempt, index: 0, answers: new Map() };
      renderQuestion();
    } catch (e) {
      panel.innerHTML = `<div class="card"><p class="empty-state">Could not start this check: ${escapeHtml(e.message)}</p>
        <button type="button" class="secondary" data-back>Back to Study Next</button></div>`;
      panel.querySelector("[data-back]").addEventListener("click", backFromDiagnostic);
    }
  }

  async function resumeAttemptResults(attemptId) {
    showDiagnosticView();
    const panel = document.getElementById("view-diagnostic");
    panel.innerHTML = '<p class="empty-state">Loading results…</p>';
    try {
      const results = await diag.results(attemptId);
      renderResults(results);
    } catch (e) {
      panel.innerHTML = `<p class="empty-state">${escapeHtml(e.message)}</p>`;
    }
  }

  function multiSelectExpected(promptText) {
    const m = /\(Choose (two|three|four)\.?\)/i.exec(promptText || "");
    if (!m) return 1;
    return { two: 2, three: 3, four: 4 }[m[1].toLowerCase()];
  }

  function renderQuestion() {
    const panel = document.getElementById("view-diagnostic");
    const { attempt, index } = runner;
    const total = attempt.responses.length;
    const r = attempt.responses[index];
    const expected = multiSelectExpected(r.prompt_snapshot);
    const inputType = expected > 1 ? "checkbox" : "radio";
    const saved = runner.answers.get(r.question_id) || { selected: [], confidence: null };
    const isLast = index === total - 1;

    panel.innerHTML = `
      <div class="card diagnostic-runner">
        <p class="empty-state">${escapeHtml(runner.scope.name)} — ${escapeHtml(attempt.mode)} check</p>
        <div class="progress-bar" role="progressbar" aria-valuemin="0" aria-valuemax="${total}" aria-valuenow="${index + 1}">
          <span style="width:${((index + 1) / total) * 100}%"></span>
        </div>
        <p class="q-progress">Question ${index + 1} of ${total}${expected > 1 ? ` — select ${expected}` : ""}</p>
        <h2 tabindex="-1" id="q-heading">${escapeHtml(r.prompt_snapshot)}</h2>
        <fieldset class="options-fieldset">
          <legend class="empty-state">${expected > 1 ? `Choose ${expected} options` : "Choose one option"}</legend>
          ${r.options
            .map(
              (opt, i) => `<label class="option-row">
                <input type="${inputType}" name="opt" value="${i}" ${saved.selected.includes(i) ? "checked" : ""}>
                <span>${escapeHtml(opt)}</span>
              </label>`
            )
            .join("")}
        </fieldset>
        <fieldset class="confidence-fieldset">
          <legend>How confident are you?</legend>
          ${["high", "medium", "low"]
            .map(
              (c) => `<label class="option-row confidence-row">
                <input type="radio" name="confidence" value="${c}" ${saved.confidence === c ? "checked" : ""}>
                <span>${c}</span>
              </label>`
            )
            .join("")}
        </fieldset>
        <div class="filters diagnostic-actions">
          <button type="button" class="secondary" data-back>Back to Study Next</button>
          ${index > 0 ? '<button type="button" class="secondary" data-prev>Previous</button>' : ""}
          <button type="button" data-next>${isLast ? "Submit" : "Next"}</button>
        </div>
        <p class="empty-state">This is a multiple-choice check, not a hands-on/lab validation of ability. Answers are not shown until you submit.</p>
      </div>`;

    panel.querySelector("[data-back]").addEventListener("click", backFromDiagnostic);
    if (index > 0) {
      panel.querySelector("[data-prev]").addEventListener("click", () => {
        saveCurrentAnswer(false);
        runner.index -= 1;
        renderQuestion();
      });
    }
    panel.querySelector("[data-next]").addEventListener("click", async () => {
      if (!saveCurrentAnswer(true)) return;
      if (isLast) {
        await submitRunner();
      } else {
        runner.index += 1;
        renderQuestion();
      }
    });
    const heading = panel.querySelector("#q-heading");
    if (heading) heading.focus();

    function saveCurrentAnswer(validate) {
      const selected = Array.from(panel.querySelectorAll('input[name="opt"]:checked')).map((i) => parseInt(i.value, 10));
      const confidenceEl = panel.querySelector('input[name="confidence"]:checked');
      const confidence = confidenceEl ? confidenceEl.value : null;
      if (validate) {
        if (selected.length !== expected) {
          toast(`Select exactly ${expected} option(s) before continuing`, true);
          return false;
        }
        if (!confidence) {
          toast("Choose a confidence level before continuing", true);
          return false;
        }
      }
      runner.answers.set(r.question_id, { selected, confidence });
      return true;
    }
  }

  async function submitRunner() {
    const panel = document.getElementById("view-diagnostic");
    if (!confirm("Submit your answers? You cannot change them after submitting.")) return;
    const responses = runner.attempt.responses.map((r) => {
      const a = runner.answers.get(r.question_id);
      return { question_id: r.question_id, selected: a.selected, confidence: a.confidence };
    });
    panel.innerHTML = '<p class="empty-state">Scoring…</p>';
    try {
      const results = await diag.submit(runner.attempt.id, responses);
      renderResults(results);
    } catch (e) {
      panel.innerHTML = `<p class="empty-state">Submit failed: ${escapeHtml(e.message)}</p>
        <button type="button" class="secondary" data-back>Back to Study Next</button>`;
      panel.querySelector("[data-back]").addEventListener("click", backFromDiagnostic);
    }
  }

  function renderResults(results) {
    const panel = document.getElementById("view-diagnostic");
    const passClass = results.passed ? "pass" : "fail";
    const reused = results.reused_question_ids && results.reused_question_ids.length;
    panel.innerHTML = `
      <div class="card">
        <h2 tabindex="-1" id="results-heading">${results.passed ? "Passed" : "Needs remediation"}</h2>
        <p><span class="knowledge-badge ${passClass}">${escapeHtml(results.bucket_result || "")}</span></p>
        <table><tbody>
          <tr><td>Raw score</td><td>${results.raw_score_pct}% (pass threshold 85%)</td></tr>
          <tr><td>Confidence-adjusted score</td><td>${results.effective_score_pct}% (pass threshold 80%)</td></tr>
          <tr><td>Question reuse</td><td>${reused ? `${results.reused_question_ids.length} question(s) reused from a prior attempt` : "All questions were new to you"}</td></tr>
          <tr><td>Selection disclosure</td><td>${escapeHtml(results.selection_disclosure || "")}</td></tr>
        </tbody></table>
        ${results.passed
          ? '<p class="empty-state">This is provisional mastery from a multiple-choice diagnostic, not a guarantee of exam readiness or hands-on ability. A 14-day retention check is scheduled.</p>'
          : '<p class="empty-state">Focus only on the gaps below — everything else in this section stays marked as already understood.</p>'}
        <div class="filters">
          <button type="button" class="secondary" data-back>Back to Study Next</button>
        </div>
      </div>
      ${results.gaps && results.gaps.length ? `<div class="card"><h2>Gaps to review (${results.gaps.length})</h2><div id="gap-list"></div></div>` : ""}`;
    panel.querySelector("[data-back]").addEventListener("click", backFromDiagnostic);
    const heading = panel.querySelector("#results-heading");
    if (heading) heading.focus();
    if (results.gaps && results.gaps.length) {
      const gapList = panel.querySelector("#gap-list");
      gapList.innerHTML = results.gaps.map(gapCardHtml).join("");
      wireGapCards(gapList, results);
    }
  }

  function gapCardHtml(g) {
    const yourAnsText = (g.submitted_answer_text && g.submitted_answer_text.length)
      ? g.submitted_answer_text.map(escapeHtml).join("; ")
      : (g.submitted_answer && g.submitted_answer.length ? g.submitted_answer.join(", ") : "None");
    const correctAnsText = (g.correct_answer_text && g.correct_answer_text.length)
      ? g.correct_answer_text.map(escapeHtml).join("; ")
      : (g.correct_answers && g.correct_answers.length ? g.correct_answers.join(", ") : "None");
    const expText = g.explanation || g.practice_book_explanation || "";

    return `<article class="gap-card" data-remediation-id="${g.remediation_id}">
      <p class="pill">${g.gap_reason === "incorrect" ? "Incorrect" : "Correct, but low confidence"}</p>
      <p><strong>${escapeHtml(g.prompt_snapshot)}</strong></p>
      <p class="empty-state">Your answer: ${yourAnsText} · Correct answer: ${correctAnsText}</p>
      ${expText ? `<p class="empty-state"><strong>Practice-book explanation:</strong> ${escapeHtml(expText)}</p>` : ""}
      <p>${escapeHtml(g.recall_prompt)}</p>
      <p class="empty-state">${escapeHtml(g.lab_scaffold)}</p>
      ${g.readings.length
        ? `<div class="readings">${g.readings
            .map(
              (rd) => `<div class="reading-cite">
                <p><strong>${escapeHtml(rd.book_title)}</strong> (<span class="pill">${escapeHtml(rd.book_slug)}</span>)</p>
                <p><strong>Section:</strong> ${escapeHtml(rd.section_title)} — <code class="section-id">${escapeHtml(rd.section_stable_id)}</code></p>
                <p class="empty-state" style="word-break:break-all"><strong>Content hash:</strong> ${escapeHtml(rd.content_hash)}</p>
                <button type="button" class="secondary" data-open-section="${escapeHtml(rd.section_stable_id)}">View section</button>
                <p class="empty-state">${escapeHtml(rd.snippet)}</p>
                <p class="empty-state">Retrieval basis: ${escapeHtml(rd.retrieval_basis)}</p>
                <div class="section-detail" hidden></div>
              </div>`
            )
            .join("")}</div>`
        : '<p class="empty-state">No relevant non-practice-book sections were found via search for this question.</p>'}
      <div class="filters">
        <button type="button" class="secondary" data-mark-reviewed="${g.remediation_id}" ${g.status === "reviewed" ? "disabled" : ""}>
          ${g.status === "reviewed" ? "Reviewed" : "Mark reviewed"}
        </button>
      </div>
    </article>`;
  }

  function wireGapCards(root, results) {
    root.querySelectorAll("[data-open-section]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const box = btn.closest(".reading-cite").querySelector(".section-detail");
        if (!box.hidden) { box.hidden = true; return; }
        try {
          const section = await api(`/api/sections/${encodeURIComponent(btn.dataset.openSection)}`);
          box.innerHTML = `<p><em>${escapeHtml(section.book_title)} — ${escapeHtml(section.title)} (${escapeHtml(section.stable_id)})</em></p>
            <div class="full-section-content">${escapeHtml(section.content)}</div>`;
          box.hidden = false;
        } catch (e) {
          toast(e.message, true);
        }
      });
    });
    root.querySelectorAll("[data-mark-reviewed]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await diag.markReviewed(parseInt(btn.dataset.markReviewed, 10));
          btn.textContent = "Reviewed";
          btn.disabled = true;
          toast("Marked reviewed");
        } catch (e) {
          toast(e.message, true);
        }
      });
    });
  }

  async function openScopeDetail(scopeId) {
    showDiagnosticView();
    const panel = document.getElementById("view-diagnostic");
    panel.innerHTML = '<p class="empty-state">Loading…</p>';
    try {
      const scope = await diag.getScope(scopeId);
      panel.innerHTML = `
        <div class="card">
          <h2 tabindex="-1" id="scope-heading">${escapeHtml(scope.name)}</h2>
          <p>${masteryBadge(scope)}</p>
          <p class="empty-state">${escapeHtml(scope.provenance)}</p>
          <table><tbody>
            <tr><td>Scope type</td><td>${escapeHtml(scope.scope_type)}</td></tr>
            <tr><td>Available questions</td><td>${scope.available_question_count}</td></tr>
            <tr><td>Question target</td><td>${scope.question_target}</td></tr>
            <tr><td>Retest available</td><td>${scope.retest_available ? "yes" : "no — review open gaps first"}</td></tr>
          </tbody></table>
          ${knowledgeActionsHtml({ ...scope, mastery_status: scope.mastery ? scope.mastery.status : "unassessed", retention_due_at: scope.mastery ? scope.mastery.retention_due_at : null, open_gap_count: scope.remediation_items.filter((r) => r.status === "open").length })}
          <div class="filters"><button type="button" class="secondary" data-back>Back to Study Next</button></div>
        </div>
        <div class="card">
          <h2>Recent attempts</h2>
          ${scope.recent_attempts.length
            ? `<table><thead><tr><th>Mode</th><th>State</th><th>Started</th><th>Score</th><th>Result</th></tr></thead><tbody>${scope.recent_attempts
                .map(
                  (a) => `<tr><td>${escapeHtml(a.mode)}</td><td>${escapeHtml(a.state)}</td><td>${escapeHtml(a.started_at)}</td>
                    <td>${a.raw_score_pct !== null ? a.raw_score_pct + "%" : "-"}</td>
                    <td>${a.state === "submitted" ? `<button type="button" class="secondary" data-view-results="${a.id}">${escapeHtml(a.bucket_result || "")}</button>` : "-"}</td></tr>`
                )
                .join("")}</tbody></table>`
            : '<p class="empty-state">No attempts yet.</p>'}
        </div>`;
      panel.querySelector("[data-back]").addEventListener("click", backFromDiagnostic);
      wireKnowledgeActions(panel);
      panel.querySelectorAll("[data-view-results]").forEach((btn) => {
        btn.addEventListener("click", () => resumeAttemptResults(parseInt(btn.dataset.viewResults, 10)));
      });
      const heading = panel.querySelector("#scope-heading");
      if (heading) heading.focus();
    } catch (e) {
      panel.innerHTML = `<p class="empty-state">${escapeHtml(e.message)}</p>`;
    }
  }

  // --- View registry ---------------------------------------------------

  const views = {
    next: renderStudyNext,
    overview: renderOverview,
    curriculum: renderCurriculum,
    library: renderLibrary,
    search: renderSearch,
    objectives: renderObjectives,
    practice: renderPractice,
    settings: renderSettings,
  };

  function activate(name) {
    document.querySelectorAll(".tab").forEach((btn) => {
      if (btn.dataset.view === name) btn.setAttribute("aria-current", "page");
      else btn.removeAttribute("aria-current");
    });
    document.querySelectorAll(".view").forEach((panel) => {
      panel.hidden = panel.dataset.viewPanel !== name;
    });
    const panel = document.getElementById("view-" + name);
    let renderPromise = Promise.resolve();
    if (panel) {
      panel.innerHTML = '<p class="empty-state">Loading…</p>';
      renderPromise = views[name](panel).catch((err) => {
        panel.innerHTML = `<p class="empty-state">Failed to load: ${escapeHtml(err.message)}</p>`;
      });
    }
    location.hash = name;
    return renderPromise;
  }

  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => activate(btn.dataset.view));
  });

  // --- Overview ----------------------------------------------------------

  function statTile(label, value, extra) {
    const cls = value === null || value === undefined ? " na" : "";
    return `<div class="stat-tile"><span class="value${cls}">${value === null || value === undefined ? "No data yet" : escapeHtml(value)}</span><span class="label">${escapeHtml(label)}</span>${extra || ""}</div>`;
  }

  function studyNextActionHtml(item, primary) {
    const cls = primary ? "" : "secondary";
    const action = item.action || {};
    if (action.type === "diagnostic") {
      const label = action.mode === "retention" ? "Start retention check"
        : action.mode === "retest" ? "Start fresh retest"
        : item.eyebrow === "Continue" ? "Continue check" : "Start knowledge check";
      return `<button type="button" class="${cls}" data-diag-action="${escapeHtml(action.mode)}" data-scope-id="${action.scope_id}">${label}</button>`;
    }
    if (action.type === "scope_detail") {
      return `<button type="button" class="${cls}" data-diag-view-scope="${action.scope_id}">Review focused gaps</button>`;
    }
    if (action.type === "task") {
      return `<button type="button" class="${cls}" data-focus-task="${action.task_id}">Open curriculum task</button>`;
    }
    return "";
  }

  function wireStudyNextActions(root) {
    wireKnowledgeActions(root);
    root.querySelectorAll("[data-focus-task]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const taskId = btn.dataset.focusTask;
        await activate("curriculum");
        const task = document.getElementById(`task-${taskId}`);
        if (task) {
          task.scrollIntoView({ behavior: "smooth", block: "center" });
          task.focus();
        }
      });
    });
  }

  async function renderStudyNext(panel) {
    const queue = await api("/api/study-next");
    if (!queue.primary) {
      panel.innerHTML = `<div class="card study-next-empty">
        <p class="queue-eyebrow">Queue clear</p>
        <h2>Nothing is waiting for you</h2>
        <p>Your retention checks, focused gaps, and curriculum tasks are all clear.</p>
      </div>`;
      return;
    }

    const primary = queue.primary;
    const remaining = queue.items.slice(1);
    const cleanWeekTitle = String(queue.week_title || "").replace(
      new RegExp(`^Week\\s+${queue.current_week}\\s*:\\s*`, "i"), ""
    );
    panel.innerHTML = `
      <section class="study-next-hero" aria-labelledby="study-next-heading">
        <div>
          <p class="queue-eyebrow">${escapeHtml(primary.eyebrow)}</p>
          <h2 id="study-next-heading">${escapeHtml(primary.title)}</h2>
          <p>${escapeHtml(primary.description)}</p>
          <p class="queue-reason">${escapeHtml(primary.reason)}</p>
        </div>
        <div class="study-next-primary-action">${studyNextActionHtml(primary, true)}</div>
      </section>
      <div class="queue-context" aria-label="Current study context">
        <span><strong>${escapeHtml(queue.current_exam || "No exam")}</strong></span>
        <span>Week ${escapeHtml(queue.current_week)}${cleanWeekTitle ? `: ${escapeHtml(cleanWeekTitle)}` : ""}</span>
        <span>${queue.counts.open_gaps} open gap${queue.counts.open_gaps === 1 ? "" : "s"}</span>
        <span>${queue.counts.retention_due} retention due</span>
      </div>
      <section class="card" aria-labelledby="after-that-heading">
        <h2 id="after-that-heading">After that</h2>
        ${remaining.length
          ? `<ol class="queue-list">${remaining.map((item, index) => `
              <li class="queue-item">
                <span class="queue-index" aria-hidden="true">${index + 2}</span>
                <div class="queue-copy">
                  <p class="queue-eyebrow">${escapeHtml(item.eyebrow)}</p>
                  <h3>${escapeHtml(item.title)}</h3>
                  <p>${escapeHtml(item.description)}</p>
                </div>
                <div class="queue-action">${studyNextActionHtml(item, false)}</div>
              </li>`).join("")}</ol>`
          : '<p class="empty-state">Complete the first action and this queue will refresh from your saved evidence.</p>'}
      </section>
      <p class="queue-footnote">Order: due retention, focused gaps, section knowledge check, then incomplete curriculum tasks.</p>`;
    wireStudyNextActions(panel);
  }

  async function renderOverview(panel) {
    const d = await api("/api/dashboard");
    const pct = d.completed_tasks && d.total_tasks ? Math.round((d.completed_tasks / d.total_tasks) * 1000) / 10 : 0;
    panel.innerHTML = `
      <div class="card">
        <h2>Where you are</h2>
        <div class="grid">
          ${statTile("Current exam", d.current_exam)}
          ${statTile("Current week", d.current_week ? `Week ${d.current_week}` : null)}
          ${statTile("Next action", d.next_task ? (d.next_task.title || d.next_task.detail) : null)}
          ${statTile("Total study hours", d.total_hours)}
          ${statTile("Hours (last 7 days)", d.hours_last_7_days)}
        </div>
      </div>
      <div class="card">
        <h2>Plan progress</h2>
        <p>${d.completed_tasks} / ${d.total_tasks} tasks complete (${pct}%)</p>
        <div class="progress-bar"><span style="width:${pct}%"></span></div>
      </div>
      ${diagnosticsSummaryCardHtml(d.diagnostics)}
      <div class="card">
        <h2>Readiness (heuristic, not a guarantee)</h2>
        <p><span class="readiness-badge">${escapeHtml(d.readiness_label)}</span></p>
        <table>
          <thead><tr><th>Component</th><th>Value</th></tr></thead>
          <tbody>
            <tr><td>Plan progress</td><td>${d.readiness_components.plan_progress_pct ?? "No data yet"}${d.readiness_components.plan_progress_pct !== null ? "%" : ""}</td></tr>
            <tr><td>Recent practice average</td><td>${d.readiness_components.practice_average_recent_pct ?? "No data yet"}${d.readiness_components.practice_average_recent_pct !== null ? "%" : ""}</td></tr>
            <tr><td>Objective coverage</td><td>${d.readiness_components.objective_coverage_pct ?? "No data yet"}${d.readiness_components.objective_coverage_pct !== null ? "%" : ""}</td></tr>
          </tbody>
        </table>
      </div>
      <div class="card">
        <h2>Weak objectives</h2>
        ${d.weak_objectives.length
          ? `<table><thead><tr><th>Code</th><th>Description</th><th>Avg %</th><th>Attempts</th></tr></thead><tbody>${d.weak_objectives
              .map((w) => `<tr><td>${escapeHtml(w.exam_code)} ${escapeHtml(w.code)}</td><td>${escapeHtml(w.description)}</td><td>${w.average_pct}%</td><td>${w.attempts}</td></tr>`)
              .join("")}</tbody></table>`
          : '<p class="empty-state">No weak objectives identified yet — log some practice attempts to see this.</p>'}
      </div>`;
  }

  // --- Curriculum ----------------------------------------------------

  async function renderCurriculum(panel) {
    const plan = await api("/api/plan");
    panel.innerHTML = `
      <div class="card">
        <h2>${escapeHtml(plan.name)}</h2>
        <p>${escapeHtml(plan.description)}</p>
        <div class="filters">
          <button type="button" data-filter="all" class="secondary">All weeks</button>
          <button type="button" data-filter="220-1201" class="secondary">Core 1</button>
          <button type="button" data-filter="220-1202" class="secondary">Core 2</button>
        </div>
      </div>
      <div class="week-grid" id="week-grid"></div>`;
    const grid = panel.querySelector("#week-grid");

    function draw(filter) {
      grid.innerHTML = plan.weeks
        .filter((w) => filter === "all" || w.exam_code === filter)
        .map(weekCardHtml)
        .join("");
      grid.querySelectorAll("input[type=checkbox]").forEach((cb) => {
        cb.addEventListener("change", async () => {
          try {
            await api(`/api/plan/tasks/${cb.dataset.taskId}`, {
              method: "POST",
              body: JSON.stringify({ completed: cb.checked }),
            });
            toast("Task updated");
            renderOverview(document.getElementById("view-overview"));
          } catch (e) {
            cb.checked = !cb.checked;
            toast(e.message, true);
          }
        });
      });
      grid.querySelectorAll("textarea[data-task-id]").forEach((ta) => {
        ta.addEventListener("blur", async () => {
          try {
            await api(`/api/plan/tasks/${ta.dataset.taskId}`, {
              method: "POST",
              body: JSON.stringify({ notes: ta.value }),
            });
            toast("Notes saved");
          } catch (e) {
            toast(e.message, true);
          }
        });
      });
      wireKnowledgeActions(grid);
    }

    function weekCardHtml(w) {
      const scope = w.diagnostic_scope;
      const mastered = scope && ["provisional_mastery", "mastered_after_remediation"].includes(scope.mastery_status);
      const done = w.tasks.length && w.tasks.every((t) => t.completed || t.exemption_reason);
      const taskListHtml = `<ul class="task-list">
          ${w.tasks
            .map((t) =>
              t.exemption_reason
                ? `<li class="exempted">
                    <span class="task-type">${escapeHtml(t.type)}</span>
                    <div><span>${escapeHtml(t.title)}</span>
                      <p class="empty-state">Exempted by knowledge check on ${escapeHtml(formatDate(t.exempted_at))} — not marked complete.</p>
                    </div>
                  </li>`
                : `<li>
                <input type="checkbox" data-task-id="${t.id}" ${t.completed ? "checked" : ""} id="task-${t.id}" aria-describedby="task-${t.id}-desc">
                <div>
                  <label for="task-${t.id}"><span class="task-type">${escapeHtml(t.type)}</span> ${escapeHtml(t.title)}</label>
                  <p id="task-${t.id}-desc" class="empty-state">${escapeHtml(t.description || "")}</p>
                  <textarea data-task-id="${t.id}" placeholder="Notes…">${escapeHtml(t.notes || "")}</textarea>
                </div>
              </li>`
            )
            .join("")}
        </ul>`;
      return `<article class="week-card${done ? " done" : ""}">
        <header><h3>${escapeHtml(w.title)}</h3><span class="exam-tag">${escapeHtml(w.exam_code || "")}</span></header>
        ${scope ? `<div class="knowledge-check">${masteryBadge({ ...scope, mastery_status: scope.mastery_status })}${knowledgeActionsHtml(scope)}</div>` : ""}
        ${mastered ? `<details><summary>Task list (already understood — collapsed)</summary>${taskListHtml}</details>` : taskListHtml}
      </article>`;
    }

    panel.querySelectorAll("[data-filter]").forEach((btn) => {
      btn.addEventListener("click", () => draw(btn.dataset.filter));
    });
    draw("all");
  }

  // --- Library -------------------------------------------------------

  async function renderLibrary(panel) {
    const data = await api("/api/books");
    panel.innerHTML = `<div class="grid">${data.books
      .map(
        (b) => `<div class="card">
          <h2>${escapeHtml(b.title)}</h2>
          <p>${escapeHtml(b.creator || "")}</p>
          <table>
            <tbody>
              <tr><td>Sections</td><td>${b.section_count}</td></tr>
              <tr><td>Total words</td><td>${b.total_words.toLocaleString()}</td></tr>
              <tr><td>Converter version</td><td>${escapeHtml(b.converter_version)}</td></tr>
              <tr><td>Generated by</td><td>${escapeHtml(b.generated_by)}</td></tr>
              <tr><td>Source EPUB SHA-256</td><td style="word-break:break-all">${escapeHtml(b.source_epub_sha256)}</td></tr>
              <tr><td>Corpus SHA-256 (ingest fingerprint)</td><td style="word-break:break-all">${escapeHtml(b.corpus_sha256)}</td></tr>
              <tr><td>Ingested at</td><td>${escapeHtml(b.ingested_at)}</td></tr>
              <tr><td>Source directory</td><td style="word-break:break-all">${escapeHtml(b.source_dir)}</td></tr>
            </tbody>
          </table>
        </div>`
      )
      .join("")}</div>`;
  }

  // --- Search --------------------------------------------------------

  async function renderSearch(panel) {
    const books = await api("/api/books");
    panel.innerHTML = `
      <div class="card">
        <form id="search-form" class="filters">
          <label for="search-q">Query</label>
          <input type="search" id="search-q" name="q" required minlength="1">
          <label for="search-book">Book</label>
          <select id="search-book"><option value="">All books</option>${books.books
            .map((b) => `<option value="${escapeHtml(b.slug)}">${escapeHtml(b.title.slice(0, 40))}</option>`)
            .join("")}</select>
          <label for="search-exam">Exam</label>
          <select id="search-exam"><option value="">Any</option><option value="220-1201">Core 1</option><option value="220-1202">Core 2</option></select>
          <button type="submit">Search</button>
        </form>
      </div>
      <div id="search-results"></div>`;
    const resultsEl = panel.querySelector("#search-results");
    panel.querySelector("#search-form").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const q = panel.querySelector("#search-q").value;
      const book = panel.querySelector("#search-book").value;
      const exam = panel.querySelector("#search-exam").value;
      const params = new URLSearchParams({ q, limit: "20" });
      if (book) params.set("book", book);
      if (exam) params.set("exam", exam);
      resultsEl.innerHTML = '<p class="empty-state">Searching…</p>';
      try {
        const data = await api("/api/search?" + params.toString());
        resultsEl.innerHTML = data.results.length
          ? data.results
              .map(
                (r) => `<div class="search-result">
                  <span class="pill">${escapeHtml(r.book_slug)}</span>
                  <strong>${escapeHtml(r.title)}</strong>
                  <button type="button" class="secondary" data-stable-id="${escapeHtml(r.stable_id)}">Open</button>
                  <p>${snippetToHtml(r.snippet)}</p>
                  <div class="section-detail" hidden></div>
                </div>`
              )
              .join("")
          : '<p class="empty-state">No matches.</p>';
        resultsEl.querySelectorAll("button[data-stable-id]").forEach((btn) => {
          btn.addEventListener("click", async () => {
            const box = btn.closest(".search-result").querySelector(".section-detail");
            if (!box.hidden) { box.hidden = true; return; }
            const section = await api(`/api/sections/${encodeURIComponent(btn.dataset.stableId)}`);
            box.innerHTML = `<p><em>${escapeHtml(section.book_title)} — ${escapeHtml(section.title)} (${escapeHtml(section.stable_id)})</em></p>
              <p>${escapeHtml(section.content.slice(0, 1200))}${section.content.length > 1200 ? "…" : ""}</p>
              ${section.objectives.length ? `<p>Objectives: ${section.objectives.map((o) => `<span class="pill">${escapeHtml(o.exam_code)} ${escapeHtml(o.code)}</span>`).join("")}</p>` : ""}`;
            box.hidden = false;
          });
        });
      } catch (e) {
        resultsEl.innerHTML = `<p class="empty-state">${escapeHtml(e.message)}</p>`;
      }
    });
  }

  // --- Objectives ------------------------------------------------------

  async function renderObjectives(panel) {
    panel.innerHTML = `
      <div class="filters">
        <label for="obj-exam">Exam</label>
        <select id="obj-exam"><option value="">Both</option><option value="220-1201">Core 1</option><option value="220-1202">Core 2</option></select>
      </div>
      <div id="obj-list"></div>`;
    const listEl = panel.querySelector("#obj-list");

    async function draw(exam) {
      const data = await api("/api/objectives" + (exam ? `?exam=${exam}` : ""));
      const byExam = {};
      data.objectives.forEach((o) => {
        byExam[o.exam_code] = byExam[o.exam_code] || {};
        const dom = o.domain_name || "Unassigned domain";
        byExam[o.exam_code][dom] = byExam[o.exam_code][dom] || [];
        byExam[o.exam_code][dom].push(o);
      });
      listEl.innerHTML = Object.keys(byExam)
        .sort()
        .map(
          (examCode) => `<div class="card"><h2>${escapeHtml(examCode)}</h2>${Object.keys(byExam[examCode])
            .map(
              (dom) => `<h3>${escapeHtml(dom)}</h3><table><thead><tr><th>Code</th><th>Description</th><th>Evidence</th><th>Confidence</th></tr></thead><tbody>${byExam[examCode][dom]
                .map(
                  (o) => `<tr><td>${escapeHtml(o.code)}</td><td>${escapeHtml(o.description)}</td><td><button type="button" class="secondary" data-obj-id="${o.id}">${o.chunk_count} chunk(s)</button></td><td>${o.confidence}</td></tr>
                  <tr class="obj-detail" data-obj-detail="${o.id}" hidden><td colspan="4"></td></tr>`
                )
                .join("")}</tbody></table>`
            )
            .join("")}</div>`
        )
        .join("");
      listEl.querySelectorAll("button[data-obj-id]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const row = listEl.querySelector(`.obj-detail[data-obj-detail="${btn.dataset.objId}"]`);
          if (!row.hidden) { row.hidden = true; return; }
          const obj = await api(`/api/objectives/${btn.dataset.objId}`);
          row.querySelector("td").innerHTML = `<p class="empty-state">${escapeHtml(obj.provenance || "")}</p>` +
            (obj.evidence.length
              ? obj.evidence.map((e) => `<div class="pill">${escapeHtml(e.book_slug)}: ${escapeHtml(e.title)}</div>`).join(" ")
              : '<p class="empty-state">No linked evidence.</p>');
          row.hidden = false;
        });
      });
    }
    panel.querySelector("#obj-exam").addEventListener("change", (e) => draw(e.target.value));
    await draw("");
  }

  // --- Practice --------------------------------------------------------

  async function renderPractice(panel) {
    const [attemptsData, sessionsData, scopesData] = await Promise.all([
      api("/api/attempts"), api("/api/sessions"), diag.listScopes(),
    ]);
    panel.innerHTML = `
      <div class="card">
        <h2>Knowledge checks</h2>
        <p class="empty-state">Adaptive multiple-choice checks drawn from the practice-test bank, one per curriculum week. See Curriculum for the primary flow — this is a quick-access list.</p>
        ${scopesData.scopes.length
          ? `<table><thead><tr><th>Week</th><th>Scope</th><th>Status</th><th>Gaps</th><th></th></tr></thead><tbody>${scopesData.scopes
              .map(
                (s) => `<tr>
                  <td>${s.week_number ? "Week " + s.week_number : "-"}</td>
                  <td>${escapeHtml(s.name)}</td>
                  <td>${masteryBadge(s)}</td>
                  <td>${s.open_gap_count || 0}</td>
                  <td><button type="button" class="secondary" data-diag-view-scope="${s.id}">Open</button></td>
                </tr>`
              )
              .join("")}</tbody></table>`
          : '<p class="empty-state">No knowledge-check scopes yet — run ingest to import the practice-test question bank.</p>'}
      </div>
      <div class="card">
        <h2>Log a practice attempt</h2>
        <form id="attempt-form" class="filters">
          <label for="a-exam">Exam</label>
          <select id="a-exam" required><option value="1">Core 1 (220-1201)</option><option value="2">Core 2 (220-1202)</option></select>
          <label for="a-score">Score</label>
          <input type="number" id="a-score" min="0" required style="width:5em">
          <label for="a-total">Total</label>
          <input type="number" id="a-total" min="1" required style="width:5em">
          <label for="a-date">When</label>
          <input type="datetime-local" id="a-date" required>
          <label><input type="checkbox" id="a-held-out"> Held-out (untouched question set)</label>
          <button type="submit">Log attempt</button>
        </form>
        <p class="empty-state">Held-out attempts are excluded from the recent-average and weak-objectives metrics so previously-seen questions don't inflate your score.</p>
      </div>
      <div class="card">
        <h2>Log study time</h2>
        <form id="session-form" class="filters">
          <label for="s-date">When</label>
          <input type="datetime-local" id="s-date" required>
          <label for="s-minutes">Minutes</label>
          <input type="number" id="s-minutes" min="1" required style="width:5em">
          <label for="s-notes">Notes</label>
          <input type="text" id="s-notes">
          <button type="submit">Log session</button>
        </form>
      </div>
      <div class="card">
        <h2>Recent attempts</h2>
        <div id="attempts-table"></div>
      </div>
      <div class="card">
        <h2>Recent sessions</h2>
        <div id="sessions-table"></div>
      </div>`;

    function attemptsTable(rows) {
      return rows.length
        ? `<table><thead><tr><th>When</th><th>Exam</th><th>Score</th><th>%</th><th>Held out</th><th>Notes</th></tr></thead><tbody>${rows
            .map(
              (a) => `<tr><td>${escapeHtml(a.occurred_at)}</td><td>${escapeHtml(a.exam_code)}</td><td>${a.score}/${a.total}</td><td>${Math.round((a.score / a.total) * 1000) / 10}%</td><td>${a.held_out ? "yes" : "no"}</td><td>${escapeHtml(a.notes || "")}</td></tr>`
            )
            .join("")}</tbody></table>`
        : '<p class="empty-state">No practice attempts logged yet.</p>';
    }
    function sessionsTable(rows) {
      return rows.length
        ? `<table><thead><tr><th>When</th><th>Minutes</th><th>Notes</th></tr></thead><tbody>${rows
            .map((s) => `<tr><td>${escapeHtml(s.occurred_at)}</td><td>${s.duration_minutes}</td><td>${escapeHtml(s.notes || "")}</td></tr>`)
            .join("")}</tbody></table>`
        : '<p class="empty-state">No study sessions logged yet.</p>';
    }
    panel.querySelector("#attempts-table").innerHTML = attemptsTable(attemptsData.attempts);
    panel.querySelector("#sessions-table").innerHTML = sessionsTable(sessionsData.sessions);
    wireKnowledgeActions(panel);

    panel.querySelector("#attempt-form").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      try {
        await api("/api/attempts", {
          method: "POST",
          body: JSON.stringify({
            exam_id: parseInt(panel.querySelector("#a-exam").value, 10),
            score: parseInt(panel.querySelector("#a-score").value, 10),
            total: parseInt(panel.querySelector("#a-total").value, 10),
            occurred_at: new Date(panel.querySelector("#a-date").value).toISOString(),
            held_out: panel.querySelector("#a-held-out").checked,
          }),
        });
        toast("Attempt logged");
        renderPractice(panel);
      } catch (e) {
        toast(e.message, true);
      }
    });
    panel.querySelector("#session-form").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      try {
        await api("/api/sessions", {
          method: "POST",
          body: JSON.stringify({
            occurred_at: new Date(panel.querySelector("#s-date").value).toISOString(),
            duration_minutes: parseInt(panel.querySelector("#s-minutes").value, 10),
            notes: panel.querySelector("#s-notes").value || null,
          }),
        });
        toast("Session logged");
        renderPractice(panel);
      } catch (e) {
        toast(e.message, true);
      }
    });
  }

  // --- Settings / Data -------------------------------------------------

  async function renderSettings(panel) {
    const health = await api("/api/health");
    panel.innerHTML = `
      <div class="warning-banner">
        This is a private local prototype bound to 127.0.0.1 with a same-origin + per-process CSRF
        check on writes. It has no user accounts or transport encryption. Do not expose this port
        beyond localhost without adding real authentication and TLS in front of it.
      </div>
      <div class="card">
        <h2>Health</h2>
        <table><tbody>
          <tr><td>Status</td><td>${escapeHtml(health.status)}</td></tr>
          <tr><td>Schema version</td><td>${escapeHtml(health.schema_version)}</td></tr>
          <tr><td>Server time</td><td>${escapeHtml(health.time)}</td></tr>
        </tbody></table>
      </div>
      <div class="card">
        <h2>Export snapshot</h2>
        <p>Download a versioned portable JSON snapshot of books, objectives, plan, sessions, and attempts.</p>
        <button type="button" id="export-btn">Download export</button>
      </div>`;
    panel.querySelector("#export-btn").addEventListener("click", async () => {
      try {
        const data = await api("/api/export");
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `study-library-export-${new Date().toISOString().slice(0, 10)}.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } catch (e) {
        toast(e.message, true);
      }
    });
  }

  // --- Boot --------------------------------------------------------------

  const initial = location.hash ? location.hash.slice(1) : "next";
  activate(views[initial] ? initial : "next");
})();
