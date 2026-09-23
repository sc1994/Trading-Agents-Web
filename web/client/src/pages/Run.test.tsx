import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Run } from "./Run";
import { fakeApi, navigate, resetApi, task } from "../test/fixtures";
import type { TaskSubscription } from "../api";

beforeEach(resetApi);

it("refreshes durable stage sections, ignores duplicate events and reconnects with the last cursor", async () => {
  const handlers: TaskSubscription[] = [];
  vi.mocked(fakeApi.subscribeTask).mockImplementation(
    (_id, _cursor, handler) => {
      handlers.push(handler);
      return vi.fn();
    },
  );
  render(<Run api={fakeApi} taskId={task.id} navigate={navigate} />);
  await waitFor(() => expect(handlers).toHaveLength(1));
  vi.mocked(fakeApi.getTask).mockResolvedValue({
    ...task,
    status: "running",
    sections: { market_report: "市场报告已产出" },
  });
  await act(async () => handlers[0].onEvent({ id: 4, type: "section" }));
  expect(await screen.findByText("市场报告已产出")).toBeInTheDocument();
  const calls = vi.mocked(fakeApi.getTask).mock.calls.length;
  await act(async () => handlers[0].onEvent({ id: 3, type: "section" }));
  expect(fakeApi.getTask).toHaveBeenCalledTimes(calls);
  await act(async () => handlers[0].onError());
  expect(await screen.findByText(/连接已断开/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "重新连接" }));
  await waitFor(() =>
    expect(fakeApi.subscribeTask).toHaveBeenLastCalledWith(
      task.id,
      4,
      expect.any(Object),
    ),
  );
  expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  expect(screen.queryByText(/当前节点：/)).not.toBeInTheDocument();
});

it("recovers terminal state from a snapshot after disconnect and closes the subscription", async () => {
  let handler!: TaskSubscription;
  const close = vi.fn();
  vi.mocked(fakeApi.subscribeTask).mockImplementation((_id, _cursor, value) => {
    handler = value;
    return close;
  });
  render(<Run api={fakeApi} taskId={task.id} navigate={navigate} />);
  await waitFor(() => expect(handler).toBeDefined());
  vi.mocked(fakeApi.getTask).mockResolvedValue({
    ...task,
    status: "completed",
    rating: "Buy",
  });
  await act(async () => handler.onError());
  expect(
    await screen.findByRole("button", { name: "查看报告" }),
  ).toBeInTheDocument();
  expect(close).toHaveBeenCalled();
});

it("shows an actionable retry after snapshot loading fails", async () => {
  vi.mocked(fakeApi.getTask).mockRejectedValueOnce(new Error("offline"));
  render(<Run api={fakeApi} taskId={task.id} navigate={navigate} />);
  fireEvent.click(await screen.findByRole("button", { name: /重\s*试/ }));
  expect(await screen.findByText("NVDA 任务运行")).toBeInTheDocument();
});
