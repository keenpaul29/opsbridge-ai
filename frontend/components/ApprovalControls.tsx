"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export function ApprovalControls({
  ticketId,
  initialPayload,
}: {
  ticketId: string;
  initialPayload: Record<string, unknown>;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(JSON.stringify(initialPayload, null, 2));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  function approve() {
    let edited: Record<string, unknown> | undefined;
    if (editing) {
      try {
        edited = JSON.parse(draft);
      } catch {
        setError("Edited payload is not valid JSON");
        return;
      }
    }
    void run(() => api.approve(ticketId, edited));
  }

  function reject() {
    const reason = window.prompt("Reason for rejecting?");
    if (reason === null) return;
    void run(() => api.reject(ticketId, reason));
  }

  // Keyboard shortcuts: A approve, E edit, R reject (ignored while typing).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = e.target as HTMLElement;
      if (el.tagName === "TEXTAREA" || el.tagName === "INPUT" || busy) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "a") approve();
      else if (e.key === "e") setEditing((v) => !v);
      else if (e.key === "r") reject();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <section className="space-y-3 border-t border-ink px-4 py-3.5">
      {editing && (
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="num h-40 w-full border border-ink bg-ground p-2 text-xs"
          aria-label="Edit tool payload"
        />
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={approve} disabled={busy} className="key key-primary">
          Approve &amp; execute
        </button>
        <button onClick={() => setEditing((v) => !v)} disabled={busy} className="key">
          {editing ? "Cancel edit" : "Edit payload"}
        </button>
        <button onClick={reject} disabled={busy} className="key">
          Reject
        </button>
        <span className="num ml-auto text-xs text-muted">A approve · E edit · R reject</span>
      </div>
      {error && (
        <p role="alert" className="text-failed">
          <b>Error.</b> {error}
        </p>
      )}
    </section>
  );
}
