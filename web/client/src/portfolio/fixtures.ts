import { vi } from "vitest";
import type { Instrument, Plan, PortfolioApi, Overview } from "./api";

export const instrument: Instrument = {
  symbol: "600000.SS",
  name: "示例股份",
  exchange: "SH",
  currency: "CNY",
  security_type: "A_SHARE",
  verified_at: "2026-09-29T09:00:00Z",
  supported: true,
  support_code: null,
};
export const plan: Plan = {
  id: "p1",
  symbol: instrument.symbol,
  instrument,
  horizon: "short",
  shares: 1000,
  cost: "10.2",
  reason: "等待趋势确认",
  lower: "10",
  upper: null,
  review_date: null,
  cost_pending: false,
  revision: 1,
  status: "active",
  created_at: "2026-09-29T09:00:00Z",
  updated_at: "2026-09-29T09:00:00Z",
};
export const overview: Overview = {
  plans: [{ ...plan, result: null, result_obsolete: false }],
  latest_check: null,
  summary: {
    complete: false,
    market_value: null,
    unrealized_pnl: null,
    concentrations: [],
  },
  reports: {},
  reference_date: null,
};
export function fixturePortfolioApi(): PortfolioApi {
  return {
    searchInstruments: vi
      .fn()
      .mockResolvedValue({ results: [instrument], unavailable: false }),
    getOverview: vi.fn().mockResolvedValue(structuredClone(overview)),
    listWatchlist: vi.fn().mockResolvedValue({ watchlist: [] }),
    addWatch: vi.fn().mockResolvedValue({ ...instrument, reason: "" }),
    updateWatch: vi.fn().mockResolvedValue({ ...instrument, reason: "" }),
    removeWatch: vi.fn().mockResolvedValue(undefined),
    createPlan: vi.fn().mockResolvedValue(structuredClone(plan)),
    updatePlan: vi.fn().mockResolvedValue(structuredClone(plan)),
    closePlan: vi.fn().mockResolvedValue({ ...plan, status: "closed" }),
    getSettings: vi
      .fn()
      .mockResolvedValue({ automatic: true, concentration_limit: null }),
    updateSettings: vi
      .fn()
      .mockResolvedValue({ automatic: true, concentration_limit: null }),
    createCheck: vi
      .fn()
      .mockResolvedValue({ id: "c1", status: "queued", results: [] }),
  };
}
