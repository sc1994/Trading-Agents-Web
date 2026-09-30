import { useState } from "react";
import { Button, Empty, Space, Tooltip } from "antd";
import { DeleteOutlined, DownOutlined, RightOutlined } from "@ant-design/icons";
import type { TaskView } from "../api";
import { ratingLabel } from "./TaskContent";

function generatedAt(task: TaskView) {
  return task.finished_at || task.created_at;
}

function displayTime(task: TaskView) {
  return new Date(generatedAt(task)).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function ReportGroups({
  tasks,
  rating,
  query,
  navigate,
  busy,
  rerun,
  remove,
}: {
  tasks: TaskView[];
  rating?: TaskView["rating"];
  query: string;
  navigate: (path: string) => void;
  busy: boolean;
  rerun: (task: TaskView) => void;
  remove: (task: TaskView) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const bySymbol = new Map<string, TaskView[]>();
  // Filter ratings only after grouping, so older matches cannot replace the latest report.
  for (const task of [...tasks]
    .filter((task) => task.status === "completed")
    .sort((a, b) => Date.parse(generatedAt(b)) - Date.parse(generatedAt(a)))) {
    const group = bySymbol.get(task.ticker) || [];
    group.push(task);
    bySymbol.set(task.ticker, group);
  }
  const search = query.trim().toLowerCase();
  const groups = [...bySymbol.values()].filter(
    (group) =>
      (!rating || group[0].rating === rating) &&
      group.some(
        (task) =>
          task.ticker.toLowerCase().includes(search) ||
          task.name.toLowerCase().includes(search),
      ),
  );
  if (!groups.length) return <Empty description="暂无匹配的报告" />;

  return (
    <>
      <div className="report-group-row history-head" aria-hidden="true">
        <span>标的</span>
        <span>最新分析</span>
        <span>最新评级</span>
        <span>报告数</span>
        <span>操作</span>
      </div>
      <ul className="history-list">
        {groups.map((group) => {
          const latest = group[0];
          const previous = group[1];
          const open = expanded.has(latest.ticker);
          const changed =
            previous?.rating &&
            latest.rating &&
            previous.rating !== latest.rating;
          const label = latest.rating ? ratingLabel[latest.rating] : "未提供";
          const regionId = `reports-${latest.id}`;
          return (
            <li className="report-group" key={latest.ticker}>
              <div className="report-group-row">
                <div className="history-asset">
                  <strong>{latest.ticker}</strong>
                  <span className="muted">
                    {group.find((report) => report.name)?.name}
                  </span>
                </div>
                <div className="report-latest-date">
                  <span>{latest.date}</span>
                  <span className="muted">生成于 {displayTime(latest)}</span>
                </div>
                <div className="report-rating">
                  <strong>{label}</strong>
                  {changed && (
                    <span className="muted">
                      {ratingLabel[previous.rating!]} → {label}
                    </span>
                  )}
                </div>
                <Button
                  type="text"
                  icon={open ? <DownOutlined /> : <RightOutlined />}
                  aria-label={`${latest.ticker} 的 ${group.length} 份报告`}
                  aria-expanded={open}
                  aria-controls={regionId}
                  onClick={() =>
                    setExpanded((current) => {
                      const next = new Set(current);
                      if (open) next.delete(latest.ticker);
                      else next.add(latest.ticker);
                      return next;
                    })
                  }
                >
                  {group.length} 份
                </Button>
                <Space wrap className="report-group-actions">
                  <Button onClick={() => navigate(`/reports/${latest.id}`)}>
                    查看最新
                  </Button>
                  <Button disabled={busy} onClick={() => rerun(latest)}>
                    再次分析
                  </Button>
                </Space>
              </div>
              {open && (
                <div
                  id={regionId}
                  className="report-versions"
                  role="region"
                  aria-label={`${latest.ticker} 历史报告`}
                >
                  <div
                    className="report-version-row report-version-head"
                    aria-hidden="true"
                  >
                    <span>生成时间</span>
                    <span>分析日期</span>
                    <span>评级</span>
                    <span>操作</span>
                  </div>
                  <ul className="history-list">
                    {group.map((report, index) => (
                      <li className="report-version-row" key={report.id}>
                        <div className="report-version-time">
                          <time dateTime={generatedAt(report)}>
                            {displayTime(report)}
                          </time>
                          {index === 0 && <span className="muted">最新</span>}
                        </div>
                        <span className="report-version-date">
                          <span className="mobile-label muted">分析日期 </span>
                          {report.date}
                        </span>
                        <strong>
                          {report.rating
                            ? ratingLabel[report.rating]
                            : "未提供"}
                        </strong>
                        <Space className="report-version-actions">
                          <Button
                            size="small"
                            onClick={() => navigate(`/reports/${report.id}`)}
                          >
                            查看报告
                          </Button>
                          <Tooltip title="删除本份报告">
                            <Button
                              size="small"
                              danger
                              disabled={busy}
                              icon={<DeleteOutlined />}
                              aria-label={`删除 ${report.ticker} 的报告 ${report.id}`}
                              onClick={() => remove(report)}
                            />
                          </Tooltip>
                        </Space>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}
