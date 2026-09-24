import { chromium, expect } from "@playwright/test";
import { preview } from "vite";
import { fileURLToPath } from "node:url";
import path from "node:path";

// All API requests are intercepted. No model, credentials or market-data calls.
const root = fileURLToPath(new URL("..", import.meta.url));
const output = path.resolve(root, "../../docs/design/assets");
const server = await preview({
  root,
  preview: { host: "127.0.0.1", port: 4178, strictPort: true },
});
let browser;
const market =
  "营收增长与现金流表现为本次研究提供依据。\n\n### 趋势观察\n\n价格维持区间整理，成交量变化仍需持续跟踪。\n\n> 本节为已保存的分析师报告。\n\n### 需要关注\n\n- 产品需求与后续订单变化\n- 估值水平与盈利预期\n- 行业竞争及宏观环境";
const task = {
  id: "demo",
  ticker: "NVDA",
  name: "NVIDIA Corporation",
  date: "2026-09-22",
  params: {
    ticker: "NVDA",
    date: "2026-09-22",
    language: "简体中文",
    depth: "standard",
    provider: "openai",
    quick_model: "gpt-5.6-luna",
    deep_model: "gpt-5.6",
    analysts: ["market", "fundamentals"],
    checkpoint_enabled: true,
  },
  status: "completed",
  current_stage: null,
  current_node: null,
  rating: "Overweight",
  decision:
    "**Rating**: Overweight\n\n**Executive Summary**: 数据中心需求持续增长，估值与供应链风险仍需关注。",
  error: null,
  created_at: "2026-09-22T08:00:00Z",
  updated_at: "2026-09-22T08:12:00Z",
  started_at: "2026-09-22T08:00:01Z",
  finished_at: "2026-09-22T08:12:00Z",
  can_resume: false,
  sections: {
    market_report: market,
    fundamentals_report:
      "业务增长与盈利能力保持韧性，后续仍需验证订单与收入兑现情况。",
    bull_history: "数据中心需求与产品迭代构成增长依据。",
    bear_history: "较高估值可能放大盈利不及预期时的波动。",
    investment_plan: "持续观察增长预期与估值变化。",
    trader_investment_plan: "结合价格趋势与风险预算审慎评估。",
    conservative_history:
      "估值压缩、供应集中与出口限制可能影响未来收入。\n\n需要结合后续财报验证。",
    decision:
      "**Rating**: Overweight\n\n增长前景获得研究支持，同时保留对估值风险的关注。",
  },
};
const running = {
  ...task,
  id: "live",
  ticker: "AAPL",
  name: "Apple Inc.",
  status: "running",
  rating: null,
  decision: null,
  finished_at: null,
  sections: {
    market_report: market,
    fundamentals_report: "服务业务与现金流表现稳定，硬件换机周期仍需观察。",
    bull_history: "生态系统与经常性收入提供增长支持。",
  },
};
const settingsFixture = {
  provider: "openai",
  quick_model: "gpt-5.6-luna",
  deep_model: "gpt-5.6",
  language: "简体中文",
  checkpoint_enabled: true,
  keys: {
    openai: { configured: true, last4: "abcd" },
    google: { configured: false, last4: null },
    fred: { configured: false, last4: null },
  },
};
let providers = [
  {
    id: "openai",
    name: "OpenAI",
    kind: "built_in",
    base_url: null,
    key: { configured: true, last4: "abcd" },
  },
  {
    id: "custom:11111111-1111-4111-8111-111111111111",
    name: "本地推理",
    kind: "custom",
    base_url: "http://localhost:1234/v1",
    key: { configured: false, last4: null },
  },
];
const currentSettings = () => ({ ...settingsFixture, providers });
const history = [
  task,
  running,
  {
    ...task,
    id: "review",
    ticker: "BTC-USD",
    name: "Bitcoin USD",
    rating: "REVIEW",
  },
  {
    ...task,
    id: "paused",
    ticker: "TSLA",
    name: "Tesla, Inc.",
    status: "interrupted",
    rating: null,
    can_resume: true,
  },
  {
    ...task,
    id: "failed",
    ticker: "0700.HK",
    name: "Tencent Holdings Limited",
    status: "failed",
    rating: null,
  },
];
const pages = [
  ["start", "/", "发起一次分析"],
  ["run", "/tasks/live", "AAPL 任务运行"],
  ["report", "/reports/demo", "NVDA 决策报告"],
  ["history", "/history", "任务记录"],
  ["settings", "/settings", "模型与 API 设置"],
];
try {
  browser = await chromium.launch({ headless: true });
  for (const [device, viewport] of [
    ["desktop", { width: 1440, height: 1000 }],
    ["mobile", { width: 390, height: 844 }],
  ]) {
    const context = await browser.newContext({
      viewport,
      reducedMotion: "reduce",
    });
    const page = await context.newPage();
    const eventCursors = [];
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      const json = (value) => route.fulfill({ json: value });
      if (url.pathname === "/api/settings") return json(currentSettings());
      if (url.pathname === "/api/settings/providers") {
        if (route.request().method() === "POST") {
          const body = JSON.parse(route.request().postData() || "{}");
          if (body.kind === "custom")
            providers = [
              ...providers,
              {
                id: `custom:${crypto.randomUUID()}`,
                name: body.name,
                kind: "custom",
                base_url: body.base_url,
                key: { configured: Boolean(body.key), last4: null },
              },
            ];
        }
        return json(currentSettings());
      }
      if (url.pathname.startsWith("/api/settings/providers/"))
        return json(currentSettings());
      if (url.pathname === "/api/assets/search")
        return json({ results: [], unavailable: false });
      if (url.pathname.endsWith("/events")) {
        eventCursors.push(url.searchParams.get("after"));
        return route.fulfill({
          contentType: "text/event-stream",
          body: 'id: 7\nevent: section\ndata: {"section":"market_report","text":"persisted"}\n\n',
        });
      }
      if (url.pathname === "/api/tasks")
        return json({
          tasks: history.filter(
            (item) =>
              (!url.searchParams.get("status") ||
                item.status === url.searchParams.get("status")) &&
              (!url.searchParams.get("rating") ||
                item.rating === url.searchParams.get("rating")),
          ),
        });
      if (url.pathname.endsWith("/report"))
        return json({
          task_id: task.id,
          sections: task.sections,
          decision: {
            rating: task.rating,
            executive_summary:
              "数据中心需求与产品迭代支持增长前景。当前估值已反映较高预期，需要持续关注盈利兑现情况。",
            investment_thesis:
              "增长依据来自数据中心业务需求与产品更新。现金流和盈利能力提供支持，后续订单与收入兑现仍需验证。",
            price_target: "未给出具体数值；以原报告后续更新为准。",
            time_horizon: "中期，持续跟踪后续财报。",
          },
        });
      if (url.pathname.endsWith("/report.md"))
        return route.fulfill({
          contentType: "text/markdown",
          body: task.decision,
        });
      if (url.pathname === "/api/tasks/live") return json(running);
      if (url.pathname.startsWith("/api/tasks/")) return json(task);
      throw new Error(`Unexpected fixture request: ${url.pathname}`);
    });
    for (const [name, route] of pages) {
      await page.goto(`http://127.0.0.1:4178${route}`);
      await expect(page.locator("h1")).toBeVisible();
      if (name === "history")
        await expect(page.getByText("NVIDIA Corporation")).toBeVisible();
      if (name === "run")
        await expect(
          page.getByRole("tab", { name: "分析师", exact: true }),
        ).toBeVisible();
      if (name === "run") {
        await expect(page.getByText(/连接已断开/)).toBeVisible();
        await page.getByRole("button", { name: "重新连接" }).click();
        await expect.poll(() => eventCursors.at(-1)).toBe("7");
        await expect(page.getByText(/连接已断开/)).toBeVisible();
      }
      if (name === "report")
        await expect(page.getByText("增持", { exact: true })).toBeVisible();
      if (name === "start")
        await expect(page.getByLabel("股票 / 资产代码")).toBeVisible();
      if (name === "settings")
        await expect(
          page.getByRole("tab", { name: "模型供应商" }),
        ).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      );
      expect(overflow, `${name}/${device} must not overflow viewport`).toBe(
        false,
      );
      await page.screenshot({
        path: path.join(output, `IMPLEMENTED-task-8-${name}-${device}.png`),
      });
      if (name === "settings") {
        // Provider management: open the join dialog, assert the built-in
        // picker appears for the built-in kind, then submit a keyless
        // custom endpoint and observe the compact joined row.
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.getByRole("button", { name: "加入供应商" }).click();
        await expect(page.getByRole("dialog")).toBeVisible();
        await expect(page.getByLabel("名称")).toBeVisible();
        await page.evaluate(() => document.fonts.ready);
        await page.screenshot({
          path: path.join(
            output,
            `IMPLEMENTED-provider-management-join-dialog-${device}.png`,
          ),
        });
        await page.getByRole("button", { name: "取消" }).click();
        await expect(page.getByRole("dialog")).toBeHidden();
        await page.getByRole("button", { name: "加入供应商" }).click();
        await expect(page.getByRole("dialog")).toBeVisible();
        const kindSelect = page.locator(".ant-modal [role='combobox']").first();
        await kindSelect.focus();
        await page.keyboard.press("Enter");
        const builtInOption = page.locator(
          '.ant-select-item-option[title="内置供应商"]',
        );
        await expect(builtInOption).toBeVisible();
        await page.keyboard.press("ArrowDown");
        await page.keyboard.press("Enter");
        await expect(page.getByLabel("选择内置供应商")).toBeVisible();
        await page.getByRole("button", { name: "取消" }).click();
        await expect(page.getByRole("dialog")).toBeHidden();
        await page.getByRole("button", { name: "加入供应商" }).click();
        await expect(page.getByRole("dialog")).toBeVisible();
        await page.getByLabel("名称").fill("浏览器网关");
        await page.getByLabel("接口地址").fill("http://localhost:1234/v1");
        await page.getByRole("button", { name: "保存", exact: true }).click();
        await expect(page.getByText("浏览器网关")).toBeVisible();
        await expect(page.getByRole("dialog")).toBeHidden();
        await page.evaluate(() => document.fonts.ready);
        const overflowAfterJoin = await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        );
        expect(
          overflowAfterJoin,
          `settings/${device} must not overflow after joining a supplier`,
        ).toBe(false);
        await page.screenshot({
          path: path.join(
            output,
            `IMPLEMENTED-provider-management-settings-${device}.png`,
          ),
        });
        console.log(
          `PASS ${name}/${device}: join dialog, compact row and no overflow`,
        );
      }
      if (device === "mobile") {
        await page.evaluate(() =>
          window.scrollTo(0, document.body.scrollHeight),
        );
        const clearance = await page.evaluate(() => {
          const nav = document
            .querySelector(".bottom-nav")
            .getBoundingClientRect();
          const main = document.querySelector("main");
          const last = main.lastElementChild.getBoundingClientRect();
          return { bottom: last.bottom, navTop: nav.top };
        });
        expect(
          clearance.bottom,
          `${name} bottom content clears navigation`,
        ).toBeLessThanOrEqual(clearance.navTop);
        if (name === "report")
          await page.screenshot({
            path: path.join(
              output,
              "IMPLEMENTED-task-8-report-mobile-bottom.png",
            ),
          });
      }
      console.log(
        `PASS ${name}/${device}: viewport overflow and navigation clearance`,
      );
    }
    expect(errors).toEqual([]);
    await context.close();
  }
} finally {
  await browser?.close();
  await new Promise((resolve) => server.httpServer.close(resolve));
}
