import { useSyncExternalStore } from "react";

// The operator token lives in sessionStorage only: it is gone when the tab closes. If storage is
// blocked (private windows) it falls back to memory for this page view.
const KEY = "opsbridge.operatorToken";
const listeners = new Set<() => void>();
let memory = "";

function read(): string {
  try {
    return window.sessionStorage.getItem(KEY) ?? memory;
  } catch {
    return memory;
  }
}

export function setOperatorToken(value: string) {
  memory = value;
  try {
    window.sessionStorage.setItem(KEY, value);
  } catch {
    // Not persisted; see above.
  }
  listeners.forEach((notify) => notify());
}

function subscribe(notify: () => void) {
  listeners.add(notify);
  return () => {
    listeners.delete(notify);
  };
}

// Server snapshot is empty, so the first client render matches the server render.
export function useOperatorToken(): string {
  return useSyncExternalStore(subscribe, read, () => "");
}
