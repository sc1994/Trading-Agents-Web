import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { History } from "./History";
import { fakeApi, navigate, resetApi, task } from "../test/fixtures";

beforeEach(resetApi);

const reports = [
  {
    ...task,
    id: "older",
    status: "completed" as const,
    rating: "Underweight" as const,
  },
  {
    ...task,
    id: "latest",
    status: "completed" as const,
    rating: "Hold" as const,
    created_at: "2026-09-22T09:00:00Z",
    finished_at: "2026-09-22T09:15:00Z",
  },
];

it("groups reports by symbol and opens the latest report regardless of input order", async () => {
  vi.mocked(fakeApi.listTasks).mockResolvedValue({ tasks: reports });
  render(<History api={fakeApi} navigate={navigate} reportsOnly />);
  fireEvent.click(await screen.findByRole("button", { name: "查看最新" }));
  expect(navigate).toHaveBeenCalledWith("/reports/latest");
  expect(screen.getAllByText("NVDA")).toHaveLength(1);
  expect(screen.getByText("减持 → 持有")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "删除 NVDA" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "NVDA 的 2 份报告" }));
  const viewButtons = screen.getAllByRole("button", { name: "查看报告" });
  fireEvent.click(viewButtons[1]);
  expect(navigate).toHaveBeenLastCalledWith("/reports/older");
  fireEvent.click(screen.getAllByRole("button", { name: /删除 NVDA/ })[1]);
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(fakeApi.deleteTask).toHaveBeenCalledWith("older"));
});

it("filters by the latest rating without losing older reports or showing outdated matches", async () => {
  vi.mocked(fakeApi.listTasks).mockResolvedValue({ tasks: reports });
  render(<History api={fakeApi} navigate={navigate} reportsOnly />);
  await screen.findByText("NVDA");
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "评级筛选" }));
  fireEvent.click(
    await screen.findByText("持有", {
      selector: ".ant-select-item-option-content",
    }),
  );
  expect(
    await screen.findByRole("button", { name: "NVDA 的 2 份报告" }),
  ).toBeInTheDocument();
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "评级筛选" }));
  fireEvent.click(
    await screen.findByText("减持", {
      selector: ".ant-select-item-option-content",
    }),
  );
  expect(await screen.findByText("暂无匹配的报告")).toBeInTheDocument();
  expect(fakeApi.listTasks).toHaveBeenLastCalledWith({
    q: "",
    status: "completed",
    rating: undefined,
  });
});

it("keeps different symbols separate and task history ungrouped", async () => {
  vi.mocked(fakeApi.listTasks).mockResolvedValue({
    tasks: [...reports, { ...reports[0], id: "hk", ticker: "0780.HK" }],
  });
  const { rerender } = render(
    <History api={fakeApi} navigate={navigate} reportsOnly />,
  );
  expect(await screen.findByText("0780.HK")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "查看最新" })).toHaveLength(2);
  rerender(<History api={fakeApi} navigate={navigate} />);
  await waitFor(() =>
    expect(screen.getAllByRole("button", { name: "查看报告" })).toHaveLength(3),
  );
});

it("searches complete groups when saved names differ between reports", async () => {
  vi.mocked(fakeApi.listTasks).mockImplementation(async (filters) => ({
    tasks: [...reports.slice(0, 1), { ...reports[1], name: "" }].filter(
      (report) => !filters.q || report.name.includes(filters.q),
    ),
  }));
  render(<History api={fakeApi} navigate={navigate} reportsOnly />);
  await screen.findByRole("button", { name: "查看最新" });
  fireEvent.change(screen.getByLabelText("代码或英文名称"), {
    target: { value: "NVIDIA" },
  });
  await waitFor(() => expect(fakeApi.listTasks).toHaveBeenCalledTimes(2));
  await waitFor(() =>
    expect(fakeApi.listTasks).toHaveBeenLastCalledWith({
      q: "",
      status: "completed",
      rating: undefined,
    }),
  );
  expect(
    screen.getByRole("button", { name: "NVDA 的 2 份报告" }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "查看最新" }));
  expect(navigate).toHaveBeenCalledWith("/reports/latest");
  fireEvent.change(screen.getByLabelText("代码或英文名称"), {
    target: { value: "missing" },
  });
  expect(await screen.findByText("暂无匹配的报告")).toBeInTheDocument();
});

it("passes symbol, status and canonical rating filters to the API", async () => {
  render(<History api={fakeApi} navigate={navigate} />);
  fireEvent.change(screen.getByLabelText("代码或英文名称"), {
    target: { value: "Apple" },
  });
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "状态筛选" }));
  fireEvent.click(
    await screen.findByText("已完成", {
      selector: ".ant-select-item-option-content",
    }),
  );
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "评级筛选" }));
  fireEvent.click(
    await screen.findByText("需复核", {
      selector: ".ant-select-item-option-content",
    }),
  );
  await waitFor(() =>
    expect(fakeApi.listTasks).toHaveBeenLastCalledWith({
      q: "Apple",
      status: "completed",
      rating: "REVIEW",
    }),
  );
});

it("requires confirmation before deleting and removes only the selected task", async () => {
  vi.mocked(fakeApi.listTasks).mockResolvedValue({
    tasks: [{ ...task, status: "failed" }],
  });
  render(<History api={fakeApi} navigate={navigate} />);
  await userEvent.click(
    await screen.findByRole("button", { name: "删除 NVDA" }),
  );
  expect(fakeApi.deleteTask).not.toHaveBeenCalled();
  vi.mocked(fakeApi.listTasks).mockResolvedValue({ tasks: [] });
  await userEvent.click(
    await screen.findByRole("button", { name: "确认删除" }),
  );
  await waitFor(() =>
    expect(fakeApi.deleteTask).toHaveBeenCalledWith("task-123"),
  );
  expect(await screen.findByText("暂无匹配的任务")).toBeInTheDocument();
});

it("exposes resume only when available and preserves rerun for an interrupted task", async () => {
  vi.mocked(fakeApi.listTasks).mockResolvedValue({
    tasks: [{ ...task, status: "interrupted", can_resume: true }],
  });
  render(<History api={fakeApi} navigate={navigate} />);
  fireEvent.click(await screen.findByRole("button", { name: "继续运行" }));
  await waitFor(() =>
    expect(fakeApi.resumeTask).toHaveBeenCalledWith("task-123"),
  );
  expect(navigate).toHaveBeenCalledWith("/tasks/task-123");
  fireEvent.click(screen.getByRole("button", { name: "再次分析" }));
  await waitFor(() =>
    expect(fakeApi.rerunTask).toHaveBeenCalledWith("task-123"),
  );
});

it("hides delete and resume for running tasks and lets users retry list failures", async () => {
  vi.mocked(fakeApi.listTasks)
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue({ tasks: [{ ...task, status: "running" }] });
  render(<History api={fakeApi} navigate={navigate} />);
  fireEvent.click(await screen.findByRole("button", { name: /重\s*试/ }));
  expect(
    await screen.findByRole("button", { name: "查看进度" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "删除 NVDA" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "继续运行" }),
  ).not.toBeInTheDocument();
});
