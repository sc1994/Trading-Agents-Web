import { render, screen } from "@testing-library/react";
import { Holdings } from "./Holdings";
import { fixturePortfolioApi, overview, plan } from "../portfolio/fixtures";

it("groups different plans for one stock and explains missing checks", async () => {
  const api = fixturePortfolioApi();
  api.getOverview = vi
    .fn()
    .mockResolvedValue({
      ...overview,
      plans: [
        overview.plans[0],
        {
          ...plan,
          id: "p2",
          horizon: "long",
          result: null,
          result_obsolete: false,
        },
      ],
    });
  render(<Holdings api={api} navigate={vi.fn()} />);
  expect(
    await screen.findByRole("heading", { name: "示例股份" }),
  ).toBeVisible();
  expect(screen.getAllByRole("heading", { name: "示例股份" })).toHaveLength(1);
  expect(screen.getByText("短线")).toBeVisible();
  expect(screen.getByText("长期")).toBeVisible();
  expect(screen.getAllByText("尚未检查")).toHaveLength(2);
  expect(
    screen.getByText("数据不完整，暂不计算持仓汇总与集中度。"),
  ).toBeVisible();
});
