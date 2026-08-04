export const API_BASE = import.meta.env.VITE_API_URL ?? "/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
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
    throw new ApiError(body?.error?.message ?? body?.detail ?? "Falha ao comunicar com o servidor", response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function download(path: string, filename: string): Promise<void> {
  const token = localStorage.getItem("thermopower.token");
  const response = await fetch(`${API_BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new ApiError("Não foi possível gerar o arquivo", response.status);
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
      payload?.error?.message ?? payload?.detail ?? "Não foi possível gerar o arquivo",
      response.status,
    );
  }
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function formatDate(value?: string | null): string {
  return value ? new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "medium" }).format(new Date(value)) : "—";
}

export function formatDuration(seconds?: number | null): string {
  if (seconds == null) return "—";
  const total = Math.max(0, Math.floor(seconds));
  return [Math.floor(total / 3600), Math.floor((total % 3600) / 60), total % 60].map((part) => String(part).padStart(2, "0")).join(":");
}
