import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Select,
  Space,
  Spin,
} from "antd";
import type { TaskFilters, TaskView, WebApi } from "../api";
import { ratingLabel, Status, statusLabel } from "../components/TaskContent";

export function History({
  api,
  navigate,
  reportsOnly = false,
}: {
  api: WebApi;
  navigate: (path: string) => void;
  reportsOnly?: boolean;
}) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<TaskFilters["status"]>(
    reportsOnly ? "completed" : undefined,
  );
  const [rating, setRating] = useState<TaskFilters["rating"]>();
  const [tasks, setTasks] = useState<TaskView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [actionError, setActionError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [deleting, setDeleting] = useState<TaskView | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setStatus(reportsOnly ? "completed" : undefined);
  }, [reportsOnly]);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    const timer = setTimeout(() => {
      api
        .listTasks({ q, status, rating })
        .then((result) => {
          if (active) setTasks(result.tasks);
        })
        .catch(() => {
          if (active) setError(true);
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 300);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [api, q, status, rating, attempt]);
  async function action(task: TaskView, kind: "resume" | "rerun" | "delete") {
    setBusy(true);
    setActionError(false);
    try {
      if (kind === "delete") {
        await api.deleteTask(task.id);
        setDeleting(null);
        setAttempt((value) => value + 1);
      } else {
        const next = await (kind === "resume"
          ? api.resumeTask(task.id)
          : api.rerunTask(task.id));
        navigate(`/tasks/${next.id}`);
      }
    } catch {
      setActionError(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>{reportsOnly ? "决策报告" : "任务记录"}</h1>
          <p>回看研究结果、恢复中断任务，或使用原参数再次分析。</p>
        </div>
        <Button type="primary" onClick={() => navigate("/")}>
          新建分析
        </Button>
      </div>
      <Card className="history-card">
        <div className="history-filters">
          <Input
            aria-label="代码或英文名称"
            placeholder="搜索股票代码或英文名称"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            allowClear
          />
          <Select
            aria-label="状态筛选"
            value={status || ""}
            onChange={(value) =>
              setStatus((value || undefined) as TaskFilters["status"])
            }
            options={[
              { value: "", label: "全部状态" },
              ...Object.entries(statusLabel).map(([value, label]) => ({
                value,
                label,
              })),
            ]}
          />
          <Select
            aria-label="评级筛选"
            value={rating || ""}
            onChange={(value) =>
              setRating((value || undefined) as TaskFilters["rating"])
            }
            options={[
              { value: "", label: "全部评级" },
              ...Object.entries(ratingLabel).map(([value, label]) => ({
                value,
                label,
              })),
            ]}
          />
          <Button
            onClick={() => {
              setQ("");
              setStatus(reportsOnly ? "completed" : undefined);
              setRating(undefined);
            }}
          >
            重置
          </Button>
        </div>
        {error && (
          <Alert
            className="form-alert"
            type="error"
            message="任务记录加载失败。"
            action={
              <Button onClick={() => setAttempt((value) => value + 1)}>
                重试
              </Button>
            }
          />
        )}
        {actionError && (
          <Alert
            className="form-alert"
            type="error"
            message="操作未完成，任务状态可能已改变，请刷新后重试。"
            action={
              <Button onClick={() => setAttempt((value) => value + 1)}>
                刷新
              </Button>
            }
          />
        )}
        {loading ? (
          <Spin aria-label="正在加载任务记录" />
        ) : (
          !error &&
          (tasks.length ? (
            <>
              <div className="history-row history-head" aria-hidden="true">
                <span>标的</span>
                <span>分析日期 / 状态</span>
                <span>最终评级</span>
                <span>操作</span>
              </div>
              <ul className="history-list">
                {tasks.map((task) => (
                  <li className="history-row" key={task.id}>
                    <div className="history-asset">
                      <strong>{task.ticker}</strong>
                      <span className="muted">{task.name}</span>
                    </div>
                    <div>
                      <div className="history-date">{task.date}</div>
                      <Status task={task} />
                    </div>
                    <div className="history-rating">
                      {task.rating ? ratingLabel[task.rating] : "未提供"}
                    </div>
                    <Space wrap className="history-actions">
                      <Button
                        onClick={() =>
                          navigate(
                            `/${task.status === "completed" ? "reports" : "tasks"}/${task.id}`,
                          )
                        }
                      >
                        {task.status === "completed" ? "查看报告" : "查看进度"}
                      </Button>
                      {task.status === "interrupted" && task.can_resume && (
                        <Button
                          loading={busy}
                          onClick={() => action(task, "resume")}
                        >
                          继续运行
                        </Button>
                      )}
                      <Button
                        disabled={busy}
                        onClick={() => action(task, "rerun")}
                      >
                        再次分析
                      </Button>
                      {task.status !== "running" && (
                        <Button
                          danger
                          disabled={busy}
                          aria-label={`删除 ${task.ticker}`}
                          onClick={() => setDeleting(task)}
                        >
                          删除
                        </Button>
                      )}
                    </Space>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <Empty description="暂无匹配的任务" />
          ))
        )}
      </Card>
      <Modal
        title="删除任务记录"
        open={!!deleting}
        onCancel={() => !busy && setDeleting(null)}
        onOk={() => deleting && action(deleting, "delete")}
        okText="确认删除"
        cancelText="取消"
        okButtonProps={{ danger: true }}
        confirmLoading={busy}
      >
        <p>
          确认删除 {deleting?.ticker} 的本次任务及专属报告？此操作不可撤销。
        </p>
        <p className="muted">其他任务、共享记忆和检查点将保留。</p>
        {actionError && <Alert type="error" message="删除失败，请稍后重试。" />}
      </Modal>
    </>
  );
}
