import type { TicketStatus } from "@/lib/api";

// Color plus shape plus text label: color is never the only signal.
const STYLE: Record<TicketStatus, { color: string; shape: string; label: string }> = {
  AWAITING_APPROVAL: { color: "text-needs-you", shape: "bg-needs-you", label: "Awaiting approval" },
  EXECUTED: { color: "text-executed", shape: "bg-executed", label: "Executed" },
  FAILED: { color: "text-failed", shape: "", label: "Failed" },
  REJECTED: { color: "text-rejected", shape: "", label: "Rejected" },
  PENDING: { color: "text-pending", shape: "border-[1.5px] border-pending", label: "Pending" },
};

function Shape({ status }: { status: TicketStatus }) {
  const s = STYLE[status];
  if (status === "FAILED") {
    return (
      <svg width="9" height="9" viewBox="0 0 9 9" aria-hidden="true">
        <path d="M0.5 0.5L8.5 8.5M8.5 0.5L0.5 8.5" stroke="currentColor" strokeWidth="2" />
      </svg>
    );
  }
  if (status === "REJECTED") {
    return (
      <svg width="9" height="9" viewBox="0 0 9 9" aria-hidden="true">
        <rect x="0.5" y="0.5" width="8" height="8" fill="none" stroke="currentColor" />
        <path d="M0.5 8.5L8.5 0.5" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    );
  }
  return <span aria-hidden="true" className={`inline-block h-[9px] w-[9px] ${s.shape}`} />;
}

export function StatusBadge({ status }: { status: TicketStatus }) {
  const s = STYLE[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 font-stamp text-xs font-bold uppercase tracking-[0.08em] ${s.color}`}
    >
      <Shape status={status} />
      {s.label}
    </span>
  );
}
