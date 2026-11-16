import Link from "next/link";
import { StatusBadge } from "@/components/StatusBadge";
import { api, TICKET_STATUSES, type TicketStatus } from "@/lib/api";

const STATUS_LABEL = (s: string) => s.replace("_", " ");

export default async function TriageQueue({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const { status } = await searchParams;
  const filter = TICKET_STATUSES.find((s) => s === status);

  let tickets;
  try {
    tickets = await api.listTickets(filter);
  } catch {
    return (
      <div className="border border-failed bg-surface px-3 py-2">
        <b className="text-failed">Error.</b> Could not reach the backend API. Reload to retry.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h1 className="font-stamp text-[28px] font-bold uppercase leading-none tracking-wide">
        Triage queue
      </h1>
      <div className="flex flex-wrap gap-2">
        <FilterLink label="All" href="/" active={!filter} />
        {TICKET_STATUSES.map((s) => (
          <FilterLink
            key={s}
            label={STATUS_LABEL(s)}
            href={`/?status=${s}`}
            active={filter === s}
          />
        ))}
      </div>
      {tickets.length === 0 ? (
        <p className="border border-rule bg-surface px-3 py-6 text-muted">
          No tickets{filter ? ` with status ${STATUS_LABEL(filter)}` : ""}. New GitHub issue events
          appear here once the webhook fires.
        </p>
      ) : (
        <div className="border border-ink bg-surface">
          <div className="grid grid-cols-[170px_1fr_90px_70px] gap-3 border-b border-ink px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
            <span>Status</span>
            <span>Event</span>
            <span>Source</span>
            <span className="text-right">Conf</span>
          </div>
          {tickets.map((t) => {
            const attention = t.status === "AWAITING_APPROVAL";
            return (
              <Link
                key={t.id}
                href={`/tickets/${t.id}`}
                className={`grid h-8 grid-cols-[170px_1fr_90px_70px] items-center gap-3 border-b border-rule px-3 last:border-b-0 hover:bg-ground ${
                  attention ? "bg-needs-you/15" : ""
                }`}
              >
                <StatusBadge status={t.status as TicketStatus} />
                <span className="num truncate">{t.external_event_id}</span>
                <span className="num text-muted">{t.provider}</span>
                <span className="text-right">
                  {t.confidence_score != null ? (
                    <span className="conf-wrap">
                      <span
                        className="conf num"
                        style={{ "--w": `${t.confidence_score * 100}%` } as React.CSSProperties}
                      >
                        {t.confidence_score.toFixed(2)}
                      </span>
                    </span>
                  ) : (
                    <span className="num text-muted">—</span>
                  )}
                </span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

function FilterLink({ label, href, active }: { label: string; href: string; active: boolean }) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`border border-ink px-3 py-1 text-xs font-semibold uppercase tracking-wider ${
        active ? "bg-ink text-on-ink" : "bg-surface hover:bg-ground"
      }`}
    >
      {label}
    </Link>
  );
}
