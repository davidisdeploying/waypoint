import {useMemo, useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {queries} from "../api";
import {ErrorNotice, Loading, Panel} from "../components";
import type {LearningProposalEnvelope} from "../types";

function decodeProposal(): LearningProposalEnvelope | null {
  const encoded = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("proposal");
  if (!encoded) return null;
  try {
    const base64 = encoded.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = decodeURIComponent(Array.from(atob(base64), (char) => `%${char.charCodeAt(0).toString(16).padStart(2, "0")}`).join(""));
    const value = JSON.parse(decoded) as LearningProposalEnvelope;
    if (value.schema_version !== 1 || value.source !== "prospect_job_listing_audit" || !Array.isArray(value.proposals)) return null;
    return value;
  } catch { return null; }
}

export function LearningRequestsPage() {
  const queryClient = useQueryClient();
  const [imported, setImported] = useState(false);
  const incoming = useMemo(decodeProposal, []);
  const requests = useQuery({queryKey: ["learning-requests"], queryFn: queries.learningRequests});
  const importer = useMutation({
    mutationFn: queries.importLearningRequests,
    onSuccess: () => {
      setImported(true);
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
      void queryClient.invalidateQueries({queryKey: ["learning-requests"]});
    },
  });

  if (requests.isLoading) return <Loading label="Loading learning requests" />;
  if (requests.error) return <ErrorNotice error={requests.error} />;

  return (
    <>
      <div className="page-title">
        <span className="eyebrow">Career bridge</span>
        <h1>Learning requests</h1>
        <p>Potential skills and technologies from Prospect job audits. These are proposals—not study evidence, mastery, or credential progress.</p>
      </div>

      {incoming && !imported ? (
        <Panel eyebrow="Confirmation required" title={`Import proposals for ${incoming.role || "this listing"}?`}>
          <p>{incoming.company ? `${incoming.company} · ` : ""}Prospect audit #{incoming.source_audit_id}</p>
          <ul>
            {incoming.proposals.map((proposal) => (
              <li key={proposal.technology}>
                <strong>{proposal.technology}</strong> — {proposal.evidence_building_method}
                {proposal.certification_label ? ` (${proposal.certification_label}; ${proposal.waypoint_scope_status.replace(/_/g, " ")})` : ""}
              </li>
            ))}
          </ul>
          <p className="notice">Importing creates planning-only requests. It does not create lessons, mark objectives complete, award mastery, or change certification status.</p>
          <div className="action-row">
            <button className="button primary" type="button" disabled={importer.isPending} onClick={() => importer.mutate(incoming)}>
              {importer.isPending ? "Importing..." : "Import as proposed learning"}
            </button>
            <button className="button secondary" type="button" onClick={() => window.history.replaceState(null, "", window.location.pathname)}>Discard handoff</button>
          </div>
          {importer.error ? <ErrorNotice error={importer.error} /> : null}
        </Panel>
      ) : null}

      <Panel eyebrow="Proposal ledger" title="Saved requests">
        {requests.data!.learning_requests.length ? (
          <ol className="session-history-list">
            {requests.data!.learning_requests.map((request) => (
              <li key={request.id}>
                <div className="session-history-summary">
                  <strong>{request.technology}</strong>
                  <span>{request.role || "Job listing"}{request.company ? ` · ${request.company}` : ""}</span>
                  <span>{request.rationale}</span>
                  <small>{request.priority} priority · {request.waypoint_scope_status.replace(/_/g, " ")} · proposed</small>
                </div>
              </li>
            ))}
          </ol>
        ) : <p className="notice">No learning requests have been imported.</p>}
        <p className="fine-print">Boundary: {requests.data!.evidence_boundary.replace(/_/g, " ")}.</p>
      </Panel>
    </>
  );
}
