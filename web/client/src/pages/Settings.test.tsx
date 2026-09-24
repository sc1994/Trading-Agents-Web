import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";
import { Settings } from "./Settings";
import { customProviderId, fakeApi, resetApi, settings } from "../test/fixtures";

beforeEach(resetApi);

function renderSettings() {
  return render(
    <ConfigProvider virtual={false}>
      <Settings api={fakeApi} />
    </ConfigProvider>,
  );
}

async function joinedList() {
  return screen.findByRole("list", { name: "已加入的供应商" });
}

it("lists joined suppliers without a wall of credential inputs", async () => {
  renderSettings();
  const list = await joinedList();
  expect(within(list).getByText("OpenAI")).toBeInTheDocument();
  expect(within(list).getByText("本地推理")).toBeInTheDocument();
  expect(screen.queryByLabelText("OpenAI API Key")).not.toBeInTheDocument();
  expect(within(list).getByText(/已配置 · 尾号 abcd/)).toBeInTheDocument();
  expect(within(list).getByText("http://localhost:1234/v1")).toBeInTheDocument();
});

it("opens the join dialog and switches between supplier kinds", async () => {
  renderSettings();
  await userEvent.click(await screen.findByRole("button", { name: "加入供应商" }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("类型"));
  expect(await screen.findByText("内置供应商")).toBeInTheDocument();
  await userEvent.click(screen.getByText("内置供应商"));
  expect(screen.getByLabelText("选择内置供应商")).toBeInTheDocument();
});

it("joins a custom supplier with its saved key", async () => {
  renderSettings();
  await userEvent.click(await screen.findByRole("button", { name: "加入供应商" }));
  await userEvent.type(await screen.findByLabelText("名称"), "云网关");
  await userEvent.type(screen.getByLabelText("接口地址"), "https://gateway.example/v1");
  await userEvent.type(screen.getByLabelText("API Key"), "secret-12345");
  await userEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() =>
    expect(fakeApi.addProvider).toHaveBeenCalledWith({
      kind: "custom",
      name: "云网关",
      base_url: "https://gateway.example/v1",
      key: "secret-12345",
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(await screen.findByText("供应商已加入")).toBeInTheDocument();
});

it("joins an unjoined built-in supplier by identifier", async () => {
  renderSettings();
  await userEvent.click(await screen.findByRole("button", { name: "加入供应商" }));
  await userEvent.click(screen.getByLabelText("类型"));
  await userEvent.click(await screen.findByText("内置供应商"));
  await userEvent.click(screen.getByLabelText("选择内置供应商"));
  await userEvent.click(await screen.findByText("Anthropic"));
  await userEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() =>
    expect(fakeApi.addProvider).toHaveBeenCalledWith({
      kind: "built_in",
      id: "anthropic",
    }),
  );
});

it("replaces a joined key through the edit dialog without keeping it locally", async () => {
  const localSpy = vi.spyOn(Storage.prototype, "setItem");
  renderSettings();
  await userEvent.click(await screen.findByRole("button", { name: "编辑 OpenAI" }));
  const input = await screen.findByLabelText("OpenAI API Key");
  expect(input).toHaveAttribute("type", "password");
  expect(input).toHaveValue("");
  await userEvent.type(input, "replacement-secret");
  await userEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() =>
    expect(fakeApi.editProvider).toHaveBeenCalledWith("openai", {
      key: "replacement-secret",
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(localSpy).not.toHaveBeenCalled();
});

it("keeps the existing key when the edit key is left blank", async () => {
  renderSettings();
  await userEvent.click(await screen.findByRole("button", { name: "编辑 OpenAI" }));
  await userEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() =>
    expect(fakeApi.editProvider).toHaveBeenCalledWith("openai", {}),
  );
});

it("clears a joined key through the dialog and reports an ambient key", async () => {
  vi.mocked(fakeApi.editProvider).mockResolvedValue({
    ...structuredClone(settings),
    providers: settings.providers.map((provider) =>
      provider.id === "openai"
        ? { ...provider, key: { configured: true, last4: null } }
        : provider,
    ),
  });
  renderSettings();
  await userEvent.click(await screen.findByRole("button", { name: "编辑 OpenAI" }));
  await userEvent.click(screen.getByRole("button", { name: "清除 OpenAI 密钥" }));
  await userEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() =>
    expect(fakeApi.editProvider).toHaveBeenCalledWith("openai", {
      clear_key: true,
    }),
  );
  expect(await screen.findByText(/服务器仍提供 OpenAI 密钥/)).toBeInTheDocument();
});

it("edits a custom supplier name and URL", async () => {
  renderSettings();
  await userEvent.click(
    await screen.findByRole("button", { name: "编辑 本地推理" }),
  );
  const name = await screen.findByLabelText("名称");
  await userEvent.clear(name);
  await userEvent.type(name, "本地网关");
  const url = screen.getByLabelText("接口地址");
  await userEvent.clear(url);
  await userEvent.type(url, "http://127.0.0.1:1235/v1");
  await userEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() =>
    expect(fakeApi.editProvider).toHaveBeenCalledWith(customProviderId, {
      name: "本地网关",
      base_url: "http://127.0.0.1:1235/v1",
    }),
  );
});

it("requires confirmation before removing a supplier", async () => {
  renderSettings();
  await userEvent.click(await screen.findByRole("button", { name: "删除 OpenAI" }));
  expect(fakeApi.removeProvider).not.toHaveBeenCalled();
  await userEvent.click(await screen.findByText("确定删除"));
  await waitFor(() =>
    expect(fakeApi.removeProvider).toHaveBeenCalledWith("openai"),
  );
});

it("reports a removal failure without dropping the list", async () => {
  vi.mocked(fakeApi.removeProvider).mockRejectedValue(new Error("request failed"));
  renderSettings();
  await userEvent.click(await screen.findByRole("button", { name: "删除 OpenAI" }));
  await userEvent.click(await screen.findByText("确定删除"));
  expect(await screen.findByText(/删除失败/)).toBeInTheDocument();
  const list = await joinedList();
  expect(within(list).getByText("本地推理")).toBeInTheDocument();
});

it("keeps dialog values when saving a supplier fails", async () => {
  vi.mocked(fakeApi.editProvider).mockRejectedValue(new Error("request failed"));
  renderSettings();
  await userEvent.click(await screen.findByRole("button", { name: "编辑 OpenAI" }));
  const input = await screen.findByLabelText("OpenAI API Key");
  await userEvent.type(input, "new-key");
  await userEvent.click(screen.getByRole("button", { name: "保存" }));
  expect(await screen.findByText(/保存失败/)).toBeInTheDocument();
  expect(input).toHaveValue("new-key");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
});

it("offers only joined suppliers as the default", async () => {
  renderSettings();
  await userEvent.click(await screen.findByRole("tab", { name: "默认模型" }));
  await userEvent.click(await screen.findByLabelText("默认供应商"));
  const dropdown = await screen.findByRole("listbox");
  expect(within(dropdown).getByText("OpenAI")).toBeInTheDocument();
  expect(within(dropdown).getByText("本地推理")).toBeInTheDocument();
  expect(within(dropdown).queryByText("Anthropic")).not.toBeInTheDocument();
});

it("tests a saved supplier only after an explicit action", async () => {
  renderSettings();
  await joinedList();
  expect(fakeApi.testConnection).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "测试 OpenAI 连接" }));
  await waitFor(() =>
    expect(fakeApi.testConnection).toHaveBeenCalledWith("openai"),
  );
  expect(await screen.findByText("OpenAI 连接成功")).toBeInTheDocument();
});

it("omits blank keys and cleared data-source keys on save", async () => {
  renderSettings();
  await userEvent.click(await screen.findByRole("tab", { name: "数据源" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "清除 Alpha Vantage 密钥" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "保存设置" }));
  await waitFor(() =>
    expect(fakeApi.saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({ keys: {}, clear_keys: ["alpha_vantage"] }),
    ),
  );
});

it("keeps data-source edits available when saving settings fails", async () => {
  vi.mocked(fakeApi.saveSettings).mockRejectedValue(new Error("request failed"));
  renderSettings();
  await userEvent.click(await screen.findByRole("tab", { name: "数据源" }));
  const input = await screen.findByLabelText("FRED API Key");
  await userEvent.type(input, "new-key");
  await userEvent.click(screen.getByRole("button", { name: "保存设置" }));
  expect(await screen.findByText(/保存失败/)).toBeInTheDocument();
  expect(input).toHaveValue("new-key");
});
