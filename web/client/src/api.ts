export interface Asset {
  symbol: string;
  name: string;
  exchange: string;
  type: string;
}
export interface SearchResponse {
  results: Asset[];
  unavailable: boolean;
}
export interface KeyStatus {
  configured: boolean;
  last4: string | null;
}
export interface SettingsView {
  provider: string;
  quick_model: string;
  deep_model: string;
  language: string;
  checkpoint_enabled: boolean;
  keys: Record<string, KeyStatus>;
}
export interface SettingsChanges extends Partial<Omit<SettingsView, "keys">> {
  keys?: Record<string, string>;
  clear_keys?: string[];
}
export interface TaskParams {
  ticker: string;
  date: string;
  name?: string;
  asset_type?: string;
  depth?: string;
  language?: string;
  provider?: string;
  quick_model?: string;
  deep_model?: string;
  analysts?: string[];
  max_debate_rounds?: number;
  max_risk_discuss_rounds?: number;
  checkpoint_enabled?: boolean;
}
export interface TaskView {
  id: string;
  params: TaskParams;
  ticker: string;
  name: string;
  date: string;
  status: "queued" | "running" | "completed" | "failed" | "interrupted";
  current_stage: string | null;
  current_node: string | null;
  rating:
    | "Buy"
    | "Overweight"
    | "Hold"
    | "Underweight"
    | "Sell"
    | "REVIEW"
    | null;
  decision: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  sections: Record<string, string>;
  can_resume: boolean;
}
export interface WebApi {
  searchSymbols(q: string, signal?: AbortSignal): Promise<SearchResponse>;
  createTask(params: TaskParams): Promise<TaskView>;
  getSettings(): Promise<SettingsView>;
  saveSettings(changes: SettingsChanges): Promise<SettingsView>;
  testConnection(provider: string): Promise<{ ok: boolean; error?: string }>;
}
export class ApiError extends Error {
  constructor(
    public status: number,
    public fields: Record<string, string> = {},
  ) {
    super("请求失败，请检查输入或稍后重试。");
  }
}
export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const fields: Record<string, string> = {};
    if (Array.isArray(body.detail))
      for (const issue of body.detail) {
        const field = issue.loc?.at(-1);
        if (typeof field === "string")
          fields[field] =
            field === "provider"
              ? "供应商配置不可用，请检查密钥与模型。"
              : "请检查此项输入。";
      }
    throw new ApiError(response.status, fields);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const webApi: WebApi = {
  searchSymbols: (q, signal) =>
    request(`/assets/search?q=${encodeURIComponent(q)}`, { signal }),
  createTask: (params) =>
    request("/tasks", { method: "POST", body: JSON.stringify(params) }),
  getSettings: () => request("/settings"),
  saveSettings: (changes) =>
    request("/settings", { method: "PATCH", body: JSON.stringify(changes) }),
  testConnection: (provider) =>
    request("/settings/test-connection", {
      method: "POST",
      body: JSON.stringify({ provider }),
    }),
};
