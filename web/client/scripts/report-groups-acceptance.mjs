import { chromium, expect } from "@playwright/test";
import { preview } from "vite";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Synthetic reports only: no credentials, models, or market data are accessed.
const root = fileURLToPath(new URL("..", import.meta.url));
const output = path.resolve(root, "../../docs/design/assets");
const base = {
  ticker: "0780.HK",
  name: "TONGCHENGTRAVEL",
  date: "2026-09-24",
  params: { ticker: "0780.HK", date: "2026-09-24" },
  status: "completed",
  current_stage: null,
  current_node: null,
  decision: null,
  error: null,
  updated_at: "2026-09-24T08:15:00Z",
  started_at: null,
  sections: {},
  can_resume: false,
};
const fixtures = [
  {
    ...base,
    id: "older",
    rating: "Underweight",
    created_at: "2026-09-24T07:00:00Z",
    finished_at: "2026-09-24T07:15:00Z",
  },
  {
    ...base,
    id: "latest",
    rating: "Hold",
    created_at: "2026-09-24T08:00:00Z",
    finished_at: "2026-09-24T08:15:00Z",
  },
  {
    ...base,
    id: "other",
    ticker: "NVDA",
    name: "NVIDIA Corporation",
    rating: "Overweight",
    created_at: "2026-09-23T08:00:00Z",
    finished_at: "2026-09-23T08:15:00Z",
  },
];
const server = await preview({
  root,
  preview: { host: "127.0.0.1", port: 4189, strictPort: true },
});
let browser;
try {
  browser = await chromium.launch({ headless: true });
  for (const [device, viewport] of [
    ["desktop", { width: 1440, height: 1000 }],
    ["mobile", { width: 390, height: 844 }],
    ["tablet", { width: 768, height: 1000 }],
    ["compact-desktop", { width: 1101, height: 1000 }],
  ]) {
    const context = await browser.newContext({
      viewport,
      timezoneId: "Asia/Shanghai",
      reducedMotion: "reduce",
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let reports = [...fixtures];
    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      if (route.request().method() === "DELETE") {
        reports = reports.filter(
          (report) => !url.pathname.endsWith(`/${report.id}`),
        );
        return route.fulfill({ status: 204 });
      }
      if (url.pathname === "/api/tasks") {
        expect(url.searchParams.get("rating")).toBeNull();
        expect(url.searchParams.get("status")).toBe("completed");
        return route.fulfill({ json: { tasks: reports } });
      }
      return route.fulfill({ json: fixtures[1] });
    });
    await page.goto("http://127.0.0.1:4189/history?view=reports");
    const toggle = page.getByRole("button", { name: "0780.HK 的 2 份报告" });
    await expect(toggle).toBeVisible();
    await expect(page.getByText("0780.HK", { exact: true })).toHaveCount(1);
    await expect(page.getByText("减持 → 持有")).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({
      path: path.join(output, `report-groups-${device}-collapsed.png`),
      fullPage: true,
    });
    await toggle.click();
    const region = page.getByRole("region", { name: "0780.HK 历史报告" });
    await expect(region.getByRole("button", { name: "查看报告" })).toHaveCount(
      2,
    );
    await expect(
      region.getByText("2026/09/24 16:15", { exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
    ).toBe(false);
    // Assert all text and command surfaces stay within the viewport horizontally.
    const clipped = await page
      .locator(".report-group button, .report-group strong, .report-group time")
      .evaluateAll((elements) =>
        elements.some((element) => {
          const rect = element.getBoundingClientRect();
          return (
            rect.left < 0 ||
            rect.right > innerWidth ||
            element.scrollWidth > element.clientWidth
          );
        }),
      );
    expect(clipped).toBe(false);
    await page.screenshot({
      path: path.join(output, `report-groups-${device}-expanded.png`),
      fullPage: true,
    });
    await region
      .getByRole("button", { name: "删除 0780.HK 的报告 latest", exact: true })
      .click();
    await page.getByRole("button", { name: "确认删除" }).click();
    await expect(
      page.getByRole("button", { name: "0780.HK 的 1 份报告" }),
    ).toBeVisible();
    await expect(page.getByText("减持 → 持有")).toHaveCount(0);
    await expect(page.locator(".report-rating").first()).toHaveText("减持");
    expect(errors).toEqual([]);
    await context.close();
    console.log(
      `Report groups ${device}: grouping, expansion, deletion, layout verified`,
    );
  }
} finally {
  await browser?.close();
  await new Promise((resolve, reject) =>
    server.httpServer.close((error) => (error ? reject(error) : resolve())),
  );
}
