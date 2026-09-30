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
