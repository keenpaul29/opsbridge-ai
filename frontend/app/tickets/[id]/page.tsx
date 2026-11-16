import { notFound } from "next/navigation";
import { ApprovalControls } from "@/components/ApprovalControls";
import { StatusBadge } from "@/components/StatusBadge";
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
              <li
                key={t.id}
                className="grid grid-cols-[44px_1fr_80px] border-b border-rule last:border-b-0"
              >
                <span className="num border-r border-rule pl-3 pt-2.5 text-xs text-muted">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <details className="px-4 py-2.5">
                  <summary className="cursor-pointer font-semibold">{t.step_name}</summary>
                  {t.citations && t.citations.length > 0 && (
                    <ul className="mt-2 space-y-1 text-[13px]">
                      {t.citations.map((c, n) => (
                        <li key={n} className="bg-rule/35 px-2.5 py-1.5">
                          <sup className="num font-semibold text-needs-you">{n + 1}</sup>{" "}
                          {JSON.stringify(c)}
                        </li>
                      ))}
                    </ul>
                  )}
                  <pre className="num mt-2 overflow-x-auto bg-ground p-2 text-xs">
                    {JSON.stringify({ input: t.input_data, output: t.output_data }, null, 2)}
                  </pre>
                </details>
                <span className="num pr-3 pt-2.5 text-right text-xs text-muted">
                  {t.latency_ms} ms
                </span>
              </li>
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
