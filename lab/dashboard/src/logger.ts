type LogMethod = "debug" | "info" | "warn" | "error";

const PREFIX = "[komodobots]";

function normalizeError(error: unknown): unknown {
  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message,
      stack: error.stack,
    };
  }
  return error;
}

function emit(method: LogMethod, message: string, detail?: unknown): void {
  const logger = (console[method] ?? console.log).bind(console);
  if (detail === undefined) {
    logger(`${PREFIX} ${message}`);
    return;
  }
  logger(`${PREFIX} ${message}`, normalizeError(detail));
}

export function logDebug(message: string, detail?: unknown): void {
  emit("debug", message, detail);
}

export function logInfo(message: string, detail?: unknown): void {
  emit("info", message, detail);
}

export function logWarn(message: string, detail?: unknown): void {
  emit("warn", message, detail);
}

export function logError(message: string, error?: unknown, detail?: unknown): void {
  emit("error", message, {
    error: normalizeError(error),
    detail,
  });
}
