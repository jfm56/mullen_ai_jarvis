/**
 * Typed fetch wrapper.
 *
 * - Reads the JWT from localStorage (set by the auth context on login).
 * - Attaches Authorization: Bearer <token> on every request.
 * - Throws ApiError with the HTTP status + parsed detail on non-2xx.
 * - 401 triggers a soft sign-out (clears token, dispatches a custom event
 *   so the auth context can react and route to /login).
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

const TOKEN_KEY = "jarvis_token";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

function readToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
  window.dispatchEvent(new CustomEvent("jarvis:auth-changed"));
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.dispatchEvent(new CustomEvent("jarvis:auth-changed"));
}

export function hasToken(): boolean {
  return readToken() != null;
}

type Method = "GET" | "POST" | "PATCH" | "DELETE";

interface RequestOptions {
  method?: Method;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  // For OAuth-style form login: body is treated as application/x-www-form-urlencoded.
  form?: boolean;
}

export async function request<T>(
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, query, form } = opts;

  let url = API_BASE + path;
  if (query) {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v != null) sp.append(k, String(v));
    }
    const qs = sp.toString();
    if (qs) url += (path.includes("?") ? "&" : "?") + qs;
  }

  const headers: Record<string, string> = {};
  const token = readToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let bodyInit: BodyInit | undefined;
  if (form && body && typeof body === "object") {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(body as Record<string, string>)) {
      sp.append(k, v);
    }
    bodyInit = sp.toString();
    headers["Content-Type"] = "application/x-www-form-urlencoded";
  } else if (body !== undefined) {
    bodyInit = JSON.stringify(body);
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(url, {
    method,
    headers,
    body: bodyInit,
  });

  if (response.status === 401) {
    clearToken();
    throw new ApiError(401, null, "unauthorized");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let parsed: unknown = text;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      // leave as raw text
    }
  }

  if (!response.ok) {
    const detail =
      (parsed && typeof parsed === "object" && "detail" in (parsed as object))
        ? (parsed as { detail: unknown }).detail
        : parsed;
    throw new ApiError(
      response.status,
      detail,
      `HTTP ${response.status}: ${typeof detail === "string" ? detail : "request failed"}`,
    );
  }

  return parsed as T;
}

// ---- Typed view models matching backend Pydantic responses --------------

export interface User {
  id: string;
  username: string;
  display_name: string;
  is_admin: boolean;
}

export interface Task {
  id: string;
  title: string;
  notes: string;
  status: "pending" | "in_progress" | "done" | "cancelled";
  priority: "low" | "normal" | "high" | "urgent";
  domain: string;
  due_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Approval {
  id: string;
  created_at: string;
  decided_at: string | null;
  expires_at: string | null;
  agent: string;
  domain: string;
  action_class: string;
  action_name: string;
  target_summary: string;
  preview: string;
  payload: Record<string, unknown>;
  status: string;
  decision_note: string;
  request_id: string;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  client: string;
  vertical: string;
  status: string;
  priority: number;
  description: string;
  value_estimate: number;
  start_date: string | null;
  target_end_date: string | null;
  actual_end_date: string | null;
  created_at: string;
  updated_at: string;
}

export interface Grant {
  id: string;
  funder_type: string;
  funder_name: string;
  mechanism_code: string;
  title: string;
  status: string;
  eligibility_verdict: string;
  requested_amount: number;
  deadline: string | null;
  bundle_path: string;
  org_profile_id: string | null;
  opportunity_id: string | null;
  submission_approval_id: string | null;
  submitted_at: string | null;
  created_at: string;
  updated_at: string;
  abstract: string;
  period_months: number;
  nofo_url: string;
  eligibility_notes: string;
}

export interface AgentHandleResponse {
  text: string;
  metadata: Record<string, unknown>;
}

// ---- Convenience helpers tied to specific endpoints --------------------

export const api = {
  // Auth
  async login(username: string, password: string): Promise<{ access_token: string }> {
    return request<{ access_token: string }>("/auth/login", {
      method: "POST",
      form: true,
      body: { username, password },
    });
  },
  async me(): Promise<User> {
    return request<User>("/auth/me");
  },

  // Tasks
  async listTasks(): Promise<Task[]> {
    return request<Task[]>("/tasks");
  },
  async createTask(input: {
    title: string;
    notes?: string;
    priority?: string;
    due_at?: string | null;
  }): Promise<Task> {
    return request<Task>("/tasks", { method: "POST", body: input });
  },
  async updateTask(id: string, patch: Partial<Task>): Promise<Task> {
    return request<Task>(`/tasks/${id}`, { method: "PATCH", body: patch });
  },
  async deleteTask(id: string): Promise<void> {
    await request<void>(`/tasks/${id}`, { method: "DELETE" });
  },

  // Approvals
  async listApprovals(): Promise<Approval[]> {
    return request<Approval[]>("/approvals");
  },
  async decideApproval(
    id: string,
    approve: boolean,
    note = "",
  ): Promise<Approval> {
    return request<Approval>(`/approvals/${id}/decision`, {
      method: "POST",
      body: { approve, note },
    });
  },

  // Projects
  async listProjects(): Promise<Project[]> {
    return request<Project[]>("/projects");
  },

  // Grants
  async listGrants(): Promise<Grant[]> {
    return request<Grant[]>("/grants");
  },

  // Agent invocation — generic shape works for all 8 agents.
  async invokeAgent(
    agent: string,
    input: string,
    domain = "personal",
    permission_level = "ask_before_action",
  ): Promise<AgentHandleResponse> {
    return request<AgentHandleResponse>(`/agents/${agent}/handle`, {
      method: "POST",
      body: { input, domain, permission_level },
    });
  },
};
