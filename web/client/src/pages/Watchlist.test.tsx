import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Watchlist } from "./Watchlist";
import { fixturePortfolioApi, instrument } from "../portfolio/fixtures";

it("opens a holding plan for a watched verified stock", async () => {
  const api = fixturePortfolioApi();
  api.listWatchlist = vi.fn().mockResolvedValue({
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

it("discards cancelled search results when reopening the add dialog", async () => {
  render(<Watchlist api={fixturePortfolioApi()} navigate={vi.fn()} />);
  const add = await screen.findByRole("button", { name: /添加自选/ });
  await userEvent.click(add);
  await userEvent.type(screen.getByRole("combobox"), "600000");
  await screen.findByText("示例股份 · 600000.SS");
  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  await userEvent.click(add);
  expect(screen.getByRole("combobox")).toHaveValue("");
  expect(screen.queryByText("示例股份 · 600000.SS")).not.toBeInTheDocument();
});
