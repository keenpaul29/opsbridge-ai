import type { components } from "./api-types";

// Types are generated from the FastAPI OpenAPI schema: `npm run gen:types`.
export type Ticket = components["schemas"]["TicketOut"];
export type TicketDetail = components["schemas"]["TicketDetail"];
export type Trace = components["schemas"]["TraceOut"];
export type EvalRun = components["schemas"]["EvalRunOut"];
export type TicketStatus = components["schemas"]["TicketStatus"];

export const TICKET_STATUSES: TicketStatus[] = [
  "PENDING",
  "AWAITING_APPROVAL",
  "EXECUTED",
  "FAILED",
  "REJECTED",
];

// Server components talk to the API directly; the browser uses the public URL.
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store", ...init });
  if (!res.ok) {
    const detail = await res.json().then((b) => b.detail as string).catch(() => res.statusText);
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

// State-changing calls carry the operator token; reads stay public.
function writeHeaders(token: string): Record<string, string> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (token) headers.authorization = `Bearer ${token}`;
  return headers;
}

export const api = {
  listTickets: (status?: TicketStatus) =>
    request<Ticket[]>(`/tickets${status ? `?status=${status}` : ""}`),
  getTicket: (id: string) => request<TicketDetail>(`/tickets/${id}`),
  getTraces: (id: string) => request<Trace[]>(`/tickets/${id}/traces`),
  approve: (id: string, token: string, editedPayload?: Record<string, unknown>) =>
    request<Ticket>(`/tickets/${id}/approve`, {
      method: "POST",
      headers: writeHeaders(token),
      body: JSON.stringify({ edited_payload: editedPayload ?? null }),
    }),
  reject: (id: string, token: string, reason: string) =>
    request<Ticket>(`/tickets/${id}/reject`, {
      method: "POST",
      headers: writeHeaders(token),
      body: JSON.stringify({ reason }),
    }),
  latestEval: () => request<EvalRun>("/evals/latest"),
};
