import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Empty, Space, Spin } from "antd";
import type { TaskView, WebApi } from "../api";
import {
  groups,
  sectionLabel,
  Sections,
  Status,
} from "../components/TaskContent";

const terminal = (task: TaskView) =>
  !["queued", "running"].includes(task.status);
export function Run({
  api,
  taskId,
  navigate,
}: {
  api: WebApi;
  taskId: string;
  navigate: (path: string) => void;
}) {
  const [task, setTask] = useState<TaskView | null>(null);
  const [error, setError] = useState(false);
  const [disconnected, setDisconnected] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const cursor = useRef(0);
  const cursorTask = useRef(taskId);
  const refresh = useRef<() => void>(() => {});
  useEffect(() => {
    if (cursorTask.current !== taskId) {
      cursor.current = 0;
      cursorTask.current = taskId;
    }
    let disposed = false;
    let stopped = false;
    let close: (() => void) | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let loading = false;
    let pending = false;
    setTask(null);
    setError(false);
    const snapshot = async () => {
      if (loading) {
        pending = true;
        return;
      }
      loading = true;
      do {
        pending = false;
        try {
          const next = await api.getTask(taskId);
          if (disposed) return;
          setTask(next);
          setError(false);
          if (terminal(next)) {
            stopped = true;
            close?.();
            clearTimeout(retry);
            setDisconnected(false);
          }
        } catch {
          if (!disposed) setError(true);
        }
      } while (pending && !disposed);
      loading = false;
    };
    const connect = () => {
      if (disposed || stopped) return;
      close?.();
      close = api.subscribeTask(taskId, cursor.current, {
        onOpen: () => {
          if (!disposed) setDisconnected(false);
        },
        onEvent: (event) => {
          if (disposed || stopped || event.id <= cursor.current) return;
          cursor.current = event.id;
          void snapshot();
        },
        onError: () => {
          if (disposed || stopped) return;
          close?.();
          setDisconnected(true);
          void snapshot();
          clearTimeout(retry);
          retry = setTimeout(connect, 3000);
        },
      });
    };
    refresh.current = () => {
      clearTimeout(retry);
      void snapshot().then(connect);
    };
    void snapshot().then(connect);
    const poll = setInterval(() => {
      if (!stopped) void snapshot();
    }, 15000);
    return () => {
      disposed = true;
      close?.();
      clearTimeout(retry);
      clearInterval(poll);
    };
  }, [api, taskId, attempt]);
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>{task ? `${task.ticker} 任务运行` : "任务运行"}</h1>
          <p>已产出的报告可立即阅读，离开页面后任务继续运行。</p>
        </div>
        <Button onClick={() => navigate("/history")}>返回任务记录</Button>
      </div>
      {error && (
        <Alert
          className="form-alert"
          type="error"
          showIcon
          message="暂时无法读取任务，请稍后重试。"
          action={
            <Button
              onClick={() =>
                task ? refresh.current() : setAttempt((value) => value + 1)
              }
            >
              重试
            </Button>
          }
        />
      )}
      {!task && !error && <Spin aria-label="正在加载任务" />}
      {task && (
        <>
          {disconnected && (
            <Alert
              className="form-alert"
              type="warning"
              showIcon
              message="连接已断开，正在自动重连；仍会定期读取任务快照。"
              action={
                <Button onClick={() => refresh.current()}>重新连接</Button>
              }
            />
          )}
          {task.error && (
            <Alert
              className="form-alert"
              type="error"
              showIcon
              message={task.error}
            />
          )}
          <Card className="task-overview">
            <div className="task-identity">
              <div>
                <strong>
                  {task.ticker} · {task.name || task.ticker}
                </strong>
                <p className="muted">
                  {task.date} · {task.params.language || "语言未提供"}
                </p>
              </div>
              <Space wrap>
                <Status task={task} />
                {task.status === "completed" && (
                  <Button
                    type="primary"
                    onClick={() => navigate(`/reports/${task.id}`)}
                  >
                    查看报告
                  </Button>
                )}
              </Space>
            </div>
            <ol className="stage-track" aria-label="阶段产出">
              {groups.map((group) => {
                const count = group.sections.filter((key) =>
                  task.sections[key]?.trim(),
                ).length;
                return (
                  <li key={group.key} className={count ? "has-output" : ""}>
                    <span className="stage-dot" />
                    <strong>{group.label}</strong>
                    <small>{count ? `${count} 份产出` : "暂无产出"}</small>
                  </li>
                );
              })}
            </ol>
            {task.current_stage && (
              <p className="muted">当前阶段：{task.current_stage}</p>
            )}
            {task.current_node && (
              <p className="muted">当前节点：{task.current_node}</p>
            )}
          </Card>
          <div className="run-layout">
            <Card title="当前产出">
              <Sections sections={task.sections} />
            </Card>
            <Card title="已保存的产出">
              {Object.entries(task.sections).filter(([, text]) => text.trim())
                .length ? (
                <ul className="output-list">
                  {Object.entries(task.sections)
                    .filter(([, text]) => text.trim())
                    .map(([key]) => (
                      <li key={key}>
                        <span>{sectionLabel[key] || key}</span>
                        <span className="muted">已保存</span>
                      </li>
                    ))}
                </ul>
              ) : (
                <Empty
                  description={
                    task.status === "queued"
                      ? "任务排队中，等待开始分析。"
                      : "尚未产出报告"
                  }
                />
              )}
              <p className="muted">报告以服务端保存的内容为准。</p>
              {terminal(task) && task.status !== "completed" && (
                <Button onClick={() => navigate(`/reports/${task.id}`)}>
                  查看已有报告
                </Button>
              )}
            </Card>
          </div>
        </>
      )}
    </>
  );
}
