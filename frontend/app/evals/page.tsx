import { api, ApiError } from "@/lib/api";

const Title = () => (
  <h1 className="font-stamp text-[28px] font-bold uppercase leading-none tracking-wide">
    Eval dashboard
  </h1>
);

export default async function EvalDashboard() {
  let run;
  try {
    run = await api.latestEval();
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      return (
        <div className="space-y-4">
          <Title />
          <p className="border border-rule bg-surface px-3 py-6 text-muted">
            No eval runs recorded yet. Run the eval suite in CI to populate this table.
          </p>
        </div>
      );
    }
    return (
      <div className="space-y-4">
        <Title />
        <div className="border border-failed bg-surface px-3 py-2">
          <b className="text-failed">Error.</b> Could not load the latest eval run.
        </div>
      </div>
    );
  }

  const rows: [string, string][] = [
    ["Pass rate", `${(run.pass_rate * 100).toFixed(1)} %`],
    ["Tool-selection accuracy", `${(run.tool_accuracy * 100).toFixed(1)} %`],
    ["Groundedness", `${(run.groundedness_score * 100).toFixed(1)} %`],
    ["P95 latency", `${run.p95_latency_ms.toLocaleString("en-US")} ms`],
  ];

  return (
    <div className="space-y-4">
      <Title />
      <p className="text-[13px] text-muted">
        {run.total_cases} cases · commit <span className="num">{run.git_sha.slice(0, 7)}</span> ·{" "}
        {new Date(run.created_at).toLocaleString()}
      </p>
      <dl className="max-w-md border border-ink bg-surface">
        {rows.map(([label, value]) => (
          <div
            key={label}
            className="flex h-8 items-center justify-between border-b border-rule px-3 last:border-b-0"
          >
            <dt>{label}</dt>
            <dd className="num">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
