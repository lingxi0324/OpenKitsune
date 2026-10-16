export interface RuntimeApplyResult {
  status: string;
  apply_mode?: string;
  refreshed?: string[];
  invalidated?: string[];
  warnings?: string[];
  failed?: Record<string, unknown>;
  restart_required?: boolean;
  [key: string]: unknown;
}

export interface RuntimeOperationResult {
  status?: string;
  operation_status?: string;
  connection_status?: string;
  runtime?: RuntimeApplyResult;
  ok?: boolean;
  error?: unknown;
  detail?: unknown;
  [key: string]: unknown;
}

export interface DecodedRuntimeOperation<T extends RuntimeOperationResult> {
  body: T;
  failure: string | null;
  notice: string | null;
}

interface RuntimeResponseLike {
  json(): Promise<unknown>;
}

interface DecodeRuntimeOperationOptions {
  allowEmpty?: boolean;
}

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === "object" ? value as Record<string, unknown> : null;

export const operationStatus = (value: unknown): string => {
  const body = asRecord(value);
  return typeof body?.operation_status === "string"
    ? body.operation_status
    : typeof body?.status === "string"
      ? body.status
      : "";
};

export const connectionStatus = (value: unknown): string => {
  const body = asRecord(value);
  if (typeof body?.connection_status === "string") return body.connection_status;
  // Compatibility with servers that predate the unified operation contract.
  if (body?.operation_status === "connected" || body?.operation_status === "disconnected") {
    return body.operation_status;
  }
  return typeof body?.status === "string" ? body.status : "";
};

export const runtimeNotice = (value: unknown): string | null => {
  const body = asRecord(value);
  const runtime = asRecord(body?.runtime);
  const failed = asRecord(runtime?.failed);
  const failures = failed
    ? Object.entries(failed).map(([name, reason]) => `${name}: ${String(reason)}`).join("; ")
    : "";
  const warnings = Array.isArray(runtime?.warnings)
    ? runtime.warnings.map(String).join("; ")
    : "";
  return failures || warnings || null;
};

export const responseFailure = (value: unknown, fallback = "Operation failed"): string | null => {
  const body = asRecord(value);
  if (body?.ok !== false && !body?.error) return null;
  const error = asRecord(body?.error);
  const detail = asRecord(body?.detail);
  if (typeof error?.message === "string") return error.message;
  if (typeof detail?.message === "string") return detail.message;
  if (typeof body?.error === "string") return body.error;
  if (typeof body?.detail === "string") return body.detail;
  return fallback;
};

export const decodeRuntimeOperationResponse = async <
  T extends RuntimeOperationResult = RuntimeOperationResult,
>(
  response: RuntimeResponseLike,
  fallback = "Operation failed",
  options: DecodeRuntimeOperationOptions = {},
): Promise<DecodedRuntimeOperation<T>> => {
  let raw: unknown;
  try {
    raw = await response.json();
  } catch (error) {
    if (!options.allowEmpty) throw new Error(fallback, { cause: error });
    raw = {};
  }

  const record = asRecord(raw);
  if (!record && !options.allowEmpty) throw new Error(fallback);
  const body = (record ?? {}) as T;
  return {
    body,
    failure: responseFailure(body, fallback),
    notice: runtimeNotice(body),
  };
};
