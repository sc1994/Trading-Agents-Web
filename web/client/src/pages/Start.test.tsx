import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Start } from "./Start";
import { fakeApi, navigate, resetApi, settings } from "../test/fixtures";

beforeEach(resetApi);

it("submits selected symbol instead of the English search name, preserving server defaults", async () => {
  render(<Start api={fakeApi} navigate={navigate} />);
  await userEvent.type(
    await screen.findByLabelText("股票 / 资产代码"),
    "NVIDIA",
  );
  await userEvent.click(await screen.findByText("NVDA"));
  await userEvent.click(screen.getByRole("button", { name: "开始分析" }));
  await waitFor(() =>
    expect(fakeApi.createTask).toHaveBeenCalledWith(
      expect.objectContaining({
        ticker: "NVDA",
        name: "NVIDIA Corporation",
        language: "简体中文",
        quick_model: "gpt-5.6-luna",
        deep_model: "gpt-5.6",
      }),
    ),
  );
  expect(navigate).toHaveBeenCalledWith("/tasks/task-123");
});

it("searches a Chinese name and submits the selected market symbol", async () => {
  vi.mocked(fakeApi.searchSymbols).mockResolvedValue({
    results: [{ symbol: "0780.HK", name: "同程旅行", exchange: "HKEX", type: "EQUITY" }],
    unavailable: false,
  });
  render(<Start api={fakeApi} navigate={navigate} />);
  const input = await screen.findByLabelText("股票 / 资产代码");
  expect(screen.getByText(/输入代码或公司名称/)).toBeInTheDocument();
  await userEvent.type(input, "同程");
  await userEvent.click(await screen.findByText("同程旅行"));
  await userEvent.click(screen.getByRole("button", { name: "开始分析" }));
  await waitFor(() => expect(fakeApi.createTask).toHaveBeenCalledWith(
    expect.objectContaining({ ticker: "0780.HK", name: "同程旅行" }),
  ));
});

it("debounces queries of at least two characters and aborts an obsolete request", async () => {
  vi.useFakeTimers();
  try {
    render(<Start api={fakeApi} navigate={navigate} />);
    await act(async () => {});
    const input = screen.getByLabelText("股票 / 资产代码");
    fireEvent.change(input, { target: { value: "N" } });
    await act(async () => {
      vi.advanceTimersByTime(350);
    });
    expect(fakeApi.searchSymbols).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "NV" } });
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    fireEvent.change(input, { target: { value: "NVD" } });
    await act(async () => {
      vi.advanceTimersByTime(299);
    });
    expect(fakeApi.searchSymbols).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(fakeApi.searchSymbols).toHaveBeenCalledTimes(1);
    expect(fakeApi.searchSymbols).toHaveBeenCalledWith(
      "NVD",
      expect.any(AbortSignal),
    );
    const signal = vi.mocked(fakeApi.searchSymbols).mock.calls[0][1]!;
    await act(async () => {
      fireEvent.change(input, { target: { value: "AAPL" } });
    });
    expect(signal.aborted).toBe(true);
  } finally {
    vi.useRealTimers();
  }
});

it("allows a manually entered valid ticker when search is unavailable", async () => {
  vi.mocked(fakeApi.searchSymbols).mockResolvedValue({
    results: [],
    unavailable: true,
  });
  render(<Start api={fakeApi} navigate={navigate} />);
  await userEvent.type(
    await screen.findByLabelText("股票 / 资产代码"),
    "0700.hk",
  );
  expect(await screen.findByText(/搜索暂不可用/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "开始分析" }));
  await waitFor(() =>
    expect(fakeApi.createTask).toHaveBeenCalledWith(
      expect.objectContaining({ ticker: "0700.HK" }),
    ),
  );
});

it.each([
  { state: "unavailable", unavailable: true, status: /搜索暂不可用/ },
  { state: "empty", unavailable: false, status: /未找到结果/ },
])(
  "requires manual confirmation for an unselected company-like query after $state search",
  async ({ unavailable, status }) => {
    vi.mocked(fakeApi.searchSymbols).mockResolvedValue({
      results: [],
      unavailable,
    });
    render(<Start api={fakeApi} navigate={navigate} />);
    fireEvent.change(await screen.findByLabelText("股票 / 资产代码"), {
      target: { value: "NVIDIA" },
    });
    await screen.findByText(status);
    await userEvent.click(screen.getByRole("button", { name: "开始分析" }));
    expect(
      await screen.findByText(/请选择搜索结果或确认按代码手动输入/),
    ).toBeInTheDocument();
    expect(fakeApi.createTask).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("checkbox", { name: "将「NVIDIA」作为代码手动输入" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "开始分析" }));
    await waitFor(() =>
      expect(fakeApi.createTask).toHaveBeenCalledWith(
        expect.objectContaining({ ticker: "NVIDIA", name: "" }),
      ),
    );
  },
);

it.each(["2026-01-15", "2024-02-29"])(
  "accepts the valid calendar date %s without timezone shifts",
  async (date) => {
    render(<Start api={fakeApi} navigate={navigate} />);
    fireEvent.change(await screen.findByLabelText("股票 / 资产代码"), {
      target: { value: "F" },
    });
    fireEvent.change(screen.getByLabelText("分析日期"), {
      target: { value: date },
    });
    await userEvent.click(screen.getByRole("button", { name: "开始分析" }));
    await waitFor(() =>
      expect(fakeApi.createTask).toHaveBeenCalledWith(
        expect.objectContaining({ ticker: "F", date }),
      ),
    );
  },
);

