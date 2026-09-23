import { useEffect, useState } from "react";
import { Alert, Button, Card, Space, Spin } from "antd";
import type { ReportView, TaskView, WebApi } from "../api";
import {
  Markdown,
  ratingLabel,
  Sections,
  Status,
} from "../components/TaskContent";

export function Report({
  api,
  taskId,
  navigate,
}: {
  api: WebApi;
  taskId: string;
  navigate: (path: string) => void;
}) {
  const [data, setData] = useState<{
    task: TaskView;
    report: ReportView;
  } | null>(null);
  const [error, setError] = useState(false);
  const [actionError, setActionError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setData(null);
    setError(false);
    Promise.all([api.getTask(taskId), api.getReport(taskId)])
      .then(([task, report]) => {
        if (active) setData({ task, report });
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
  }, [api, taskId, attempt]);
  async function rerun() {
    setBusy(true);
    setActionError(false);
    try {
      const next = await api.rerunTask(taskId);
      navigate(`/tasks/${next.id}`);
    } catch {
      setActionError(true);
    } finally {
      setBusy(false);
    }
  }
  const decision = data?.report.decision;
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>{data ? `${data.task.ticker} 决策报告` : "决策报告"}</h1>
          <p>
            {data
              ? `${data.task.name || data.task.ticker} · ${data.task.date}`
              : "查看已保存的研究依据与决策。"}
          </p>
        </div>
        {data && (
          <Space wrap className="page-actions">
            <Button loading={busy} onClick={rerun}>
              复制参数再次分析
            </Button>
            <Button
              type="primary"
              href={`/api/tasks/${encodeURIComponent(taskId)}/report.md`}
              download
            >
              导出 Markdown
            </Button>
          </Space>
        )}
      </div>
      {error && (
        <Alert
          type="error"
          message="报告加载失败，请重试。"
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
          message="未能创建新任务，请检查配置后重试。"
        />
      )}
      {!data && !error && <Spin aria-label="正在加载报告" />}
      {data && (
        <>
          <Card className="report-summary">
            <div className="summary-grid">
              <div className="rating-block">
                <span className="muted">最终评级</span>
                <strong
                  className={`rating rating-${data.task.rating || "none"}`}
                >
                  {data.task.rating ? ratingLabel[data.task.rating] : "未提供"}
                </strong>
                <Status task={data.task} />
              </div>
              <div>
                <h2>执行摘要</h2>
                {decision?.executive_summary ? (
                  <Markdown text={decision.executive_summary} />
                ) : (
                  <p className="muted">未提供</p>
                )}
              </div>
            </div>
          </Card>
          <div className="report-evidence">
            <Card title="投资论证">
              {decision?.investment_thesis ? (
                <Markdown text={decision.investment_thesis} />
              ) : (
                <p className="muted">未提供</p>
              )}
              {decision?.price_target && (
                <>
                  <h3>价格目标</h3>
                  <Markdown text={decision.price_target} />
                </>
              )}
              {decision?.time_horizon && (
                <>
                  <h3>时间范围</h3>
                  <Markdown text={decision.time_horizon} />
                </>
              )}
            </Card>
            <Card title="风险依据">
              {[
                "conservative_history",
                "neutral_history",
                "aggressive_history",
              ].some((key) => data.report.sections[key]?.trim()) ? (
                [
                  "conservative_history",
                  "neutral_history",
                  "aggressive_history",
                ]
                  .filter((key) => data.report.sections[key]?.trim())
                  .map((key) => (
                    <blockquote className="risk-excerpt" key={key}>
                      <Markdown
                        text={data.report.sections[key].split(/\n\s*\n/)[0]}
                      />
                    </blockquote>
                  ))
              ) : (
                <p className="muted">未提供</p>
              )}
            </Card>
          </div>
          <Card title="完整报告">
            <Sections sections={data.report.sections} />
          </Card>
        </>
      )}
    </>
  );
}
