export type SessionRestoreEvent =
  | { type: "attempt"; attempt: number }
  | { type: "not_ready"; attempt: number; delayMs: number }
  | { type: "request_error"; attempt: number; delayMs: number; error: unknown }
  | {
    type: "reconcile_error";
    attempt: number;
    retry: boolean;
    delayMs?: number;
    error: unknown;
  }
  | { type: "restored"; attempt: number }
  | { type: "cancelled"; attempt: number };

export type SessionRestoreResult =
  | { status: "restored" | "cancelled"; attempts: number }
  | { status: "failed"; attempts: number; error: unknown };

export function sessionRestoreRetryDelay(attempt: number): number {
  return Math.min(1000 * Math.pow(1.5, Math.max(0, attempt - 1)), 5000);
}

function waitForRetry(delayMs: number, signal: AbortSignal): Promise<boolean> {
  if (signal.aborted) return Promise.resolve(false);

  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve(true);
    }, delayMs);
    const onAbort = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", onAbort);
      resolve(false);
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export async function restoreSessionsUntilReady<T>(options: {
  signal: AbortSignal;
  request: (attempt: number) => Promise<T>;
  isReady: (payload: T) => boolean;
  reconcile: (payload: T) => void | Promise<void>;
  onEvent?: (event: SessionRestoreEvent) => void;
  retryDelay?: (attempt: number) => number;
  wait?: (delayMs: number, signal: AbortSignal) => Promise<boolean>;
  shouldRetryReconcileError?: (error: unknown) => boolean;
}): Promise<SessionRestoreResult> {
  const retryDelay = options.retryDelay ?? sessionRestoreRetryDelay;
  const wait = options.wait ?? waitForRetry;
  let attempt = 0;

  while (!options.signal.aborted) {
    attempt += 1;
    options.onEvent?.({ type: "attempt", attempt });

    let payload: T;
    try {
      payload = await options.request(attempt);
    } catch (error) {
      if (options.signal.aborted) break;
      const delayMs = retryDelay(attempt);
      options.onEvent?.({ type: "request_error", attempt, delayMs, error });
      if (!(await wait(delayMs, options.signal))) break;
      continue;
    }
    if (options.signal.aborted) break;

    if (options.isReady(payload)) {
      try {
        await options.reconcile(payload);
      } catch (error) {
        if (options.signal.aborted) break;
        const retry = options.shouldRetryReconcileError?.(error) ?? true;
        const delayMs = retry ? retryDelay(attempt) : undefined;
        options.onEvent?.({ type: "reconcile_error", attempt, retry, delayMs, error });
        if (!retry) return { status: "failed", attempts: attempt, error };
        if (!(await wait(delayMs!, options.signal))) break;
        continue;
      }
      if (options.signal.aborted) break;
      options.onEvent?.({ type: "restored", attempt });
      return { status: "restored", attempts: attempt };
    }

    const delayMs = retryDelay(attempt);
    options.onEvent?.({ type: "not_ready", attempt, delayMs });
    if (!(await wait(delayMs, options.signal))) break;
  }

  options.onEvent?.({ type: "cancelled", attempt });
  return { status: "cancelled", attempts: attempt };
}
