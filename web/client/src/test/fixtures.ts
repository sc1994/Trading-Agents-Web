import { vi } from "vitest";
import type { SettingsView, TaskView, WebApi } from "../api";

export const customProviderId =
  "custom:11111111-1111-4111-8111-111111111111";
export const settings: SettingsView = {
  provider: "openai",
  quick_model: "gpt-5.6-luna",
  deep_model: "gpt-5.6",
  language: "简体中文",
  checkpoint_enabled: true,
  keys: {
    openai: { configured: true, last4: "abcd" },
    google: { configured: false, last4: null },
    fred: { configured: false, last4: null },
    alpha_vantage: { configured: true, last4: "wxyz" },
  },
  providers: [
    {
      id: "openai",
      name: "OpenAI",
      kind: "built_in",
      base_url: null,
      key: { configured: true, last4: "abcd" },
    },
    {
      id: customProviderId,
      name: "本地推理",
      kind: "custom",
      base_url: "http://localhost:1234/v1",
      key: { configured: false, last4: null },
    },
  ],
};
export const task: TaskView = {
  id: "task-123",
  params: { ticker: "NVDA", date: "2026-09-22" },
  ticker: "NVDA",
  name: "NVIDIA Corporation",
  date: "2026-09-22",
  status: "queued",
  current_stage: null,
  current_node: null,
  rating: null,
  decision: null,
  error: null,
  created_at: "2026-09-22T08:00:00Z",
  updated_at: "2026-09-22T08:00:00Z",
  started_at: null,
  finished_at: null,
  sections: {},
  can_resume: false,
};
export const fakeApi: WebApi = {
  getTask: vi.fn(),
  listTasks: vi.fn(),
  getReport: vi.fn(),
  subscribeTask: vi.fn(),
  resumeTask: vi.fn(),
  rerunTask: vi.fn(),
  deleteTask: vi.fn(),
  searchSymbols: vi.fn(),
  createTask: vi.fn(),
  getSettings: vi.fn(),
  saveSettings: vi.fn(),
  testConnection: vi.fn(),
  addProvider: vi.fn(),
  editProvider: vi.fn(),
  removeProvider: vi.fn(),
};
export const navigate = vi.fn();
export function resetApi() {
  Object.values(fakeApi).forEach((method) => vi.mocked(method).mockReset());
  navigate.mockReset();
  vi.mocked(fakeApi.getTask).mockResolvedValue(structuredClone(task));
  vi.mocked(fakeApi.listTasks).mockResolvedValue({ tasks: [] });
  vi.mocked(fakeApi.getReport).mockResolvedValue({
    task_id: task.id,
    sections: {},
    decision: null,
  });
  vi.mocked(fakeApi.subscribeTask).mockReturnValue(vi.fn());
  vi.mocked(fakeApi.resumeTask).mockResolvedValue(structuredClone(task));
  vi.mocked(fakeApi.rerunTask).mockResolvedValue(structuredClone(task));
  vi.mocked(fakeApi.deleteTask).mockResolvedValue(undefined);
  vi.mocked(fakeApi.getSettings).mockResolvedValue(structuredClone(settings));
  vi.mocked(fakeApi.saveSettings).mockResolvedValue(structuredClone(settings));
  vi.mocked(fakeApi.addProvider).mockResolvedValue(structuredClone(settings));
  vi.mocked(fakeApi.editProvider).mockResolvedValue(structuredClone(settings));
  vi.mocked(fakeApi.removeProvider).mockResolvedValue(structuredClone(settings));
  vi.mocked(fakeApi.searchSymbols).mockResolvedValue({
    results: [
      {
        symbol: "NVDA",
        name: "NVIDIA Corporation",
        exchange: "NASDAQ",
        type: "EQUITY",
      },
    ],
    unavailable: false,
  });
  vi.mocked(fakeApi.createTask).mockResolvedValue(structuredClone(task));
  vi.mocked(fakeApi.testConnection).mockResolvedValue({ ok: true });
}
