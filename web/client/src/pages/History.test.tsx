import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { History } from "./History";
import { fakeApi, navigate, resetApi, task } from "../test/fixtures";

beforeEach(resetApi);

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
