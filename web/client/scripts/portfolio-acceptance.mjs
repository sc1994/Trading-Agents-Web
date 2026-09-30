import { chromium, expect } from "@playwright/test";
import { preview } from "vite";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL("..", import.meta.url));
const output = path.resolve(root, "../../docs/design/assets");
const server = await preview({
  root,
  preview: { host: "127.0.0.1", port: 0, strictPort: false },
});
const address = server.httpServer.address();
const base = `http://127.0.0.1:${address.port}`;
const date = "2026-09-29";
const instruments = [
  { symbol: "600000.SS", name: "示例股份", exchange: "SH" },
  { symbol: "000001.SZ", name: "观察股份", exchange: "SZ" },
].map((item) => ({
  ...item,
  currency: "CNY",
  security_type: "A_SHARE",
  verified_at: `${date}T09:00:00Z`,
  supported: true,
  support_code: null,
}));
const modelSettings = {
  provider: "openai",
  quick_model: "gpt-5.6-luna",
  deep_model: "gpt-5.6",
  language: "简体中文",
  checkpoint_enabled: true,
  keys: { openai: { configured: true, last4: "demo" } },
  providers: [
    {
      id: "openai",
      name: "OpenAI",
      kind: "built_in",
      base_url: null,
      key: { configured: true, last4: "demo" },
    },
  ],
};
let browser;
let lastPage;
try {
  browser = await chromium.launch({
    headless: true,
    ...(existsSync("/usr/bin/google-chrome")
      ? { executablePath: "/usr/bin/google-chrome" }
      : {}),
    args: ["--no-sandbox"],
  });
  for (const [device, viewport] of [
    ["desktop", { width: 1440, height: 1000 }],
    ["mobile", { width: 390, height: 844 }],
  ]) {
    const context = await browser.newContext({
      viewport,
      reducedMotion: process.env.PORTFOLIO_MOTION ?? "reduce",
    });
    const page = await context.newPage();
    lastPage = page;
    page.setDefaultTimeout(10000);
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    page.on("requestfailed", (request) => {
      if (!request.failure()?.errorText.includes("ERR_ABORTED"))
        errors.push(`request failed: ${request.url()}`);
    });
    let plans = [
      {
        id: "p1",
        symbol: "600000.SS",
        horizon: "short",
        shares: 1000,
        cost: "10.2",
        reason: "短线观察：等待量价条件确认",
        lower: "10",
        upper: "11",
        review_date: null,
      },
      {
        id: "p2",
        symbol: "600000.SS",
        horizon: "long",
        shares: 2000,
        cost: "9.1",
        reason: "长期计划：下一次财报后重新复核",
        lower: null,
        upper: null,
        review_date: "2026-10-30",
      },
      {
        id: "p3",
        symbol: "000001.SZ",
        horizon: "medium",
        shares: 500,
        cost: "12",
        reason: "观察行业预期变化",
        lower: "11",
        upper: null,
        review_date: null,
      },
    ].map((p) => ({
      ...p,
      instrument: instruments.find((i) => i.symbol === p.symbol),
      revision: 1,
      cost_pending: false,
      status: "active",
      created_at: `${date}T08:00:00Z`,
      updated_at: `${date}T08:00:00Z`,
    }));
    let watches = [
      {
        ...instruments[1],
        reason: "等待业绩预告与估值变化",
        created_at: date,
        updated_at: date,
      },
    ];
    let settings = { automatic: true, concentration_limit: "40" };
    let results = [
      {
        plan_id: "p1",
        revision: 1,
        plan_snapshot: structuredClone(plans[0]),
        target_date: date,
        quote: {
          close: "9.9",
          price_date: date,
          source: "演示数据 · 不复权收盘",
          fetched_at: `${date}T08:45:00Z`,
          error_code: null,
        },
        quality: "valid",
        error_code: null,
        signals: ["lower"],
        state: "review",
        market_value: "9900",
        unrealized_pnl: "-300",
      },
      {
        plan_id: "p2",
        revision: 1,
        plan_snapshot: structuredClone(plans[1]),
        target_date: date,
        quote: {
          close: "9.9",
          price_date: date,
          source: "演示数据 · 不复权收盘",
          fetched_at: `${date}T08:45:00Z`,
          error_code: null,
        },
        quality: "valid",
        error_code: null,
        signals: [],
        state: "not_triggered",
        market_value: "19800",
        unrealized_pnl: "1600",
      },
      {
        plan_id: "p3",
        revision: 1,
        plan_snapshot: structuredClone(plans[2]),
        target_date: date,
        quote: {
          close: null,
          price_date: null,
          source: "演示数据",
          fetched_at: `${date}T08:45:00Z`,
          error_code: "missing_quote",
        },
        quality: "missing",
        error_code: "missing_quote",
        signals: [],
        state: "unavailable",
        market_value: null,
        unrealized_pnl: null,
      },
    ];
    let check = {
      id: "c1",
      status: "partial",
      target_date: date,
      source: "manual",
      results,
      error_code: null,
      finished_at: `${date}T08:45:00Z`,
    };
    let pendingReads = 0;
    let serial = 3;
    const view = () => {
      if (check.status === "queued" && ++pendingReads > 1)
        check = { ...check, status: "partial" };
      return {
        plans: plans.map((p) => {
          const result = results.find((r) => r.plan_id === p.id) ?? null;
          return {
            ...p,
            result,
            result_obsolete: !!result && result.revision !== p.revision,
          };
        }),
        latest_check: check,
        summary: {
          complete: false,
          market_value: null,
          unrealized_pnl: null,
          concentrations: [],
        },
        reports: {},
        reference_date: date,
      };
    };
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();
      const body = request.postData() ? request.postDataJSON() : {};
      const json = (value, status = 200) =>
        route.fulfill({ json: value, status });
      if (url.pathname === "/api/settings") return json(modelSettings);
      if (url.pathname === "/api/assets/search")
        return json({ results: [], unavailable: false });
      const endpoint = url.pathname.replace("/api/portfolio", "");
      if (endpoint === "/overview") return json(view());
      if (endpoint === "/settings") {
        if (method === "PATCH") settings = body;
        return json(settings);
      }
      if (endpoint === "/instruments/search") {
        const q = url.searchParams.get("q") ?? "";
        return json({
          results: q.toUpperCase().includes("NVDA")
            ? [
                {
                  symbol: "NVDA",
                  name: "NVIDIA",
                  exchange: "US",
                  supported: false,
                  support_code: "unsupported_market",
                },
              ]
            : instruments.filter(
                (i) => i.symbol.includes(q) || i.name.includes(q),
              ),
          unavailable: false,
        });
      }
      if (endpoint === "/plans" && method === "POST") {
        const p = {
          ...body,
          id: `p${++serial}`,
          instrument: instruments.find((i) => i.symbol === body.symbol),
          revision: 1,
          status: "active",
          created_at: date,
          updated_at: date,
        };
        plans.push(p);
        return json(p, 201);
      }
      if (endpoint.startsWith("/plans/")) {
        const id = endpoint.split("/")[2];
        const p = plans.find((p) => p.id === id);
        if (body.revision !== p.revision)
          return json(
            { detail: { code: "revision_conflict", field: "revision" } },
            409,
          );
        if (endpoint.endsWith("/close")) {
          plans = plans.filter((p) => p.id !== id);
          return json({ ...p, status: "closed", revision: p.revision + 1 });
        }
        Object.assign(p, body, { revision: p.revision + 1 });
        return json(p);
      }
      if (endpoint === "/watchlist") {
        if (method === "POST") {
          const w = {
            ...instruments.find((i) => i.symbol === body.symbol),
            reason: body.reason,
            created_at: date,
            updated_at: date,
          };
          watches.push(w);
          return json(w, 201);
        }
        return json({ watchlist: watches });
      }
      if (endpoint.startsWith("/watchlist/")) {
        const symbol = decodeURIComponent(endpoint.split("/")[2]);
        if (method === "DELETE") {
          watches = watches.filter((w) => w.symbol !== symbol);
          return route.fulfill({ status: 204 });
        }
        const row = watches.find((w) => w.symbol === symbol);
        row.reason = body.reason;
        return json(row);
      }
      if (endpoint === "/checks" && method === "POST") {
        pendingReads = 0;
        check = { ...check, status: "queued" };
        return json(check, 202);
      }
      errors.push(`unexpected API: ${method} ${url.pathname}`);
      return json({ error: "unexpected" }, 500);
    });
    async function fit() {
      await expect
        .poll(async () =>
          page.evaluate(
            () => document.documentElement.scrollWidth <= window.innerWidth,
          ),
        )
        .toBe(true);
      const checks = await page
        .locator("button, h1, h2, .holding-plan, .portfolio-metrics strong")
        .evaluateAll((elements) =>
          elements
            .filter((el) => {
              const r = el.getBoundingClientRect();
              return (
                r.width && r.height && (r.x < -1 || r.right > innerWidth + 1)
              );
            })
            .map((el) => el.textContent),
        );
      expect(checks).toEqual([]);
    }
    await page.goto(`${base}/holdings`);
    await expect(page.getByRole("heading", { name: "示例股份" })).toBeVisible();
    await expect(page.getByText("部分数据缺失", { exact: true })).toBeVisible();
    await fit();
    await page.screenshot({
      path: path.join(output, `IMPLEMENTED-portfolio-holdings-${device}.png`),
      fullPage: true,
    });
    await page
      .getByRole("button", { name: /新增持仓/ })
      .first()
      .click();
    const dialog = page.getByRole("dialog", { name: "新增持仓计划" });
    await dialog.getByRole("combobox").fill("NVDA");
    await expect(
      dialog.getByText("当前持仓与收盘检查仅支持 A 股", { exact: true }),
    ).toBeVisible();
    await expect(
      page.locator(".ant-select-item-option-disabled"),
    ).toContainText("NVDA");
    await dialog.getByRole("combobox").fill("600000");
    await page
      .locator(".ant-select-item-option")
      .filter({ hasText: "示例股份" })
      .click();
    await dialog.getByLabel("持有股数", { exact: true }).fill("500");
    await dialog
      .getByLabel("每股成本（元）", { exact: true })
      .fill("10.123456");
    await dialog
      .getByLabel("买入理由", { exact: true })
      .fill("独立中线计划，演示数据");
    await fit();
    await page.screenshot({
      path: path.join(output, `IMPLEMENTED-portfolio-plan-${device}.png`),
      fullPage: false,
    });
    await dialog.getByRole("button", { name: "保存计划", exact: true }).click();
    await expect(page.locator(".holding-plan")).toHaveCount(4);
    await page
      .getByRole("button", { name: "编辑短线计划", exact: true })
      .click();
    const edit = page.getByRole("dialog", { name: "编辑持仓计划" });
    await edit.getByLabel("下观察线（可选）", { exact: true }).fill("9");
    await edit.getByRole("button", { name: "保存计划", exact: true }).click();
    await expect(page.getByText("计划已修改，结果待更新")).toBeVisible();
    await page
      .getByRole("button", { name: "关闭中线计划", exact: true })
      .first()
      .click();
    await page
      .getByRole("dialog", { name: "关闭持仓计划" })
      .getByRole("button", { name: /确认关闭/ })
      .click();
    await expect(page.locator(".holding-plan")).toHaveCount(3);
    await page.getByRole("button", { name: /检查收盘/ }).click();
    await expect(page.getByText("部分数据缺失", { exact: true })).toBeVisible();
    await page.goto(`${base}/watchlist`);
    await expect(page.getByText("等待业绩预告与估值变化")).toBeVisible();
    await fit();
    await page.screenshot({
      path: path.join(output, `IMPLEMENTED-portfolio-watchlist-${device}.png`),
      fullPage: true,
    });
    await page
      .getByRole("button", { name: /添加自选/ })
      .first()
      .click();
    const watch = page.getByRole("dialog", { name: "添加自选股" });
    await watch.getByRole("combobox").fill("600000");
    await page
      .locator(".ant-select-item-option")
      .filter({ hasText: "示例股份" })
      .click();
    await watch.getByLabel("关注理由").fill("新加入的演示关注理由");
    await watch.getByRole("button", { name: /^保\s*存$/ }).click();
    await expect(
      page.locator("#main").getByText("新加入的演示关注理由"),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "建立持仓计划", exact: true })
      .first()
      .click();
    await expect(
      page.getByRole("dialog", { name: "新增持仓计划" }).getByRole("combobox"),
    ).toHaveValue("观察股份 · 000001.SZ");
    await page
      .getByRole("dialog", { name: "新增持仓计划" })
      .getByRole("button", { name: /^取\s*消$/ })
      .click();
    await page
      .getByRole("button", { name: /发起研究/ })
      .first()
      .click();
    await expect(page.getByLabel("股票 / 资产代码")).toHaveValue("000001.SZ");
    await expect(page.getByLabel("分析日期")).toHaveValue(date);
    await expect(
      page.getByText(
        "通用单股研究，未结合你的持仓条件。请确认分析日期与参数。",
        { exact: true },
      ),
    ).toBeVisible();
    await fit();
    expect(errors).toEqual([]);
    console.log(
      `${device}: portfolio CRUD, non-A-share rejection, partial checks, prefill and layout passed`,
    );
    await context.close();
  }
} catch (error) {
  console.error(error.message);
  console.log(
    await lastPage
      ?.locator(".ant-modal, .ant-select-dropdown")
      .evaluateAll((els) =>
        els.map((el) => ({
          text: el.textContent.slice(0, 100),
          className: el.className,
          display: getComputedStyle(el).display,
          visibility: getComputedStyle(el).visibility,
          opacity: getComputedStyle(el).opacity,
          rect: JSON.stringify(el.getBoundingClientRect().toJSON()),
        })),
      ),
  );
  console.log(
    await lastPage?.locator('[role="combobox"]').evaluateAll((els) =>
      els.map((el) => ({
        expanded: el.getAttribute("aria-expanded"),
        focused: document.activeElement === el,
      })),
    ),
  );
  console.log(
    await lastPage?.locator(".ant-select").evaluateAll((els) =>
      els.map((el) => ({
        rect: el.getBoundingClientRect().toJSON(),
        height: getComputedStyle(el).height,
        offsetParent: !!el.offsetParent,
      })),
    ),
  );
  await lastPage?.screenshot({
    path: "/tmp/portfolio-acceptance-failure.png",
    fullPage: true,
  });
  throw error;
} finally {
  await browser?.close();
  await server.close();
}
