import { Empty, Tabs, Tag } from "antd";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { TaskView } from "../api";

export const ratingLabel = {
  Buy: "买入",
  Overweight: "增持",
  Hold: "持有",
  Underweight: "减持",
  Sell: "卖出",
  REVIEW: "需复核",
};
export const statusLabel = {
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  interrupted: "已中断",
};
export const groups = [
  {
    key: "analysts",
    label: "分析师",
    sections: [
      "market_report",
      "sentiment_report",
      "news_report",
      "fundamentals_report",
    ],
  },
  {
    key: "research",
    label: "多空研究",
    sections: ["bull_history", "bear_history", "investment_plan"],
  },
  { key: "trader", label: "交易员", sections: ["trader_investment_plan"] },
  {
    key: "risk",
    label: "风险团队",
    sections: ["aggressive_history", "conservative_history", "neutral_history"],
  },
  { key: "portfolio", label: "组合经理", sections: ["decision"] },
];
export const sectionLabel: Record<string, string> = {
  market_report: "市场分析",
  sentiment_report: "情绪分析",
  news_report: "新闻分析",
  fundamentals_report: "基本面分析",
  bull_history: "多头研究",
  bear_history: "空头研究",
  investment_plan: "研究结论",
  trader_investment_plan: "交易计划",
  aggressive_history: "积极风险观点",
  conservative_history: "保守风险观点",
  neutral_history: "中性风险观点",
  decision: "组合经理决策",
};
export function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        skipHtml
        remarkPlugins={[remarkGfm]}
        components={{ img: () => null }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
export function Sections({ sections }: { sections: Record<string, string> }) {
  const items = groups.flatMap((group) => {
    const entries = group.sections.filter((key) => sections[key]?.trim());
    return entries.length
      ? [
          {
            key: group.key,
            label: group.label,
            children: entries.map((key) => (
              <section key={key} className="report-section">
                <h3>{sectionLabel[key]}</h3>
                <Markdown text={sections[key]} />
              </section>
            )),
          },
        ]
      : [];
  });
  return items.length ? (
    <Tabs className="report-tabs" items={items} />
  ) : (
    <Empty description="暂无报告章节" />
  );
}
export function Status({ task }: { task: TaskView }) {
  return (
    <Tag
      color={
        task.status === "completed"
          ? "success"
          : task.status === "failed"
            ? "error"
            : task.status === "interrupted"
              ? "warning"
              : "default"
      }
    >
      {statusLabel[task.status]}
    </Tag>
  );
}
