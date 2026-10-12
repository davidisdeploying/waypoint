import {useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {Link, useParams} from "react-router-dom";
import {queries, trackStudyEvent} from "../api";
import {ErrorNotice, Loading, Panel} from "../components";
import type {RetentionRating} from "../types";

const ratings: Array<{
  value: RetentionRating;
  label: string;
  detail: string;
}> = [
  {value: "again", label: "Again", detail: "I could not recall it. Review tomorrow."},
  {value: "hard", label: "Hard", detail: "I recalled part of it with effort."},
  {value: "good", label: "Good", detail: "I recalled the important ideas correctly."},
  {value: "easy", label: "Easy", detail: "The answer was immediate and complete."},
];

export function RetentionPage() {
  const objectiveId = Number(useParams().objectiveId);
  const queryClient = useQueryClient();
  const [readyToRate, setReadyToRate] = useState(false);
  const objective = useQuery({
    queryKey: ["objective", objectiveId],
    queryFn: () => queries.objective(objectiveId),
    enabled: Number.isInteger(objectiveId) && objectiveId > 0,
  });
  const review = useMutation({
    mutationFn: (rating: RetentionRating) =>
      queries.recordRetentionReview(
        objectiveId,
        rating,
        `retention:${objectiveId}:${Date.now()}`,
      ),
    onSuccess: (_state, rating) => {
      trackStudyEvent(
        "task_completed",
        `Memory review: ${objective.data?.exam_code ?? ""} ${objective.data?.code ?? ""}`.trim(),
        `retention:${objectiveId}:${rating}:${Date.now()}`,
        {objective_id: objectiveId, retention_rating: rating},
      );
      void queryClient.invalidateQueries({queryKey: ["study-next"]});
      void queryClient.invalidateQueries({queryKey: ["adaptive-plan"]});
      void queryClient.invalidateQueries({queryKey: ["retention"]});
      void queryClient.invalidateQueries({queryKey: ["objective", objectiveId]});
    },
  });

  if (!Number.isInteger(objectiveId) || objectiveId < 1) {
    return <ErrorNotice error={new Error("Invalid objective")} />;
  }
  if (objective.isLoading) return <Loading label="Preparing your memory review" />;
  if (objective.error) return <ErrorNotice error={objective.error} />;
  const detail = objective.data!;

  if (review.data) {
    const nextDate = new Date(review.data.due_at).toLocaleDateString("en-US", {
      weekday: "long",
      month: "short",
      day: "numeric",
    });
    return (
      <>
        <div className="page-title">
          <span className="eyebrow">Memory review complete</span>
          <h1>Objective {detail.code} is scheduled again</h1>
          <p>Next review: {nextDate}, after {review.data.interval_days} day{review.data.interval_days === 1 ? "" : "s"}.</p>
        </div>
        <Panel eyebrow="Evidence boundary" title="Recall recorded, mastery unchanged">
          <p>{review.data.evidence_note}</p>
          <div className="action-row">
            <Link className="button primary" to="/">Return to Today</Link>
            <Link className="button secondary" to={`/learn/${objectiveId}`}>Open full lesson</Link>
          </div>
        </Panel>
      </>
    );
  }

  return (
    <>
      <div className="page-title">
        <span className="eyebrow">{detail.exam_code} · Objective {detail.code}</span>
        <h1>Recall before you look</h1>
        <p>{detail.description}</p>
      </div>

      <Panel eyebrow="Active recall" title="Explain this objective from memory">
        <ol className="retention-prompts">
          <li>State the important components, steps, or distinctions.</li>
          <li>Describe one realistic scenario where you would apply them.</li>
          <li>Name anything you are uncertain about before checking the lesson.</li>
        </ol>
        <div className="action-row">
          <button className="button primary" onClick={() => setReadyToRate(true)}>
            I finished recalling
          </button>
          <Link className="button secondary" to={`/learn/${objectiveId}`}>
            I need the lesson
          </Link>
        </div>
      </Panel>

      {readyToRate ? (
        <Panel eyebrow="Self-rating" title="How well did you recall it?">
          <div className="retention-ratings">
            {ratings.map((rating) => (
              <button
                key={rating.value}
                type="button"
                disabled={review.isPending}
                onClick={() => review.mutate(rating.value)}
              >
                <strong>{rating.label}</strong>
                <span>{rating.detail}</span>
              </button>
            ))}
          </div>
          {review.error ? <ErrorNotice error={review.error} /> : null}
          <p className="fine-print">
            Be honest rather than optimistic. This controls only the next memory-review date.
          </p>
        </Panel>
      ) : null}
    </>
  );
}
