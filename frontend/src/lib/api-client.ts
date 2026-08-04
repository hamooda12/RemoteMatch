const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000/api/v1";

type ApiErrorPayload = {
  detail?: unknown;
};

type CsrfResponse = {
  csrf_token: string;
};

let cachedCsrfToken: string | null = null;

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function formatErrorDetail(detail: unknown): string {
  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (
          typeof item === "object" &&
          item !== null &&
          "msg" in item
        ) {
          return String(item.msg);
        }

        return null;
      })
      .filter((message): message is string => message !== null);

    if (messages.length > 0) {
      return messages.join(" ");
    }
  }

  return "The request could not be completed.";
}

async function readError(response: Response): Promise<ApiError> {
  try {
    const payload = (await response.json()) as ApiErrorPayload;

    return new ApiError(
      response.status,
      formatErrorDetail(payload.detail),
    );
  } catch {
    return new ApiError(
      response.status,
      response.statusText || "The request failed.",
    );
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);

  headers.set("Accept", "application/json");

  if (
    options.body !== undefined &&
    !(options.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  const response = await fetch(
    `${API_BASE_URL}${normalizedPath}`,
    {
      ...options,
      headers,
      credentials: "include",
    },
  );

  if (!response.ok) {
    throw await readError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
export async function apiDownload(
  path: string,
): Promise<Blob> {
  const normalizedPath = path.startsWith("/")
    ? path
    : `/${path}`;

  const response = await fetch(
    `${API_BASE_URL}${normalizedPath}`,
    {
      method: "GET",
      credentials: "include",
      headers: {
        Accept: "application/octet-stream",
      },
    },
  );

  if (!response.ok) {
    throw await readError(response);
  }

  return response.blob();
}

export async function getCsrfToken(
  forceRefresh = false,
): Promise<string> {
  if (cachedCsrfToken !== null && !forceRefresh) {
    return cachedCsrfToken;
  }

  const response = await apiRequest<CsrfResponse>(
    "/auth/csrf",
  );

  cachedCsrfToken = response.csrf_token;

  return cachedCsrfToken;
}

export function clearCsrfToken(): void {
  cachedCsrfToken = null;
}

export async function apiMutation<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const csrfToken = await getCsrfToken();
  const headers = new Headers(options.headers);

  headers.set("X-CSRF-Token", csrfToken);

  return apiRequest<T>(path, {
    ...options,
    headers,
  });
}