import {useMemo, useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {Link, useSearchParams} from "react-router-dom";
import {queries} from "../api";
import {ErrorNotice, Loading, Metric, Panel, formatDate} from "../components";
import type {
  HandsOnLab,
  LabCompletionLevel,
  LabTemplate,
  LabUpdate,
} from "../types";

const levelLabels: Record<LabCompletionLevel, string> = {
  guided: "With step-by-step guidance",
  referenced: "With references",
  unaided: "Unaided",
};

function ResultForm({
  lab,
  pending,
  onComplete,
}: {
  lab: HandsOnLab;
  pending: boolean;
  onComplete: (payload: LabUpdate) => void;
}) {
  const [evidence, setEvidence] = useState("");
  const [reflection, setReflection] = useState("");
  const [level, setLevel] = useState<LabCompletionLevel>("referenced");
  return (
    <div className="lab-result-form">
      <label>
        Evidence and result
        <textarea
          value={evidence}
          onChange={(event) => setEvidence(event.target.value)}
          placeholder="Commands, measurements, test results, configuration changes, or a link to saved evidence."
          maxLength={10000}
        />
      </label>
      <label>
        Reflection
        <textarea
          value={reflection}
          onChange={(event) => setReflection(event.target.value)}
          placeholder="What worked, what failed, and what would you do differently?"
          maxLength={10000}
        />
      </label>
      <label>
        How did you complete it?
        <select
          value={level}
          onChange={(event) => setLevel(event.target.value as LabCompletionLevel)}
        >
          {Object.entries(levelLabels).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </label>
      <button
        className="button primary"
        disabled={pending || !evidence.trim() || !reflection.trim()}
        onClick={() => onComplete({
          status: "completed",
          evidence_text: evidence.trim(),
          reflection_text: reflection.trim(),
          completion_level: level,
        })}
      >
        Complete lab
      </button>
    </div>
  );
}

export function LabsPage() {
  const [searchParams] = useSearchParams();
  const requestedObjective = Number(searchParams.get("objective_id") || 0);
  const queryClient = useQueryClient();
  const labsQuery = useQuery({queryKey: ["labs"], queryFn: () => queries.labs()});
  const catalogQuery = useQuery({queryKey: ["lab-catalog"], queryFn: queries.labCatalog});
  const masteryQuery = useQuery({queryKey: ["mastery-map"], queryFn: () => queries.masteryMap()});
  const [selectedObjective, setSelectedObjective] = useState(requestedObjective);
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [environment, setEnvironment] = useState("");
  const [examFilter, setExamFilter] = useState<"all" | "220-1201" | "220-1202">("all");
  const [launchedTitle, setLaunchedTitle] = useState("");

  const objectives = useMemo(
    () => masteryQuery.data?.exams.flatMap((exam) =>
      exam.domains.flatMap((domain) =>
        domain.objectives.map((objective) => ({
          id: objective.id,
          label: `${exam.code} ${objective.code} · ${objective.description}`,
        })),
      ),
    ) ?? [],
    [masteryQuery.data],
  );
  const objectiveId = selectedObjective || objectives[0]?.id || 0;
  const refresh = () => {
    void queryClient.invalidateQueries({queryKey: ["labs"]});
    void queryClient.invalidateQueries({queryKey: ["lab-catalog"]});
  };
  const launchTemplate = useMutation({
    mutationFn: (template: LabTemplate) =>
      queries.launchLabTemplate(
        template.slug,
        `lab-template:${template.slug}:${Date.now()}`,
      ),
    onSuccess: (lab) => {
      setLaunchedTitle(lab.title);
      refresh();
    },
  });
  const createLab = useMutation({
    mutationFn: queries.createLab,
    onSuccess: () => {
      setTitle("");
      setGoal("");
      setEnvironment("");
      refresh();
    },
  });
  const updateLab = useMutation({
    mutationFn: ({id, payload}: {id: number; payload: LabUpdate}) =>
      queries.updateLab(id, payload),
    onSuccess: refresh,
  });

  if (labsQuery.isLoading || masteryQuery.isLoading || catalogQuery.isLoading) {
    return <Loading label="Opening your lab workspace" />;
  }
  const error = labsQuery.error || masteryQuery.error || catalogQuery.error;
  if (error) return <ErrorNotice error={error} />;
  const data = labsQuery.data!;
  const catalog = catalogQuery.data!;
  const catalogTemplates = catalog.templates.filter((template) => {
    if (requestedObjective && template.objective_id !== requestedObjective) return false;
    return examFilter === "all" || template.exam_code === examFilter;
  });

  return (
    <>
      <div className="page-title">
        <span className="eyebrow">Hands-on labs</span>
        <h1>Turn knowledge into repeatable skill</h1>
        <p>
          Plan the task, perform it, capture evidence, and honestly record how much
          help you needed.
        </p>
      </div>

      <div className="metric-grid compact lab-metrics">
        <Metric value={data.summary.planned} label="Planned" />
        <Metric value={data.summary.in_progress} label="In progress" accent />
        <Metric value={data.summary.completed} label="Completed" />
        <Metric value={data.summary.unaided} label="Unaided" />
      </div>

      <Panel eyebrow="Guided lab catalog" title={requestedObjective ? "Labs for this objective" : "Choose a proven practice plan"}>
        <div className="lab-catalog-toolbar">
          <p>
            Versioned procedures are mapped to the current A+ objective spine.
            Launching one freezes its steps and safety guidance into your practice record.
          </p>
          {!requestedObjective ? (
            <div className="duration-options lab-exam-filter" aria-label="Filter lab templates">
              {(["all", "220-1201", "220-1202"] as const).map((exam) => (
                <button
                  key={exam}
                  type="button"
                  className={examFilter === exam ? "selected" : ""}
                  onClick={() => setExamFilter(exam)}
                >
                  {exam === "all" ? "All" : exam === "220-1201" ? "Core 1" : "Core 2"}
                </button>
              ))}
            </div>
          ) : (
            <Link className="text-link" to="/labs">View all templates</Link>
          )}
        </div>
        {launchedTitle ? (
          <p className="notice success">Planned: {launchedTitle}. It is now in your lab queue.</p>
        ) : null}
        {catalogTemplates.length ? (
          <div className="lab-template-grid">
            {catalogTemplates.map((template) => (
              <article key={template.slug} className="lab-template-card">
                <span className="eyebrow">
                  {template.exam_code} · Objective {template.objective_code}
                </span>
                <h3>{template.title}</h3>
                <p>{template.summary}</p>
                <div className="template-meta">
                  <span>{template.difficulty}</span>
                  <span>{template.estimated_minutes} minutes</span>
                  <span>{template.history.completed} completed</span>
                </div>
                <details>
                  <summary>Preview procedure</summary>
                  <div className="template-preview">
                    <strong>Equipment</strong>
                    <ul>{template.equipment.map((item) => <li key={item}>{item}</li>)}</ul>
                    <strong>Safety</strong>
                    <ul>{template.safety_notes.map((item) => <li key={item}>{item}</li>)}</ul>
                    <strong>Procedure</strong>
                    <ol>{template.steps.map((item) => <li key={item}>{item}</li>)}</ol>
                    <strong>Success checks</strong>
                    <ul>{template.success_checks.map((item) => <li key={item}>{item}</li>)}</ul>
                  </div>
                </details>
                <button
                  className="button primary"
                  disabled={launchTemplate.isPending}
                  onClick={() => launchTemplate.mutate(template)}
                >
                  Plan this lab
                </button>
              </article>
            ))}
          </div>
        ) : (
          <p className="notice">No governed template is mapped to this objective yet. You can still create a custom lab below.</p>
        )}
        {launchTemplate.error ? <ErrorNotice error={launchTemplate.error} /> : null}
        <p className="fine-print">{catalog.policy} Catalog {catalog.catalog_version}.</p>
      </Panel>

      <details className="custom-lab-panel">
        <summary>Create a custom lab</summary>
        <section className="panel">
          <div className="panel-head">
            <div><span className="eyebrow">Custom plan</span><h2>Define your own practice</h2></div>
          </div>
        <div className="lab-plan-form">
          <label>
            Certification objective
            <select
              value={objectiveId}
              onChange={(event) => setSelectedObjective(Number(event.target.value))}
            >
              {objectives.map((objective) => (
                <option key={objective.id} value={objective.id}>{objective.label}</option>
              ))}
            </select>
          </label>
          <label>
            Lab title
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Replace and verify laptop memory"
              maxLength={200}
            />
          </label>
          <label>
            Goal and success condition
            <textarea
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              placeholder="What will you do, and what observable result proves it worked?"
              maxLength={10000}
            />
          </label>
          <label>
            Environment and resources
            <textarea
              value={environment}
              onChange={(event) => setEnvironment(event.target.value)}
              placeholder="Hardware, VM, operating system, tools, safety constraints, or source instructions."
              maxLength={10000}
            />
          </label>
          <button
            className="button primary"
            disabled={!objectiveId || !title.trim() || !goal.trim() || createLab.isPending}
            onClick={() => createLab.mutate({
              objective_id: objectiveId,
              title: title.trim(),
              goal_text: goal.trim(),
              environment_text: environment.trim() || undefined,
              client_key: `lab:${objectiveId}:${Date.now()}`,
            })}
          >
            Save lab plan
          </button>
        </div>
        {createLab.error ? <ErrorNotice error={createLab.error} /> : null}
        </section>
      </details>

      <Panel eyebrow="Lab queue" title={data.labs.length ? "Your practice record" : "No labs planned yet"}>
        {data.labs.length ? (
          <ol className="lab-list">
            {data.labs.map((lab) => (
              <li key={lab.id} className={`lab-card status-${lab.status}`}>
                <div className="lab-card-heading">
                  <div>
                    <span className="eyebrow">{lab.exam_code} · Objective {lab.objective_code}</span>
                    <h3>{lab.title}</h3>
                    <p>{lab.goal_text}</p>
                  </div>
                  <span className="status-pill">{lab.status.replace("_", " ")}</span>
                </div>
                {lab.environment_text ? (
                  <div className="lab-detail"><strong>Environment</strong><p>{lab.environment_text}</p></div>
                ) : null}
                {lab.template ? (
                  <details className="launched-template" open={lab.status === "in_progress"}>
                    <summary>Procedure and evidence checklist</summary>
                    <div className="template-preview">
                      <strong>Steps</strong>
                      <ol>{lab.template.steps.map((item) => <li key={item}>{item}</li>)}</ol>
                      <strong>Capture before completing</strong>
                      <ul>{lab.template.evidence_prompts.map((item) => <li key={item}>{item}</li>)}</ul>
                    </div>
                  </details>
                ) : null}
                {lab.status === "planned" ? (
                  <div className="action-row">
                    <button
                      className="button primary"
                      disabled={updateLab.isPending}
                      onClick={() => updateLab.mutate({id: lab.id, payload: {status: "in_progress"}})}
                    >
                      Start lab
                    </button>
                    <Link className="button secondary" to={`/learn/${lab.objective_id}`}>Open lesson</Link>
                  </div>
                ) : null}
                {lab.status === "in_progress" ? (
                  <ResultForm
                    lab={lab}
                    pending={updateLab.isPending}
                    onComplete={(payload) => updateLab.mutate({id: lab.id, payload})}
                  />
                ) : null}
                {lab.status === "completed" ? (
                  <div className="lab-completion">
                    <span className="completion-level">{levelLabels[lab.completion_level!]}</span>
                    <div className="lab-detail"><strong>Evidence</strong><p>{lab.evidence_text}</p></div>
                    <div className="lab-detail"><strong>Reflection</strong><p>{lab.reflection_text}</p></div>
                    <small>Completed {formatDate(lab.completed_at)}</small>
                  </div>
                ) : null}
                <button
                  className="text-button"
                  disabled={updateLab.isPending}
                  onClick={() => updateLab.mutate({id: lab.id, payload: {archived: true}})}
                >
                  Archive
                </button>
              </li>
            ))}
          </ol>
        ) : (
          <p className="notice">Choose an objective and create your first lab plan above.</p>
        )}
        {updateLab.error ? <ErrorNotice error={updateLab.error} /> : null}
        <p className="fine-print">{data.evidence_note}</p>
      </Panel>
    </>
  );
}
