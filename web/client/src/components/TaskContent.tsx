import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { Button, Empty, Popover, Segmented, Tabs, Tag, Tooltip } from "antd";
import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  FullscreenOutlined,
  FullscreenExitOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { TaskView } from "../api";
import { remarkHeadingIds, reportChapters, reportTurns } from "./reportReading";

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
export function Markdown({
  text,
  headingPrefix,
}: {
  text: string;
  headingPrefix?: string;
}) {
  return (
    <div className="markdown">
      <ReactMarkdown
        skipHtml
        remarkPlugins={
          headingPrefix
            ? [remarkGfm, [remarkHeadingIds, headingPrefix]]
            : [remarkGfm]
        }
        components={{ img: () => null }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
export function Sections({ sections }: { sections: Record<string, string> }) {
  const id = useId();
  const [team, setTeam] = useState("");
  const [role, setRole] = useState("");
  const [round, setRound] = useState(0);
  const [chaptersOpen, setChaptersOpen] = useState(false);
  const [focused, setFocused] = useState(false);
  const reader = useRef<HTMLElement>(null);
  const focusButton = useRef<HTMLButtonElement>(null);
  const placeholderHeight = useRef(0);
  const pagePosition = useRef<{ x: number; y: number } | null>(null);
  const readingPosition = useRef<{ index: number; top: number } | null>(null);
  const scrollToStart = useRef(false);
  const available = groups.filter((group) =>
    group.sections.some((key) => sections[key]?.trim()),
  );
  const activeTeam =
    available.find((group) => group.key === team) ?? available[0];
  const roles =
    activeTeam?.sections.filter((key) => sections[key]?.trim()) ?? [];
  const activeRole = roles.includes(role) ? role : roles[0];
  const source = sections[activeRole] ?? "";
  const turns = useMemo(
    () => reportTurns(activeRole, source),
    [activeRole, source],
  );
  const activeRound = Math.min(round, turns.length - 1);
  const text = turns[activeRound];
  const prefix = `${id}-${activeRole}-${activeRound}`;
  const chapters = useMemo(() => reportChapters(text, prefix), [text, prefix]);
  const hasReports = !!activeTeam;

  useEffect(() => {
    if (!hasReports) setFocused(false);
  }, [hasReports]);

  useLayoutEffect(() => {
    const node = reader.current;
    if (!node) return;
    if (
      !focused &&
      pagePosition.current &&
      (window.scrollY !== pagePosition.current.y ||
        window.scrollX !== pagePosition.current.x)
    ) {
      window.scrollTo(pagePosition.current.x, pagePosition.current.y);
    }
    const position = readingPosition.current;
    const anchor =
      position &&
      node.querySelectorAll<HTMLElement>(".markdown > *")[position.index];
    if (anchor && position) {
      const difference = anchor.getBoundingClientRect().top - position.top;
      if (focused) node.scrollTop += difference;
      else window.scrollBy(0, difference);
    }
  }, [focused]);

  useLayoutEffect(() => {
    if (!scrollToStart.current) return;
    scrollToStart.current = false;
    if (focused && reader.current) reader.current.scrollTop = 0;
    else reader.current?.scrollIntoView({ block: "start" });
  }, [activeRole, activeRound, activeTeam?.key, focused]);

  useEffect(() => {
    if (!focused || !hasReports) return;
    const overflow = document.body.style.overflow;
    const background = Array.from(document.body.children)
      .filter(
        (node): node is HTMLElement =>
          node instanceof HTMLElement && !node.contains(reader.current),
      )
      .map((node) => ({ node, inert: node.inert }));
    background.forEach(({ node }) => {
      node.inert = true;
    });
    document.body.style.overflow = "hidden";
    focusButton.current?.focus({ preventScroll: true });
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setChaptersOpen(false);
        changeFocus(false);
      }
      if (event.key !== "Tab") return;
      const controls = Array.from(
        reader.current?.querySelectorAll<HTMLElement>(
          "button, a[href], select, input, [tabindex]",
        ) ?? [],
      ).filter(
        (node) =>
          node.tabIndex >= 0 &&
          !node.hasAttribute("disabled") &&
          node.getClientRects().length,
      );
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = overflow;
      background.forEach(({ node, inert }) => {
        node.inert = inert;
      });
      document.removeEventListener("keydown", onKey);
      focusButton.current?.focus({ preventScroll: true });
    };
  }, [focused, hasReports]);

  function changeFocus(value: boolean) {
    const node = reader.current;
    if (node) {
      if (value) {
        placeholderHeight.current = node.getBoundingClientRect().height;
        pagePosition.current = { x: window.scrollX, y: window.scrollY };
      }
      const controlsBottom =
        node.querySelector(".reader-controls")?.getBoundingClientRect()
          .bottom ?? 0;
      const anchors = Array.from(
        node.querySelectorAll<HTMLElement>(".markdown > *"),
      );
      const index = anchors.findIndex(
        (anchor) => anchor.getBoundingClientRect().bottom > controlsBottom,
      );
      readingPosition.current =
        index >= 0 && (focused || node.getBoundingClientRect().top < 0)
          ? { index, top: anchors[index].getBoundingClientRect().top }
          : null;
    }
    setChaptersOpen(false);
    setFocused(value);
  }

  function chooseRole(value: string) {
    scrollToStart.current = true;
    setRole(value);
    setRound(0);
    setChaptersOpen(false);
  }
  function chooseRound(value: number) {
    scrollToStart.current = true;
    setRound(value);
    setChaptersOpen(false);
  }
  const toolbar = (
    <div className="reader-controls">
      {roles.length > 1 ? (
        <>
          <Segmented
            className="reader-role-segments"
            aria-label="报告角色"
            options={roles.map((key) => ({
              value: key,
              label: sectionLabel[key],
            }))}
            value={activeRole}
            onChange={chooseRole}
          />
          <select
            className="reader-role-select"
            aria-label="报告角色"
            value={activeRole}
            onChange={(event) => chooseRole(event.target.value)}
          >
            {roles.map((key) => (
              <option key={key} value={key}>
                {sectionLabel[key]}
              </option>
            ))}
          </select>
        </>
      ) : (
        <span className="reader-single-role">{sectionLabel[activeRole]}</span>
      )}
      <div className="reader-tools">
        {turns.length > 1 && (
          <select
            aria-label="辩论轮次"
            className="reader-round-select"
            value={activeRound}
            onChange={(event) => chooseRound(Number(event.target.value))}
          >
            {turns.map((_, index) => (
              <option key={index} value={index}>
                第 {index + 1} 轮
              </option>
            ))}
          </select>
        )}
        {!!chapters.length && (
          <Popover
            placement="bottomRight"
            trigger="click"
            open={chaptersOpen}
            onOpenChange={setChaptersOpen}
            getPopupContainer={(trigger) =>
              trigger.closest<HTMLElement>(".report-reader") ?? document.body
            }
            content={
              <nav className="reader-chapters" aria-label="本轮章节">
                {chapters.map((chapter) => (
                  <a
                    key={chapter.id}
                    href={`#${chapter.id}`}
                    className={
                      chapter.depth > 2 ? "reader-chapter-nested" : undefined
                    }
                    onClick={(event) => {
                      event.preventDefault();
                      const heading = document.getElementById(chapter.id);
                      heading?.scrollIntoView({ block: "start" });
                      heading?.focus({ preventScroll: true });
                      setChaptersOpen(false);
                    }}
                  >
                    {chapter.label}
                  </a>
                ))}
              </nav>
            }
          >
            <Tooltip title="章节目录">
              <Button
                type="text"
                icon={<UnorderedListOutlined />}
                aria-label="章节目录"
                aria-expanded={chaptersOpen}
              />
            </Tooltip>
          </Popover>
        )}
        <Tooltip title={focused ? "退出专注阅读" : "专注阅读"}>
          <Button
            ref={focusButton}
            type="text"
            icon={focused ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
            aria-label={focused ? "退出专注阅读" : "专注阅读"}
            onClick={() => changeFocus(!focused)}
          />
        </Tooltip>
      </div>
    </div>
  );
  const article = (
    <article className="reader-article">
      <div className="reader-meta">
        <span>{sectionLabel[activeRole]}</span>
        {turns.length > 1 && (
          <span>
            第 {activeRound + 1} 轮 / 共 {turns.length} 轮
          </span>
        )}
      </div>
      <Markdown text={text} headingPrefix={prefix} />
      {turns.length > 1 && (
        <footer className="reader-pagination">
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            aria-label="上一轮"
            disabled={activeRound === 0}
            onClick={() => chooseRound(activeRound - 1)}
          >
            上一轮
          </Button>
          <span>
            {activeRound + 1} / {turns.length}
          </span>
          <Button
            type="text"
            aria-label="下一轮"
            disabled={activeRound === turns.length - 1}
            onClick={() => chooseRound(activeRound + 1)}
          >
            下一轮 <ArrowRightOutlined />
          </Button>
        </footer>
      )}
    </article>
  );
  const content = (
    <section
      ref={reader}
      className={`report-reader${focused ? " reader-focused" : ""}`}
      aria-label="报告阅读"
      role={focused ? "dialog" : undefined}
      aria-modal={focused || undefined}
    >
      <div className="reader-inner">
        <Tabs
          className="report-tabs"
          getPopupContainer={(trigger) =>
            trigger.closest<HTMLElement>(".report-reader") ?? document.body
          }
          activeKey={activeTeam?.key}
          onChange={(key) => {
            setTeam(key);
            chooseRole("");
          }}
          items={available.map((group) => ({
            key: group.key,
            label: group.label,
            children:
              group.key === activeTeam?.key ? (
                <>
                  {toolbar}
                  {article}
                </>
              ) : null,
          }))}
        />
      </div>
    </section>
  );
  if (!available.length) return <Empty description="暂无报告章节" />;
  return focused ? (
    <>
      <div aria-hidden style={{ height: placeholderHeight.current }} />
      {createPortal(content, document.body)}
    </>
  ) : (
    content
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
