import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InstrumentPicker } from "./InstrumentPicker";
import { fixturePortfolioApi, instrument } from "./fixtures";

it("explains why a non-A-share result cannot be selected", async () => {
  const api = fixturePortfolioApi();
  api.searchInstruments = vi.fn().mockResolvedValue({
    results: [
      {
        symbol: "NVDA",
        name: "NVIDIA",
        exchange: "US",
        supported: false,
        support_code: "unsupported_market",
      },
    ],
    unavailable: false,
  });
  render(<InstrumentPicker api={api} onChange={vi.fn()} />);
  await userEvent.type(screen.getByRole("combobox"), "NVDA");
  expect(
    await screen.findByText("当前持仓与收盘检查仅支持 A 股"),
  ).toBeVisible();
});

it("keeps async candidates open after replacing an unsupported query", async () => {
  const api = fixturePortfolioApi();
  api.searchInstruments = vi.fn().mockImplementation(async (query: string) => ({
    results:
      query === "NVDA"
        ? [
            {
              symbol: "NVDA",
              name: "NVIDIA",
              exchange: "US",
              supported: false,
              support_code: "unsupported_market",
            },
          ]
        : [instrument],
    unavailable: false,
  }));
  render(<InstrumentPicker api={api} onChange={vi.fn()} />);
  const input = screen.getByRole("combobox");
  await userEvent.type(input, "NVDA");
  await screen.findByText("当前持仓与收盘检查仅支持 A 股");
  await userEvent.clear(input);
  await userEvent.type(input, "600000");
  await screen.findByText("示例股份 · 600000.SS");
  await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "true"));
});

it("allows verified cached stocks and identifies an unrelated exchange outage", async () => {
  const api = fixturePortfolioApi();
  api.searchInstruments = vi.fn().mockResolvedValue({
    results: [
      {
        ...instrument,
        catalog_state: "stale",
        catalog_fetched_at: "2026-09-28T08:00:00Z",
      },
    ],
    unavailable: false,
    catalog_status: [
      {
        exchange: "SH",
        state: "stale",
        fetched_at: "2026-09-28T08:00:00Z",
        refreshing: false,
        error_code: "market_timeout",
      },
      {
        exchange: "BJ",
        state: "unavailable",
        fetched_at: null,
        refreshing: false,
        error_code: "market_timeout",
      },
    ],
  });
  const selected = vi.fn();
  render(<InstrumentPicker api={api} onChange={selected} />);
  await userEvent.type(screen.getByRole("combobox"), "600000");
  await screen.findByText(/沪市：使用 2026-09-28 名录/);
  expect(screen.getByText(/北交所：名录更新失败/)).toBeVisible();
  expect(screen.getByText(/北交所：名录更新失败（请求超时）/)).toBeVisible();
  await userEvent.click(screen.getByText("示例股份 · 600000.SS"));
  expect(selected).toHaveBeenLastCalledWith(
    expect.objectContaining({ symbol: "600000.SS" }),
  );
});

it("refreshes loading results without requiring the user to retype", async () => {
  const api = fixturePortfolioApi();
  api.searchInstruments = vi
    .fn()
    .mockResolvedValueOnce({
      results: [],
      unavailable: true,
      catalog_status: [
        {
          exchange: "SH",
          state: "loading",
          fetched_at: null,
          refreshing: true,
          error_code: null,
        },
      ],
    })
    .mockResolvedValue({
      results: [instrument],
      unavailable: false,
      catalog_status: [],
    });
  render(<InstrumentPicker api={api} onChange={vi.fn()} />);
  await userEvent.type(screen.getByRole("combobox"), "600000");
  await screen.findByText(/沪市：首次加载名录/);
  await waitFor(
    () => expect(screen.getByText("示例股份 · 600000.SS")).toBeVisible(),
    { timeout: 4000 },
  );
});

it("closes async choices with Escape without discarding the search", async () => {
  render(<InstrumentPicker api={fixturePortfolioApi()} onChange={vi.fn()} />);
  const input = screen.getByRole("combobox");
  await userEvent.type(input, "600000");
  await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "true"));
  await userEvent.keyboard("{Escape}");
  await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "false"));
  expect(input).toHaveValue("600000");
  await userEvent.keyboard("{ArrowDown}");
  await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "true"));
});