it("rejects unselected company names instead of treating them as ticker symbols", async () => {
  render(<Start api={fakeApi} navigate={navigate} />);
  fireEvent.change(await screen.findByLabelText("股票 / 资产代码"), {
    target: { value: "NVIDIA Corporation" },
  });
  await userEvent.click(screen.getByRole("button", { name: "开始分析" }));
  expect(
    await screen.findByText(/请选择搜索结果或输入有效代码/),
  ).toBeInTheDocument();
  expect(fakeApi.createTask).not.toHaveBeenCalled();
});

it("requires a missing provider key before creating a task", async () => {
  vi.mocked(fakeApi.getSettings).mockResolvedValue({
    ...settings,
    keys: { openai: { configured: false, last4: null } },
  });
  render(<Start api={fakeApi} navigate={navigate} />);
  await userEvent.type(await screen.findByLabelText("股票 / 资产代码"), "F");
  await userEvent.click(screen.getByRole("button", { name: "开始分析" }));
  expect(
    await screen.findByText(/请先在设置中配置 OpenAI/),
  ).toBeInTheDocument();
  expect(fakeApi.createTask).not.toHaveBeenCalled();
});

it("offers a retry when defaults fail to load", async () => {
  vi.mocked(fakeApi.getSettings).mockRejectedValueOnce(new Error("offline"));
  render(<Start api={fakeApi} navigate={navigate} />);
  await userEvent.click(await screen.findByRole("button", { name: "重试" }));
  expect(await screen.findByLabelText("股票 / 资产代码")).toBeInTheDocument();
  expect(fakeApi.getSettings).toHaveBeenCalledTimes(2);
});

it("does not send a company name while its search is still pending", async () => {
  vi.mocked(fakeApi.searchSymbols).mockReturnValue(new Promise(() => {}));
  render(<Start api={fakeApi} navigate={navigate} />);
  fireEvent.change(await screen.findByLabelText("股票 / 资产代码"), {
    target: { value: "NVIDIA" },
  });
  await userEvent.click(screen.getByRole("button", { name: "开始分析" }));
  await waitFor(() =>
    expect(
      screen.getByText(/请等待搜索或确认按代码手动输入/),
    ).toBeInTheDocument(),
  );
  expect(fakeApi.createTask).not.toHaveBeenCalled();
});

it("keeps late search results from replacing a newer query", async () => {
  let resolveOld!: (
    response: Awaited<ReturnType<typeof fakeApi.searchSymbols>>,
  ) => void;
  vi.mocked(fakeApi.searchSymbols).mockReturnValueOnce(
    new Promise((resolve) => {
      resolveOld = resolve;
    }),
  );
  vi.mocked(fakeApi.searchSymbols).mockResolvedValueOnce({
    results: [
      {
        symbol: "AAPL",
        name: "Apple Inc.",
        exchange: "NASDAQ",
        type: "EQUITY",
      },
    ],
    unavailable: false,
  });
  render(<Start api={fakeApi} navigate={navigate} />);
  const input = await screen.findByLabelText("股票 / 资产代码");
  await userEvent.click(input);
  fireEvent.change(input, { target: { value: "NVIDIA" } });
  await waitFor(() => expect(fakeApi.searchSymbols).toHaveBeenCalledTimes(1));
  fireEvent.change(input, { target: { value: "Apple" } });
  expect(await screen.findByText("AAPL")).toBeInTheDocument();
  await act(async () => {
    resolveOld({
      results: [
        {
          symbol: "NVDA",
          name: "NVIDIA Corporation",
          exchange: "NASDAQ",
          type: "EQUITY",
        },
      ],
      unavailable: false,
    });
  });
  expect(screen.queryByText("NVDA")).not.toBeInTheDocument();
  expect(screen.getByText("AAPL")).toBeInTheDocument();
});

it("omits a cleared round override so the selected depth supplies its default", async () => {
  render(<Start api={fakeApi} navigate={navigate} />);
  fireEvent.change(await screen.findByLabelText("股票 / 资产代码"), {
    target: { value: "F" },
  });
  await userEvent.click(screen.getByText("高级设置"));
  const rounds = screen.getByLabelText("研究辩论轮次");
  fireEvent.change(rounds, { target: { value: "4" } });
  fireEvent.change(rounds, { target: { value: "" } });
  await userEvent.click(screen.getByRole("button", { name: "开始分析" }));
  await waitFor(() => expect(fakeApi.createTask).toHaveBeenCalled());
  expect(
    vi.mocked(fakeApi.createTask).mock.calls[0][0].max_debate_rounds,
  ).toBeUndefined();
});

it("rejects future dates with field feedback before creating a task", async () => {
  render(<Start api={fakeApi} navigate={navigate} />);
  fireEvent.change(await screen.findByLabelText("股票 / 资产代码"), {
    target: { value: "F" },
  });
  fireEvent.change(screen.getByLabelText("分析日期"), {
    target: { value: "2099-01-01" },
  });
  await userEvent.click(screen.getByRole("button", { name: "开始分析" }));
  expect(
    await screen.findByText("请选择不晚于今天的有效日期"),
  ).toBeInTheDocument();
  expect(fakeApi.createTask).not.toHaveBeenCalled();
});
