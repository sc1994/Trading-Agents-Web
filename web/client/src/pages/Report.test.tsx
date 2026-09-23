import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Report } from "./Report";
import { fakeApi, navigate, resetApi, task } from "../test/fixtures";

beforeEach(resetApi);

it.each([
  ["Buy", "买入"],
  ["Overweight", "增持"],
  ["Hold", "持有"],
  ["Underweight", "减持"],
  ["Sell", "卖出"],
  ["REVIEW", "需复核"],
] as const)(
  "renders canonical %s without reinterpreting sanitized Markdown",
  async (rating, label) => {
    vi.mocked(fakeApi.getTask).mockResolvedValue({
      ...task,
      status: "completed",
      rating,
    });
    vi.mocked(fakeApi.getReport).mockResolvedValue({
      task_id: task.id,
      sections: { decision: "**Rating**: [REDACTED]" },
      decision: { rating },
    });
    render(<Report api={fakeApi} taskId={task.id} navigate={navigate} />);
    expect(await screen.findByText(label)).toBeInTheDocument();
    if (rating !== "Hold")
      expect(screen.queryByText("持有")).not.toBeInTheDocument();
    expect(screen.queryByText(/信号强度|置信度/)).not.toBeInTheDocument();
    expect(screen.queryByText("价格目标")).not.toBeInTheDocument();
  },
);

it("renders source fields safely, exports Markdown and creates a new task with original parameters", async () => {
  vi.mocked(fakeApi.getReport).mockResolvedValue({
    task_id: task.id,
    sections: {
      decision: "真实依据<script>unsafe()</script>",
      conservative_history: "估值回落风险",
    },
    decision: {
      rating: "Buy",
      executive_summary: "收入增长",
      price_target: "$150",
    },
  });
  const { container } = render(
    <Report api={fakeApi} taskId={task.id} navigate={navigate} />,
  );
  expect(await screen.findByText("收入增长")).toBeInTheDocument();
  expect(screen.getByText("$150")).toBeInTheDocument();
  expect(container.querySelector("script")).toBeNull();
  expect(screen.getByRole("link", { name: "导出 Markdown" })).toHaveAttribute(
    "href",
    "/api/tasks/task-123/report.md",
  );
  fireEvent.click(screen.getByRole("button", { name: "复制参数再次分析" }));
  await waitFor(() =>
    expect(fakeApi.rerunTask).toHaveBeenCalledWith("task-123"),
  );
  expect(navigate).toHaveBeenCalledWith("/tasks/task-123");
});

it("marks absent source fields as unavailable and can retry failed report loading", async () => {
  vi.mocked(fakeApi.getReport).mockRejectedValueOnce(new Error("offline"));
  render(<Report api={fakeApi} taskId={task.id} navigate={navigate} />);
  fireEvent.click(await screen.findByRole("button", { name: /重\s*试/ }));
  expect(await screen.findByText("暂无报告章节")).toBeInTheDocument();
  expect(screen.getAllByText("未提供").length).toBeGreaterThan(0);
});
