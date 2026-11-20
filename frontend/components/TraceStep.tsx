import type { Trace } from "@/lib/api";

// One row of the trace tape: step number in the left gutter, latency in the right gutter, and
// citations as footnotes that expand inline to the policy text and similarity score.
type Citation = { doc_name?: string; text?: string; score?: number };

function asNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

// What the retrieval guardrails did, from the output the runner already stores on the
// `retrieve_policy` step. Each note carries a word as well as a mark, never colour alone.
function retrievalNotes(output: Trace["output_data"]): { text: string; failed?: boolean }[] {
  if (!output) return [];
  const notes: { text: string; failed?: boolean }[] = [];
  const hits = asNumber(output.hits);
  if (hits !== null) notes.push({ text: `${hits} ${hits === 1 ? "policy" : "policies"} kept` });
  const dropped = asNumber(output.dropped_below_floor);
  if (dropped !== null && dropped > 0) {
    notes.push({ text: `${dropped} dropped below the similarity floor` });
  }
  if (typeof output.retrieval_error === "string" && output.retrieval_error) {
    notes.push({ text: `retrieval failed (${output.retrieval_error}), no policy used`, failed: true });
  }
  return notes;
}

export function TraceStep({ index, trace }: { index: number; trace: Trace }) {
  const citations = (trace.citations ?? []) as Citation[];
  const notes = trace.step_name === "retrieve_policy" ? retrievalNotes(trace.output_data) : [];

  return (
    <li className="grid grid-cols-[44px_1fr_80px] border-b border-rule last:border-b-0">
      <span className="num border-r border-rule pl-3 pt-2.5 text-xs text-muted">
        {String(index + 1).padStart(2, "0")}
      </span>
      <details className="px-4 py-2.5">
        <summary className="cursor-pointer">
          <span className="font-semibold">{trace.step_name}</span>
          {notes.map((n) => (
            <span
              key={n.text}
              className={`ml-3 text-xs ${n.failed ? "font-semibold text-failed" : "text-muted"}`}
            >
              {n.failed ? "✕ " : "· "}
              {n.text}
            </span>
          ))}
        </summary>

        {citations.length > 0 && (
          <ol className="mt-2 space-y-1 text-[13px]">
            {citations.map((c, n) => (
              <li key={n} className="bg-rule/35">
                <details>
                  <summary className="cursor-pointer px-2.5 py-1.5">
                    <sup className="num font-semibold">{n + 1}</sup>{" "}
                    <span className="font-semibold">{c.doc_name ?? "unknown document"}</span>{" "}
                    <span className="num text-muted">
                      score {typeof c.score === "number" ? c.score.toFixed(2) : "—"}
                    </span>
                  </summary>
                  <p className="border-t border-rule px-2.5 py-2">{c.text ?? "(no text stored)"}</p>
                </details>
              </li>
            ))}
          </ol>
        )}

        <details className="mt-2">
          <summary className="cursor-pointer text-xs text-muted">Raw input and output</summary>
          <pre className="num mt-1 overflow-x-auto bg-ground p-2 text-xs">
            {JSON.stringify({ input: trace.input_data, output: trace.output_data }, null, 2)}
          </pre>
        </details>
      </details>
      <span className="num pr-3 pt-2.5 text-right text-xs text-muted">{trace.latency_ms} ms</span>
    </li>
  );
}
