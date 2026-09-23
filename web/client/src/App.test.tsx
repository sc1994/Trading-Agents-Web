import { render, screen, within } from "@testing-library/react";
import { App } from "./App";
import { fakeApi, resetApi } from "./test/fixtures";
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  webApi: (await import("./test/fixtures")).fakeApi,
}));
beforeEach(resetApi);
it.each(["/history", "/history?view=reports"])(
  "announces exactly one current link per desktop and mobile navigation on %s",
  async (path) => {
    window.history.replaceState({}, "", path);
    render(<App />);
    for (const name of ["主要导航", "手机导航"]) {
      const current = within(
        screen.getByRole("navigation", { name }),
      ).getAllByRole("link", { current: "page" });
      expect(current).toHaveLength(1);
      expect(current[0]).toHaveAttribute("href", path);
    }
    await screen.findByText("暂无匹配的任务");
    expect(fakeApi.listTasks).toHaveBeenCalled();
  },
);
