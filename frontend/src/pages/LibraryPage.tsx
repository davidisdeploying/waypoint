import {FormEvent, useState} from "react";
import {useQuery} from "@tanstack/react-query";
import {Link} from "react-router-dom";
import {queries} from "../api";
import {ErrorNotice, Loading, Panel} from "../components";
import {dossierEvidenceLabel, dossierStatusLabel} from "../dossiers";
import {sourceRefreshMessage} from "../sourceRefresh";
import {BookReader, type ReaderBook} from "../BookReader";

function snippet(value: string) {
  return value.replace(/\[|\]/g, "");
}

export function LibraryPage() {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [book, setBook] = useState("");
  const [exam, setExam] = useState("");
  const [openSection, setOpenSection] = useState("");
  const [readerBook, setReaderBook] = useState<ReaderBook | null>(null);
  const booksQuery = useQuery({queryKey: ["books"], queryFn: queries.books});
  const packQuery = useQuery({
    queryKey: ["certification-pack", "aplus"],
    queryFn: queries.certificationPack,
  });
  const buildQuery = useQuery({
    queryKey: ["certification-pack-builds", "aplus"],
    queryFn: queries.certificationPackBuilds,
  });
  const dossiersQuery = useQuery({
    queryKey: ["objective-dossiers", "aplus"],
    queryFn: queries.objectiveDossiers,
  });
  const jobsQuery = useQuery({
    queryKey: ["library-jobs"],
    queryFn: queries.jobs,
    refetchInterval: 5_000,
  });
  const searchQuery = useQuery({
    queryKey: ["search", query, book, exam],
    queryFn: () => queries.search(query, book, exam),
    enabled: Boolean(query),
  });
  const sectionQuery = useQuery({
    queryKey: ["section", openSection],
    queryFn: () => queries.section(openSection),
    enabled: Boolean(openSection),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (draft.trim()) setQuery(draft.trim());
  }

  if (booksQuery.isLoading) return <Loading label="Opening your library" />;
  if (booksQuery.error) return <ErrorNotice error={booksQuery.error} />;
  const books = booksQuery.data!.books;
  const wordCount = books.reduce((total, item) => total + item.total_words, 0);
  const dossierExams = dossiersQuery.data
    ? Array.from(new Set(
      dossiersQuery.data.objectives.map((objective) => objective.exam_code),
    ))
    : [];

  return (
    <>
      <div className="page-title">
        <span className="eyebrow">Library</span>
        <h1>Your compiled knowledge base</h1>
        <p>
          Official exam scope, verified book editions, and stable citations.
          Search only after the compiler decides which sources are safe to use.
        </p>
      </div>

      <Panel eyebrow="Full-text evidence" title="Search the approved corpus">
        <form className="search-form" onSubmit={submit}>
          <label>
            Query
            <input value={draft} onChange={(event) => setDraft(event.target.value)} type="search" placeholder="subnet mask" required />
          </label>
          <label>
            Book
            <select value={book} onChange={(event) => setBook(event.target.value)}>
              <option value="">All books</option>
              {books.map((item) => <option key={item.slug} value={item.slug}>{item.title.slice(0, 54)}</option>)}
            </select>
          </label>
          <label>
            Exam
            <select value={exam} onChange={(event) => setExam(event.target.value)}>
              <option value="">Both exams</option>
              <option value="220-1201">Core 1</option>
              <option value="220-1202">Core 2</option>
            </select>
          </label>
          <button className="button primary" type="submit">Search</button>
        </form>
      </Panel>

      <details className="advanced-library">
        <summary>Advanced source integrity and release details</summary>

      {packQuery.isLoading ? <Loading label="Checking certification pack" /> : null}
      {packQuery.error ? <ErrorNotice error={packQuery.error} /> : null}
      {packQuery.data ? (
        <Panel
          eyebrow={`${packQuery.data.certification_name} ${packQuery.data.exam_version}`}
          title={packQuery.data.status === "ready" ? "Knowledge base ready" : "Knowledge base blocked"}
        >
          <div className={`pack-banner ${packQuery.data.status}`}>
            <div>
              <strong>{packQuery.data.covered_count}/{packQuery.data.objective_count}</strong>
              <span>official objectives covered</span>
            </div>
            <div>
              <strong>{packQuery.data.official_count}</strong>
              <span>official CompTIA sources</span>
            </div>
            <div>
              <strong>{packQuery.data.active_source_count}</strong>
              <span>active sources</span>
            </div>
            <div>
              <strong>{packQuery.data.quarantined_count}</strong>
              <span>quarantined</span>
            </div>
          </div>
          <p className="pack-policy">
            CompTIA’s V15 objectives define the scope and supply all{" "}
            {packQuery.data.report.official_objective_text_count} canonical objective headings.
            The review guide supplies focused lessons,
            the textbook adds depth, and the practice-test book is assessment-only. AI may organize
            cited material, but it is never treated as an authority and does not browse the open web
            during study.
          </p>
          {packQuery.data.coverage_by_exam.map((coverage) => (
            <div className="pack-exam" key={coverage.exam_code}>
              <strong>{coverage.exam_code}</strong>
              <span>{coverage.covered_count}/{coverage.objective_count} objectives covered</span>
              <span>{coverage.missing_count ? `${coverage.missing_count} missing` : "No gaps"}</span>
            </div>
          ))}
          {packQuery.data.findings.length ? (
            <div className="pack-findings">
              {packQuery.data.findings.map((finding) => (
                <p key={`${finding.category}-${finding.exam_code}-${finding.objective_code}-${finding.message}`}>
                  <strong>{finding.severity}</strong> {finding.message}
                </p>
              ))}
            </div>
          ) : <p className="notice success">No version conflicts, missing objectives, or source-integrity findings.</p>}
          <details className="pack-sources">
            <summary>Inspect source policy and provenance</summary>
            {packQuery.data.sources.map((source) => (
              <article key={source.source_key}>
                <div>
                  <span className="eyebrow">
                    Tier {source.authority_tier} · {source.use_role.replaceAll("_", " ")}
                  </span>
                  <h3>{source.title}</h3>
                  <p>{source.publisher} · {source.version_label} · {source.exam_codes.join(" + ")}</p>
                </div>
                <span className={`source-state ${source.disposition}`}>{source.disposition}</span>
                <p className="source-reason">{source.status_reason}</p>
                {sourceRefreshMessage(source) ? (
                  <p className={`source-refresh ${source.refresh_status ?? "unchecked"}`}>
                    <strong>{sourceRefreshMessage(source)}</strong>
                    {source.last_checked_at ? (
                      <> Checked {new Date(source.last_checked_at).toLocaleString()}.</>
                    ) : null}
                  </p>
                ) : null}
                {source.source_url ? (
                  <a className="text-link" href={source.source_url} target="_blank" rel="noreferrer">
                    Open official source
                  </a>
                ) : null}
              </article>
            ))}
          </details>
        </Panel>
      ) : null}

      {buildQuery.isLoading ? <Loading label="Checking pack release history" /> : null}
      {buildQuery.error ? <ErrorNotice error={buildQuery.error} /> : null}
      {buildQuery.data?.latest ? (
        <Panel
          eyebrow={`Release gate · build ${buildQuery.data.latest.build_sha256.slice(0, 10)}`}
          title={buildQuery.data.has_pending_preview ? "Pack preview awaiting promotion" : "Published pack is sealed"}
        >
          <p className="pack-policy">
            Compilation cannot silently replace the study knowledge base. A candidate is
            built as an immutable preview, compared with the published pack, and promoted
            only when a fresh compile produces the exact same build hash.
          </p>
          <div className="pack-build-status">
            <div>
              <span>Latest build</span>
              <strong>{buildQuery.data.latest.status}</strong>
            </div>
            <div>
              <span>Compiler</span>
              <strong>{buildQuery.data.latest.compiler_version}</strong>
            </div>
            <div>
              <span>Objectives changed</span>
              <strong>{buildQuery.data.latest.diff.summary.objectives_changed}</strong>
            </div>
            <div>
              <span>Official wording updated</span>
              <strong>{buildQuery.data.latest.diff.summary.official_descriptions_changed}</strong>
            </div>
          </div>
          <p className={`notice ${buildQuery.data.has_pending_preview ? "" : "success"}`}>
            {buildQuery.data.has_pending_preview
              ? "This preview is not active. Promotion remains an explicit operator action after review."
              : `Published ${buildQuery.data.latest.published_at
                ? new Date(buildQuery.data.latest.published_at).toLocaleString()
                : "after an exact-hash review"}.`}
          </p>
          <details className="pack-diff">
            <summary>Inspect the release diff</summary>
            <dl>
              <div><dt>Sources added</dt><dd>{buildQuery.data.latest.diff.summary.sources_added}</dd></div>
              <div><dt>Sources removed</dt><dd>{buildQuery.data.latest.diff.summary.sources_removed}</dd></div>
              <div><dt>Sources changed</dt><dd>{buildQuery.data.latest.diff.summary.sources_changed}</dd></div>
              <div><dt>Objectives added</dt><dd>{buildQuery.data.latest.diff.summary.objectives_added}</dd></div>
              <div><dt>Objectives removed</dt><dd>{buildQuery.data.latest.diff.summary.objectives_removed}</dd></div>
            </dl>
            {buildQuery.data.latest.diff.changes.length ? (
              <ol>
                {buildQuery.data.latest.diff.changes.map((change, index) => (
                  <li key={`${change.kind}-${change.key}-${index}`}>
                    <strong>{change.key}</strong>
                    <span>{change.kind.replaceAll("_", " ")}</span>
                    {change.before && change.after ? (
                      <small>{change.before} → {change.after}</small>
                    ) : null}
                  </li>
                ))}
              </ol>
            ) : <p className="notice success">No effective pack changes.</p>}
          </details>
        </Panel>
      ) : null}

      {dossiersQuery.isLoading ? <Loading label="Compiling objective dossiers" /> : null}
      {dossiersQuery.error ? <ErrorNotice error={dossiersQuery.error} /> : null}
      {dossiersQuery.data ? (
        <Panel
          eyebrow={`Pack inspector · compiler ${dossiersQuery.data.compiler_version}`}
          title="Objective dossier quality"
        >
          <p className="pack-policy">
            Every official objective has a materialized dossier connecting its canonical vendor heading,
            primary lesson, supplemental reading, and assessment source. “Source-complete”
            means those provenance gates passed; it does not claim that you have mastered
            the objective.
          </p>
          <div className="dossier-banner">
            <div>
              <strong>{dossiersQuery.data.counts.complete}</strong>
              <span>source-complete</span>
            </div>
            <div>
              <strong>{dossiersQuery.data.counts.thin}</strong>
              <span>need depth</span>
            </div>
            <div>
              <strong>{dossiersQuery.data.counts.conflicted}</strong>
              <span>conflicted</span>
            </div>
            <div>
              <strong>{dossiersQuery.data.counts.missing}</strong>
              <span>missing</span>
            </div>
          </div>
          <p className="dossier-note">
            Practice questions remain conservatively mapped at domain level unless
            manually linked to an exact objective.
          </p>
          <div className="dossier-exams">
            {dossierExams.map((examCode) => {
              const objectives = dossiersQuery.data!.objectives.filter(
                (objective) => objective.exam_code === examCode,
              );
              return (
                <details key={examCode}>
                  <summary>
                    <strong>{examCode}</strong>
                    <span>{objectives.length} objective dossiers</span>
                  </summary>
                  <div className="dossier-list">
                    {objectives.map((objective) => (
                      <article key={objective.objective_id}>
                        <div className="dossier-objective">
                          <span className="objective-code">{objective.code}</span>
                          <div>
                            <strong>{objective.description}</strong>
                            <small>
                              {objective.domain_name ?? "Unassigned domain"} · {dossierEvidenceLabel(objective)}
                            </small>
                          </div>
                        </div>
                        <div className="dossier-quality">
                          <span className={`dossier-status ${objective.status}`}>
                            {dossierStatusLabel(objective.status)}
                          </span>
                          <strong>{objective.quality_score}/100</strong>
                        </div>
                        <Link className="text-link" to={`/mastery/${objective.objective_id}`}>
                          Inspect objective evidence
                        </Link>
                      </article>
                    ))}
                  </div>
                </details>
              );
            })}
          </div>
        </Panel>
      ) : null}

      </details>

      {searchQuery.isFetching ? <Loading label="Searching citations" /> : null}
      {searchQuery.error ? <ErrorNotice error={searchQuery.error} /> : null}
      {searchQuery.data ? (
        <div className="search-results">
          {searchQuery.data.results.length ? searchQuery.data.results.map((result) => (
            <article className="search-result" key={result.stable_id}>
              <span className="eyebrow">{result.book_slug}</span>
              <h2>{result.title}</h2>
              <p>{snippet(result.snippet)}</p>
              <button className="text-button" onClick={() => setOpenSection(
                openSection === result.stable_id ? "" : result.stable_id,
              )}>
                {openSection === result.stable_id ? "Close section" : "Read cited section"}
              </button>
              {openSection === result.stable_id ? (
                sectionQuery.isLoading ? <Loading /> :
                  sectionQuery.error ? <ErrorNotice error={sectionQuery.error} /> :
                    sectionQuery.data ? (
                      <div className="section-reader">
                        <strong>{sectionQuery.data.book_title}</strong>
                        <p>{sectionQuery.data.content.slice(0, 3200)}{sectionQuery.data.content.length > 3200 ? "..." : ""}</p>
                        <div className="tag-row">
                          {sectionQuery.data.objectives.map((objective) => (
                            <span key={`${objective.exam_code}-${objective.code}`}>{objective.exam_code} {objective.code}</span>
                          ))}
                        </div>
                      </div>
                    ) : null
              ) : null}
            </article>
          )) : <p className="notice">No matching sections.</p>}
        </div>
      ) : null}

      <Panel eyebrow="Corpus" title={`Ingested books · ${books.length} sources · ${wordCount.toLocaleString()} words`}>
        <div className="book-grid">
          {books.map((item) => {
            const readableBook = item as typeof item & ReaderBook;
            const canReadOriginal = Boolean(
              readableBook.original_epub_linked && readableBook.reader_sections?.length,
            );
            return (
            <article key={item.slug}>
              <span className="eyebrow">Converter v{item.converter_version}</span>
              <h3>{item.title}</h3>
              <p>{item.creator}</p>
              <strong>{item.section_count} sections · {item.total_words.toLocaleString()} words</strong>
              <button
                className="button secondary book-reader-open"
                type="button"
                disabled={!canReadOriginal}
                onClick={() => setReaderBook(readableBook)}
              >
                {canReadOriginal ? "Read original EPUB" : "Original EPUB unavailable"}
              </button>
            </article>
          );})}
        </div>
      </Panel>

      {readerBook ? <BookReader book={readerBook} onClose={() => setReaderBook(null)} /> : null}

      <details className="advanced-library">
        <summary>Advanced conversion pipeline</summary>
      <Panel eyebrow="Pipeline" title="Book conversion and indexing">
        {jobsQuery.isLoading ? <Loading label="Checking book jobs" /> : null}
        {jobsQuery.error ? <ErrorNotice error={jobsQuery.error} /> : null}
        {jobsQuery.data?.jobs.length ? (
          <ol className="task-list">
            {jobsQuery.data.jobs.map((job) => (
              <li key={job.id}>
                <span className="task-kind">{job.status} · {job.phase}</span>
                <strong>{job.book_slug}</strong>
                <p>{job.error ?? job.message}</p>
              </li>
            ))}
          </ol>
        ) : (
          <p className="notice">No conversion jobs yet. New EPUBs will appear here from queue through searchable index.</p>
        )}
      </Panel>
      </details>
    </>
  );
}
