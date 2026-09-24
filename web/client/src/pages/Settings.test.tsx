import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";
import { Settings } from "./Settings";
import { fakeApi, resetApi, settings } from "../test/fixtures";

beforeEach(resetApi);

it("does not offer an unconfigured OpenAI compatible endpoint", async () => {
  render(<ConfigProvider virtual={false}><Settings api={fakeApi} /></ConfigProvider>);
  await userEvent.click(await screen.findByRole("tab", { name: "默认模型" }));
  await userEvent.click(await screen.findByLabelText("默认供应商"));
  expect(await screen.findByText("Anthropic")).toBeInTheDocument();
  expect(screen.queryByText("OpenAI 兼容服务")).not.toBeInTheDocument();
});

it("shows only masked key status and omits blank keys on save", async () => {
  render(<Settings api={fakeApi} />);
  const input = await screen.findByLabelText("OpenAI API Key");
  expect(input).toHaveAttribute("type", "password");
  expect(input).toHaveValue("");
  expect(screen.getByText(/已配置 · 尾号 abcd/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "保存设置" }));
  await waitFor(() =>
    expect(fakeApi.saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({ keys: {}, clear_keys: [] }),
    ),
  );
});

it("guides data source key setup to the official application pages", async () => {
  vi.mocked(fakeApi.getSettings).mockResolvedValue({
    ...structuredClone(settings),
    keys: {
      ...structuredClone(settings.keys),
      alpha_vantage: { configured: false, last4: null },
    },
  });
  render(<Settings api={fakeApi} />);
  await userEvent.click(await screen.findByRole("tab", { name: "数据源" }));

  const fred = screen.getByLabelText("FRED API Key").closest(".ant-form-item");
  const alpha = screen.getByLabelText("Alpha Vantage API Key").closest(".ant-form-item");
  expect(fred).toHaveTextContent("填入后点击“保存设置”");
  expect(alpha).toHaveTextContent("填入后点击“保存设置”");
  expect(fred?.querySelector("a")).toHaveAttribute(
    "href",
    "https://fred.stlouisfed.org/docs/api/api_key.html",
  );
  expect(alpha?.querySelector("a")).toHaveAttribute(
    "href",
    "https://www.alphavantage.co/support/#api-key",
  );
});

it("sends a replacement only to the server and blanks the password after save", async () => {
  const localSpy = vi.spyOn(Storage.prototype, "setItem");
  render(<Settings api={fakeApi} />);
  const input = await screen.findByLabelText("OpenAI API Key");
  await userEvent.type(input, "replacement-secret");
  await userEvent.click(screen.getByRole("button", { name: "保存设置" }));
  await waitFor(() =>
    expect(fakeApi.saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        keys: { openai: "replacement-secret" },
        clear_keys: [],
      }),
    ),
  );
  await waitFor(() => expect(input).toHaveValue(""));
  expect(localSpy).not.toHaveBeenCalled();
});

it("sends an explicit clear command only after the clear action and save", async () => {
  render(<Settings api={fakeApi} />);
  await userEvent.click(
    await screen.findByRole("button", { name: "清除 OpenAI 密钥" }),
  );
  expect(fakeApi.saveSettings).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "保存设置" }));
  await waitFor(() =>
    expect(fakeApi.saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({ keys: {}, clear_keys: ["openai"] }),
    ),
  );
  expect(
    await screen.findByText(/服务器仍提供 OpenAI 密钥/),
  ).toBeInTheDocument();
});

it("tests only the selected saved provider after explicit user action", async () => {
  render(<Settings api={fakeApi} />);
  await screen.findByLabelText("OpenAI API Key");
  expect(fakeApi.testConnection).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: "测试 OpenAI 连接" }),
  );
  await waitFor(() =>
    expect(fakeApi.testConnection).toHaveBeenCalledWith("openai"),
  );
  expect(await screen.findByText("OpenAI 连接成功")).toBeInTheDocument();
});

it.each(["FRED", "Alpha Vantage"])("tests the saved %s data source only on demand", async (label) => {
  render(<Settings api={fakeApi} />);
  await userEvent.click(await screen.findByRole("tab", { name: "数据源" }));
  expect(fakeApi.testConnection).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: `测试 ${label} 连接` }));
  await waitFor(() => expect(fakeApi.testConnection).toHaveBeenCalledWith(
    label === "FRED" ? "fred" : "alpha_vantage",
  ));
  expect(await screen.findByText(`${label} 连接成功`)).toBeInTheDocument();
});

it("requires saving a new data source key before testing it", async () => {
  render(<Settings api={fakeApi} />);
  await userEvent.click(await screen.findByRole("tab", { name: "数据源" }));
  await userEvent.type(screen.getByLabelText("FRED API Key"), "new-secret");
  expect(screen.getByRole("button", { name: "测试 FRED 连接" })).toBeDisabled();
  expect(fakeApi.testConnection).not.toHaveBeenCalled();
});

it("keeps edits available when save fails and displays a safe error", async () => {
  vi.mocked(fakeApi.saveSettings).mockRejectedValue(
    new Error("request failed"),
  );
  render(<Settings api={fakeApi} />);
  const input = await screen.findByLabelText("OpenAI API Key");
  await userEvent.type(input, "new-key");
  await userEvent.click(screen.getByRole("button", { name: "保存设置" }));
  expect(await screen.findByText(/保存失败/)).toBeInTheDocument();
  expect(input).toHaveValue("new-key");
});
