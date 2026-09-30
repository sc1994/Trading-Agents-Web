import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PlanForm } from "./PlanForm";
import { PortfolioError } from "./api";
import { fixturePortfolioApi, plan } from "./fixtures";

it("preserves entered fields after a revision conflict", async () => {
  const api = fixturePortfolioApi();
  api.updatePlan = vi
    .fn()
    .mockRejectedValue(new PortfolioError("revision_conflict", "revision"));
  render(
    <PlanForm api={api} plan={plan} onSaved={vi.fn()} onCancel={vi.fn()} />,
  );
  const reason = screen.getByLabelText("买入理由");
  await userEvent.clear(reason);
  await userEvent.type(reason, "保留这个理由");
  await userEvent.click(screen.getByRole("button", { name: "保存计划" }));
  expect(
    await screen.findByText("持仓已被修改，请刷新后重新编辑。当前输入已保留。"),
  ).toBeVisible();
  expect(reason).toHaveValue("保留这个理由");
});
