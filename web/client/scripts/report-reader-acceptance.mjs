import { chromium, expect } from "@playwright/test";
import { preview } from "vite";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL("..", import.meta.url));
const output = path.resolve(root, "../../docs/design/assets");
const body = `## 监管风险的三个反驳

多头观点认为，监管带来的影响已被市场计入。但需要区分**市场预期监管发生**与**监管最终影响已经明确**，两者并不是同一个判断。

### 历史监管案例的差异

比较历史监管案例时，需要先核对监管对象、持续时间和行业背景，不能仅凭股价反弹推断恢复周期。

| 观察对象 | 需要比较的证据 | 当前判断 |
|---|---|---|
| 单家公司 | 处罚与业务调整 | 单独核对 |
| 行业平台 | 监管范围与持续时间 | 持续观察 |
| 同程旅行 | 公告与后续经营数据 | 等待验证 |

> **关键差异：** 单家公司被监管，与多个平台同时被调查，涉及的影响范围不同，需要分别验证。

### 监管是否已被定价

市场可能在正式立案之前提前反映部分监管预期。立案之后的跌幅，不能单独说明最终处罚与经营影响。

${Array.from({ length: 12 }, () => "需要结合监管公告、平台经营调整和盈利预期持续验证，避免把价格变化直接等同于基本面变化。").join("\n\n")}

## 后续需要验证的证据

优先观察监管公告、业务调整与下一期财报中的利润率变化。
`;
const sections = {
  market_report: "## 价格趋势\n\n价格与成交量需要结合观察。",
  sentiment_report: "## 情绪来源\n\n核对新闻与事件情绪来源。",
  news_report: "## 新闻证据\n\n核对公告时间与经营变化。",
  fundamentals_report: "## 现金流\n\n现金流与利润率需要跟踪。",
  bull_history:
    "Bull Analyst: ## 首轮多头观点\n\n关注需求增长。\n\nBull Analyst: ## 次轮多头观点\n\n结合后续财报验证增长。",
  bear_history: `Bear Analyst: ## 首轮空头观点\n\n关注估值风险。\n\nBear Analyst: ${body}\n\nBear Analyst: ## 第三轮观点\n\n继续跟踪监管进展。`,
  investment_plan: "## 研究结论\n\n结合风险预算审慎评估。",
  trader_investment_plan: "没有章节的完整交易计划。",
  aggressive_history:
    "Aggressive Analyst: 积极风险首轮\n\nAggressive Analyst: 积极风险次轮",
  conservative_history:
    "Conservative Analyst: 保守风险首轮\n\nConservative Analyst: 保守风险次轮",
  neutral_history:
    "Neutral Analyst: 中性风险首轮\n\nNeutral Analyst: 中性风险次轮",
  decision: "## 最终决策\n\n持续观察。",
};
const task = {
  id: "reader-demo",
  ticker: "0780.HK",
  name: "同程旅行（验收示例）",
  date: "2026-09-24",
  params: { ticker: "0780.HK", date: "2026-09-24" },
  status: "completed",
  current_stage: null,
  current_node: null,
  rating: "Hold",
  decision: sections.decision,
  error: null,
  created_at: "2026-09-24T08:00:00Z",
  updated_at: "2026-09-24T08:10:00Z",
  started_at: "2026-09-24T08:00:00Z",
  finished_at: "2026-09-24T08:10:00Z",
  sections,
  can_resume: false,
};
const server = await preview({
  root,
  preview: { host: "127.0.0.1", port: 4193, strictPort: true },
});
let browser;
try {
  browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH }
      : {}),
  });
  for (const [device, viewport] of [
    ["desktop", { width: 1440, height: 1000 }],
    ["tablet", { width: 1024, height: 900 }],
    ["mobile", { width: 390, height: 844 }],
    ["small-mobile", { width: 320, height: 844 }],
  ]) {
    const page = await browser.newPage({ viewport, reducedMotion: "reduce" });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/api/**", (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith("/report"))
        return route.fulfill({
          json: {
            task_id: task.id,
            sections,
            decision: {
              rating: "Hold",
              executive_summary: "验收示例，仅用于检查阅读布局。",
            },
          },
        });
      if (url.pathname === `/api/tasks/${task.id}`)
        return route.fulfill({ json: task });
      return route.fulfill({
        json: { holdings: [], watchlist: [], reports: {} },
      });
    });
    await page.goto(`http://127.0.0.1:4193/reports/${task.id}`);
    await page.getByRole("tab", { name: "多空研究", exact: true }).click();
    const mobileRole = page.getByRole("combobox", { name: "报告角色" });
    if (await mobileRole.isVisible())
      await mobileRole.selectOption("bear_history");
    else
      await page
        .locator(".reader-role-segments")
        .getByText("空头研究", { exact: true })
        .click();
    await page.getByRole("combobox", { name: "辩论轮次" }).selectOption("1");
    await expect(
      page.getByRole("heading", { name: "监管风险的三个反驳" }),
    ).toBeVisible();
    await expect(page.getByText("关注估值风险。", { exact: true })).toHaveCount(
      0,
    );
    const reader = page.locator(".report-reader");
    await reader.scrollIntoViewIfNeeded();
    await page.evaluate(() => {
      const node = document.querySelector(".report-reader");
      window.scrollTo(0, scrollY + node.getBoundingClientRect().top);
    });
    await page.screenshot({
      path: path.join(output, `IMPLEMENTED-report-reader-${device}.png`),
    });
    await page.getByRole("button", { name: "章节目录", exact: true }).click();
    await expect(
      page.getByRole("navigation", { name: "本轮章节" }),
    ).toBeVisible();
    if (device === "desktop")
      await page.screenshot({
        path: path.join(output, "IMPLEMENTED-report-reader-chapters.png"),
      });
    await page
      .getByRole("link", { name: "后续需要验证的证据", exact: true })
      .click();
    const heading = page.getByRole("heading", {
      name: "后续需要验证的证据",
      exact: true,
    });
    await expect(heading).toBeFocused();
    await expect(heading).toBeVisible();
    const stickyTop = await page
      .locator(".reader-controls")
      .evaluate((node) => node.getBoundingClientRect().top);
    expect(stickyTop).toBeGreaterThanOrEqual(0);
    expect(stickyTop).toBeLessThan(70);
    await page.getByRole("combobox", { name: "辩论轮次" }).selectOption("2");
    await expect(
      page.getByText("继续跟踪监管进展。", { exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "下一轮" })).toBeDisabled();
    await page.getByRole("button", { name: "上一轮" }).click();
    await expect(
      page.getByRole("heading", { name: "监管风险的三个反驳" }),
    ).toBeVisible();
    await page.evaluate(() => {
      const node = document.querySelector(".report-reader");
      window.scrollTo(0, scrollY + node.getBoundingClientRect().top + 450);
    });
    await expect
      .poll(() => reader.evaluate((node) => node.getBoundingClientRect().top))
      .toBeLessThan(-400);
    const readingHeading = page.getByRole("heading", {
      name: "监管是否已被定价",
      exact: true,
    });
    const beforeFocus = await readingHeading.boundingBox();
    await page.getByRole("button", { name: "专注阅读", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "报告阅读" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "退出专注阅读" }),
    ).toBeFocused();
    expect(await page.locator("#root").evaluate((node) => node.inert)).toBe(
      true,
    );
    expect(
      Math.abs((await readingHeading.boundingBox()).y - beforeFocus.y),
    ).toBeLessThan(10);
    if (device === "desktop")
      await page.screenshot({
        path: path.join(output, "IMPLEMENTED-report-reader-focus.png"),
      });
    await page.getByRole("button", { name: "章节目录", exact: true }).click();
    await page
      .getByRole("link", { name: "监管是否已被定价", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "监管是否已被定价" }),
    ).toBeFocused();
    const beforeExit = await readingHeading.boundingBox();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "报告阅读" })).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "专注阅读", exact: true }),
    ).toBeFocused();
    expect(await page.locator("#root").evaluate((node) => node.inert)).toBe(
      false,
    );
    expect(
      Math.abs((await readingHeading.boundingBox()).y - beforeExit.y),
    ).toBeLessThan(10);
    await page.getByRole("tab", { name: "风险团队", exact: true }).click();
    const riskRole = page.getByRole("combobox", { name: "报告角色" });
    if (await riskRole.isVisible())
      await riskRole.selectOption("conservative_history");
    else
      await page
        .locator(".reader-role-segments")
        .getByText("保守风险观点", { exact: true })
        .click();
    await page.getByRole("combobox", { name: "辩论轮次" }).selectOption("1");
    await expect(page.getByText("保守风险次轮", { exact: true })).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
    ).toBe(false);
    const controls = await page.locator(".reader-controls").boundingBox();
    expect(controls.height).toBeLessThan(65);
    await page.getByRole("tab", { name: "交易员", exact: true }).click();
    await expect(page.getByRole("combobox", { name: "辩论轮次" })).toHaveCount(
      0,
    );
    await expect(
      page.getByRole("button", { name: "章节目录", exact: true }),
    ).toHaveCount(0);
    if (device === "small-mobile") {
      await page.getByRole("button", { name: "专注阅读", exact: true }).click();
      await page.locator(".reader-focused .ant-tabs-nav-more").hover();
      const popup = page.locator(".ant-tabs-dropdown:visible");
      await expect(popup).toBeVisible();
      expect(
        await popup.evaluate((node) => !!node.closest(".report-reader")),
      ).toBe(true);
      await popup.getByText("组合经理", { exact: true }).click();
      await expect(
        page.getByRole("heading", { name: "最终决策", exact: true }),
      ).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog", { name: "报告阅读" })).toHaveCount(
        0,
      );
    }
    expect(errors).toEqual([]);
    console.log(
      `${device}: roles, rounds, chapter jumps, sticky toolbar, focus mode and overflow passed`,
    );
    if (device === "desktop" || device === "mobile") {
      await page.goto(`http://127.0.0.1:4193/tasks/${task.id}`);
      await expect(
        page.getByRole("tab", { name: "分析师", exact: true }),
      ).toBeVisible();
      const runRole = page.getByRole("combobox", { name: "报告角色" });
      if (await runRole.isVisible())
        await runRole.selectOption("fundamentals_report");
      else
        await page
          .locator(".reader-role-segments")
          .getByText("基本面分析", { exact: true })
          .click();
      await expect(
        page.getByRole("heading", { name: "现金流", exact: true }),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
      ).toBe(false);
      expect(errors).toEqual([]);
      console.log(`${device}: shared task-output reader passed`);
    }
    await page.close();
  }
} finally {
  await browser?.close();
  await new Promise((resolve) => server.httpServer.close(resolve));
}
