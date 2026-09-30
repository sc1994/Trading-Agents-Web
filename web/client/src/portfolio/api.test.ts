import { portfolioApi, PortfolioError } from "./api";

afterEach(() => vi.unstubAllGlobals());
it("sends portfolio decimal strings without modifying them", async () => {
  let sent: RequestInit | undefined;
  vi.stubGlobal("fetch", async (_path: string, init: RequestInit) => {
    sent = init;
    return new Response(JSON.stringify({ id: "p1" }), { status: 201 });
  });
  await portfolioApi.createPlan({
    symbol: "600000.SS",
    horizon: "short",
    shares: 1000,
    cost: "10.123456",
    reason: "fixture",
    lower: null,
    upper: null,
    review_date: null,
    cost_pending: false,
  });
  expect(JSON.parse(String(sent?.body)).cost).toBe("10.123456");
  expect(sent?.credentials).toBe("same-origin");
});
it("exposes fixed business errors instead of upstream text", async () => {
  vi.stubGlobal(
    "fetch",
    async () =>
      new Response(
        JSON.stringify({
          detail: {
            code: "unsupported_market",
            field: "symbol",
            debug: "upstream-private",
          },
        }),
        { status: 422 },
      ),
  );
  const failure = await portfolioApi
    .addWatch("NVDA", "")
    .catch((error: unknown) => error);
  expect(failure).toBeInstanceOf(PortfolioError);
  expect((failure as Error).message).toBe("当前持仓与收盘检查仅支持 A 股");
});
