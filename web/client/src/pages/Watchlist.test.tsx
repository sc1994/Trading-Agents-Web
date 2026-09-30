import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Watchlist } from "./Watchlist";
import { fixturePortfolioApi, instrument } from "../portfolio/fixtures";

it("opens a holding plan for a watched verified stock", async () => {
  const api = fixturePortfolioApi();
  api.listWatchlist = vi
    .fn()
    .mockResolvedValue({
      watchlist: [
        {
          ...instrument,
          reason: "等待财报",
          created_at: "2026-09-29",
          updated_at: "2026-09-29",
        },
      ],
    });
  render(<Watchlist api={api} navigate={vi.fn()} />);
  await screen.findByText("等待财报");
  await userEvent.click(screen.getByRole("button", { name: "建立持仓计划" }));
  await waitFor(() =>
    expect(screen.getByRole("dialog", { name: "新增持仓计划" })).toBeVisible(),
  );
  expect(screen.getByRole("combobox")).toHaveValue("示例股份 · 600000.SS");
});
