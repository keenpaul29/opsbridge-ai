import { notFound } from "next/navigation";
import { ApprovalControls } from "@/components/ApprovalControls";
import { StatusBadge } from "@/components/StatusBadge";
import { TraceStep } from "@/components/TraceStep";
import { api, ApiError, type TicketStatus } from "@/lib/api";

type Action = {
  recommended_action?: string;
  tool_payload?: Record<string, unknown>;
  reasoning?: string;
};

export default async function TicketPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let ticket, traces;
  try {
    [ticket, traces] = await Promise.all([api.getTicket(id), api.getTraces(id)]);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }

  const action = ticket.recommended_action as Action | null;
  const awaiting = ticket.status === "AWAITING_APPROVAL";

  return (
    <div className="space-y-6">
      <h1 className="font-stamp text-[28px] font-bold uppercase leading-none tracking-wide">
        Trace inspector
      </h1>

      <div className="border border-ink bg-surface">
        <div className="flex items-center justify-between gap-4 border-b border-ink px-4 py-3">
          <div className="min-w-0">
            <p className="num truncate font-bold">{ticket.external_event_id}</p>
            <p className="text-[13px] text-muted">
              {action
                ? `${action.recommended_action} · ${action.reasoning ?? ""}`
                : "No recommendation yet"}
            </p>
          </div>
          <StatusBadge status={ticket.status as TicketStatus} />
        </div>

        {traces.length === 0 ? (
          <p className="px-4 py-6 text-muted">No trace steps recorded yet.</p>
        ) : (
          <ol>
            {traces.map((t, i) => (
              <TraceStep key={t.id} index={i} trace={t} />
            ))}
          </ol>
        )}

        {awaiting && (
          <ApprovalControls ticketId={ticket.id} initialPayload={action?.tool_payload ?? {}} />
        )}
      </div>

      <details>
        <summary className="cursor-pointer text-[13px] text-muted">Raw webhook payload</summary>
        <pre className="num mt-2 overflow-x-auto border border-rule bg-surface p-3 text-xs">
          {JSON.stringify(ticket.raw_payload, null, 2)}
        </pre>
      </details>
    </div>
  );
}
