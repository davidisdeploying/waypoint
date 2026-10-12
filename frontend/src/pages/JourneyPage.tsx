import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {getWaypointState, queries, saveWaypointState, studyGet} from "../api";
import {ErrorNotice, Loading} from "../components";
import {JourneyContent} from "../JourneyContent";
import type {CredentialStatus, WaypointStateEnvelope} from "../types";

const statusOptions: Array<{value: CredentialStatus; label: string}> = [
  {value: "todo", label: "Not started"},
  {value: "studying", label: "Studying"},
  {value: "scheduled", label: "Exam booked"},
  {value: "passed", label: "Passed"},
];

export function JourneyPage() {
  const queryClient = useQueryClient();
  const stateQuery = useQuery({queryKey: ["waypoint-state"], queryFn: getWaypointState});
  const timelineQuery = useQuery({queryKey: ["timeline"], queryFn: queries.timeline});
  const saveMutation = useMutation({
    mutationFn: async ({envelope, certId, status}: {
      envelope: WaypointStateEnvelope;
      certId: string;
      status: CredentialStatus;
    }) => {
      const state = structuredClone(envelope.state);
      const credential = state.certs.find((item) => item.id === certId);
      if (!credential) throw new Error("Credential not found.");
      credential.status = status;
      if (status === "studying" && !credential.started) {
        credential.started = new Date().toISOString().slice(0, 10);
      }
      if (status === "passed" && !credential.pass) {
        credential.pass = new Date().toISOString().slice(0, 10);
        if (credential.started && credential.actualHours == null) {
          const {hours} = await studyGet<{hours: number}>(
            `hours-since?since=${encodeURIComponent(credential.started)}`,
          );
          credential.actualHours = hours;
        }
      }
      return saveWaypointState(state, envelope.revision);
    },
    onSuccess: (data) => queryClient.setQueryData(["waypoint-state"], data),
  });

  if (stateQuery.isLoading || timelineQuery.isLoading) return <Loading label="Mapping your journey" />;
  const error = stateQuery.error || timelineQuery.error;
  if (error) return <ErrorNotice error={error} />;
  if (!stateQuery.data) return <ErrorNotice error={new Error("Waypoint milestone state has not been initialized.")} />;

  const envelope = stateQuery.data;
  const timeline = timelineQuery.data!;

  return (
    <>
      <JourneyContent
        envelope={envelope}
        timeline={timeline}
        showTimelineLink
        renderStatus={(credential) => (
          <label className="credential-status">
            Status
            <select
              value={credential.status}
              disabled={saveMutation.isPending}
              onChange={(event) => saveMutation.mutate({
                envelope,
                certId: credential.id,
                status: event.target.value as CredentialStatus,
              })}
            >
              {statusOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
        )}
      />
      {saveMutation.error ? <ErrorNotice error={saveMutation.error} /> : null}
    </>
  );
}
