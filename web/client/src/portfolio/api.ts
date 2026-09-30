export interface Instrument {
  symbol: string;
  name: string;
  exchange: string;
  currency?: string;
  security_type?: string;
  verified_at?: string;
  supported?: boolean;
  support_code?: string | null;
}
export interface PlanInput {
  symbol: string;
  horizon: "short" | "medium" | "long";
  shares: number;
  cost: string;
  reason: string;
  lower: string | null;
  upper: string | null;
  review_date: string | null;
  cost_pending: boolean;
}
export interface Plan extends PlanInput {
  id: string;
  revision: number;
  status: "active" | "closed";
  instrument: Instrument;
  created_at: string;
  updated_at: string;
}
export interface CheckResult {
  plan_id: string;
  revision: number;
  plan_snapshot: Plan;
  target_date: string;
  quote: null | {
    close: string | null;
    price_date: string | null;
    source: string;
    fetched_at: string;
    error_code: string | null;
  };
  quality: "valid" | "missing" | "stale" | "cost_pending";
  error_code: string | null;
  signals: string[];
  state: "review" | "not_triggered" | "no_conditions" | "unavailable";
  market_value: string | null;
  unrealized_pnl: string | null;
}
export interface CloseCheck {
  id: string;
  status:
    "queued" | "running" | "completed" | "partial" | "failed" | "interrupted";
  target_date: string | null;
  source: string;
  results: CheckResult[];
  error_code: string | null;
  finished_at: string | null;
}
export interface HoldingSettings {
  automatic: boolean;
  concentration_limit: string | null;
}
export interface Overview {
  plans: (Plan & { result: CheckResult | null; result_obsolete: boolean })[];
  latest_check: CloseCheck | null;
  summary: {
    complete: boolean;
    market_value: string | null;
    unrealized_pnl: string | null;
    concentrations: { symbol: string; percent: string; triggered: boolean }[];
  };
  reports: Record<
    string,
    { id: string; date: string; finished_at: string; rating: string }[]
  >;
  reference_date: string | null;
}
export interface Watch extends Instrument {
  reason: string;
  created_at: string;
  updated_at: string;
}
export interface ResearchPrefill {
  symbol: string;
  name: string;
  date: string | null;
}
export type ResearchNavigate = (
  path: string,
  prefill?: ResearchPrefill,
) => void;
export interface PortfolioApi {
  searchInstruments(
    query: string,
    signal?: AbortSignal,
  ): Promise<{ results: Instrument[]; unavailable: boolean }>;
  getOverview(): Promise<Overview>;
  listWatchlist(): Promise<{ watchlist: Watch[] }>;
  addWatch(symbol: string, reason: string): Promise<Watch>;
  updateWatch(symbol: string, reason: string): Promise<Watch>;
  removeWatch(symbol: string): Promise<void>;
  createPlan(input: PlanInput): Promise<Plan>;
  updatePlan(
    id: string,
    revision: number,
    input: Partial<PlanInput>,
  ): Promise<Plan>;
  closePlan(id: string, revision: number): Promise<Plan>;
  getSettings(): Promise<HoldingSettings>;
  updateSettings(input: HoldingSettings): Promise<HoldingSettings>;
  createCheck(): Promise<CloseCheck>;
}
const messages: Record<string, string> = {
  unsupported_market: "当前持仓与收盘检查仅支持 A 股",
  instrument_unverified: "暂时无法确认这只股票的 A 股身份，请重新选择。",
  catalog_unavailable: "A 股名录暂不可用，请稍后重试。",
  calendar_unavailable: "交易日历不可用，无法确认收盘检查日期。",
  market_dependency_missing: "行情依赖未安装，请安装项目的 search 可选依赖。",
  revision_conflict: "持仓已被修改，请刷新后重新编辑。当前输入已保留。",
  stock_limit: "最多支持 100 只不同的股票。",
  watch_exists: "这只股票已在自选清单中。",
  invalid_bounds: "下观察线必须小于上观察线。",
  invalid_decimal: "请输入正数，最多 12 位整数和 6 位小数。",
  invalid_shares: "请输入 1 至 10 亿之间的整数股数。",
  invalid_date: "请输入有效日期。",
  invalid_threshold: "集中度上限必须大于 0 且不超过 100%。",
  cost_pending: "成本待核对，暂停价格与盈亏检查。",
  stale_quote: "报价日期不匹配，无法检查。",
  missing_quote: "缺少有效收盘数据，无法检查。",
  invalid_quote: "收盘数据校验失败，无法检查。",
  market_timeout: "行情请求超时，请稍后重试。",
  interrupted: "检查被中断，请重试。",
};
export const errorMessage = (code?: string | null) =>
  messages[code ?? ""] ?? "操作未完成，请稍后重试。";
export class PortfolioError extends Error {
  constructor(
    public code: string,
    public field: string = "body",
  ) {
    super(errorMessage(code));
  }
}
async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api/portfolio${path}`, {
    method,
    signal,
    credentials: "same-origin",
    cache: "no-store",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const value = await response.json().catch(() => ({}));
    throw new PortfolioError(
      value.detail?.code ?? "request_failed",
      value.detail?.field ?? "body",
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const portfolioApi: PortfolioApi = {
  searchInstruments: (q, signal) =>
    request(
      `/instruments/search?q=${encodeURIComponent(q)}`,
      "GET",
      undefined,
      signal,
    ),
  getOverview: () => request("/overview"),
  listWatchlist: () => request("/watchlist"),
  addWatch: (symbol, reason) =>
    request("/watchlist", "POST", { symbol, reason }),
  updateWatch: (symbol, reason) =>
    request(`/watchlist/${encodeURIComponent(symbol)}`, "PATCH", { reason }),
  removeWatch: (symbol) =>
    request(`/watchlist/${encodeURIComponent(symbol)}`, "DELETE"),
  createPlan: (input) => request("/plans", "POST", input),
  updatePlan: (id, revision, input) =>
    request(`/plans/${encodeURIComponent(id)}`, "PATCH", {
      ...input,
      revision,
    }),
  closePlan: (id, revision) =>
    request(`/plans/${encodeURIComponent(id)}/close`, "POST", { revision }),
  getSettings: () => request("/settings"),
  updateSettings: (input) => request("/settings", "PATCH", input),
  createCheck: () => request("/checks", "POST"),
};
