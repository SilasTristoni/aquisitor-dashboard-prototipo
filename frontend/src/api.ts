export const API_BASE = import.meta.env.VITE_API_URL ?? "/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public correlationId?: string,
  ) {
    super(correlationId ? `${message}\nCódigo: ${correlationId}` : message);
  }
}

export function friendlyApiMessage(message?: unknown): string {
  if (!message) return "Falha ao comunicar com o servidor";
  if (typeof message !== "string") {
    if (typeof message === "object" && message && "message" in message && typeof message.message === "string") return message.message;
    return "Não foi possível concluir a operação. Confira os dados e tente novamente.";
  }
  const messages: Record<string, string> = {
    protocol_timeout: "O equipamento não respondeu dentro do tempo esperado.",
    timeout: "O equipamento não respondeu dentro do tempo esperado.",
    port_busy: "A porta está sendo usada por outro programa.",
    device_not_found: "O equipamento não foi encontrado.",
  };
  return messages[message.trim().toLocaleLowerCase("pt-BR")] ?? message;
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem("thermopower.token");
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...(options.body && !isFormData ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      friendlyApiMessage(body?.error?.message ?? body?.detail),
      response.status,
      body?.error?.correlation_id ?? response.headers?.get("X-Correlation-ID") ?? undefined,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function download(path: string, filename: string): Promise<void> {
  const token = localStorage.getItem("thermopower.token");
  const response = await fetch(`${API_BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(payload?.error?.message ?? "Não foi possível gerar o arquivo", response.status,
      payload?.error?.correlation_id ?? response.headers?.get("X-Correlation-ID") ?? undefined);
  }
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function downloadWithBody(
  path: string,
  filename: string,
  body: unknown,
): Promise<void> {
  const token = localStorage.getItem("thermopower.token");
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(
      friendlyApiMessage(
        payload?.error?.message ?? payload?.detail ?? "Não foi possível gerar o arquivo",
      ),
      response.status,
      payload?.error?.correlation_id ?? response.headers?.get("X-Correlation-ID") ?? undefined,
    );
  }
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function parseApiDate(value: string): Date {
  const includesTimeZone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value);
  return new Date(includesTimeZone ? value : `${value}Z`);
}

export function formatDate(value?: string | null): string {
  return value ? new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "medium",
    timeZone: "America/Sao_Paulo",
  }).format(parseApiDate(value)) : "—";
}

export function formatDuration(seconds?: number | null): string {
  if (seconds == null) return "—";
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainingSeconds = total % 60;
  if (hours) {
    return [
      `${hours} h`,
      minutes ? `${minutes} min` : "",
      remainingSeconds && !minutes ? `${remainingSeconds} s` : "",
    ].filter(Boolean).join(" ");
  }
  if (minutes) return `${minutes} min${remainingSeconds ? ` ${remainingSeconds} s` : ""}`;
  return `${remainingSeconds} s`;
}
