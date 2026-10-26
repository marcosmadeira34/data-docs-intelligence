// Cliente HTTP da API (mesma origem via proxy do Next). Autenticação por cookie httpOnly + CSRF double-submit.

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;
  requestId?: string;

  constructor(status: number, code: string, message: string, details?: unknown, requestId?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

const BASE = "/api/v1";

function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.split("; ").find((c) => c.startsWith("ddi_csrf="));
  return match ? decodeURIComponent(match.split("=")[1]) : "";
}

async function parseError(res: Response): Promise<ApiError> {
  let body: any = null;
  try {
    body = await res.json();
  } catch {
    /* corpo não-JSON */
  }
  const err = body?.error;
  const fallback = res.status >= 500 ? "Erro interno do servidor." : `Falha na requisição (${res.status}).`;
  return new ApiError(res.status, err?.code ?? "http_error", err?.message ?? fallback, err?.details, err?.request_id);
}

type Query = Record<string, string | number | boolean | null | undefined>;

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  Object.entries(query).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  });
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

export async function api<T = any>(
  path: string,
  opts: { method?: string; body?: unknown; query?: Query; headers?: Record<string, string> } = {},
): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json", ...(opts.headers ?? {}) };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken();
  const res = await fetch(withQuery(`${BASE}${path}`, opts.query), {
    method,
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    credentials: "same-origin",
  });
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
    window.dispatchEvent(new CustomEvent("ddi:unauthorized"));
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Upload multipart com progresso real (XMLHttpRequest expõe eventos de envio). */
export function uploadFile(clientId: string, file: File, onProgress: (pct: number) => void): Promise<any> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("client_id", clientId);
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/files`);
    xhr.setRequestHeader("X-CSRF-Token", csrfToken());
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => {
      let body: any = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else {
        const err = body?.error;
        reject(new ApiError(xhr.status, err?.code ?? "http_error", err?.message ?? `Falha no envio (${xhr.status}).`, err?.details, err?.request_id));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "network_error", "Falha de rede durante o envio."));
    xhr.send(form);
  });
}

/** Download autenticado: o navegador envia o cookie de sessão para a mesma origem. */
export function downloadUrl(path: string, query?: Query): string {
  return withQuery(`${BASE}${path}`, query);
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Erro inesperado.";
}

export function errorDetails(e: unknown): string[] {
  if (!(e instanceof ApiError) || !e.details) return [];
  const d = e.details as any;
  if (Array.isArray(d)) return d.map((x) => (typeof x === "string" ? x : x.loc ? `${x.loc}: ${x.message}` : JSON.stringify(x)));
  if (Array.isArray(d.messages)) return d.messages;
  return [];
}
