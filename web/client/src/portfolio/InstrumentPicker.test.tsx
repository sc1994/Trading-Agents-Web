import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InstrumentPicker } from "./InstrumentPicker";
import { fixturePortfolioApi } from "./fixtures";

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
