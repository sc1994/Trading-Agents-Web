import { fireEvent, render, screen, within } from "@testing-library/react";
import { Markdown, Sections } from "./TaskContent";

it("renders GitHub-flavored tables instead of raw pipes", () => {
  render(
    <Markdown
      text={`| 估值指标 | 当前值 | 这意味着什么 |
|---|---:|---|
| 市盈率 (TTM) | 8.44 倍 | 不到行业平均的一半 |
| 市净率 | 0.87 倍 | 低于清算价值 |`}
    />,
  );
  const table = screen.getByRole("table");
  expect(table).toBeInTheDocument();
  const rows = within(table).getAllByRole("row");
  expect(rows).toHaveLength(3);
  expect(within(rows[0]).getAllByRole("columnheader")).toHaveLength(3);
  expect(within(rows[2]).getAllByRole("cell")).toHaveLength(3);
  expect(
    screen.getByRole("columnheader", { name: "估值指标" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "8.44 倍" })).toBeInTheDocument();
});

it("renders other GitHub-flavored syntax", () => {
  render(<Markdown text="~~删除线~~ 与配平 https://example.com 链接" />);
  expect(screen.getByText("删除线").tagName).toBe("DEL");
  expect(
    screen.getByRole("link", { name: "https://example.com" }),
  ).toHaveAttribute("href", "https://example.com");
});

it("shows only the selected role's report within a team", () => {
  render(
    <Sections
      sections={{
        market_report: "价格趋势",
        fundamentals_report: "现金流依据",
        bear_history: "估值风险",
      }}
    />,
  );
  expect(screen.getByText("价格趋势")).toBeInTheDocument();
  expect(screen.queryByText("现金流依据")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("radio", { name: "基本面分析" }));
  expect(screen.getByText("现金流依据")).toBeInTheDocument();
  expect(screen.queryByText("价格趋势")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "多空研究" }));
  expect(screen.getByText("估值风险")).toBeInTheDocument();
  expect(screen.queryByText("现金流依据")).not.toBeInTheDocument();
});

it("switches native debate turns without concatenating them and respects turn bounds", () => {
  render(
    <Sections
      sections={{
        bear_history:
          "\nBear Analyst: 第一轮观点\n\n## 证据\n首轮证据\nBear Analyst: 第二轮反驳\n\n尾轮证据",
      }}
    />,
  );
  expect(screen.getByText("第一轮观点")).toBeInTheDocument();
  expect(screen.queryByText("第二轮反驳")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "上一轮" })).toBeDisabled();
  fireEvent.change(screen.getByRole("combobox", { name: "辩论轮次" }), {
    target: { value: "1" },
  });
  expect(screen.getByText("第二轮反驳")).toBeInTheDocument();
  expect(screen.queryByText("首轮证据")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "下一轮" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "上一轮" }));
  expect(screen.getByText("第一轮观点")).toBeInTheDocument();
});

it("ignores role markers in fenced code and blockquotes when finding turns", () => {
  render(
    <Sections
      sections={{
        bull_history:
          "Bull Analyst: 开篇\n\n```text\nBull Analyst: 代码示例\n```\n\n> Bull Analyst: 引用观点\n\nBull Analyst: 后续发言",
      }}
    />,
  );
  const selector = screen.getByRole("combobox", { name: "辩论轮次" });
  expect(within(selector).getAllByRole("option")).toHaveLength(2);
  expect(screen.getByText("Bull Analyst: 代码示例")).toBeInTheDocument();
  expect(screen.getByText("Bull Analyst: 引用观点")).toBeInTheDocument();
  expect(screen.queryByText("后续发言")).not.toBeInTheDocument();
});

it.each([
  "- 第一条证据\n- 最后一条证据",
  "> 最后的引用证据",
  "| 证据 | 判断 |\n|---|---|\n| 估值 | 观察 |",
])(
  "recognizes single-newline native turn boundaries after Markdown blocks: %s",
  (ending) => {
    render(
      <Sections
        sections={{
          bear_history: `Bear Analyst: 第一轮\n\n${ending}\nBear Analyst: 第二轮正文`,
        }}
      />,
    );
    const rounds = screen.getByRole("combobox", { name: "辩论轮次" });
    expect(within(rounds).getAllByRole("option")).toHaveLength(2);
    fireEvent.change(rounds, { target: { value: "1" } });
    expect(screen.getByText("第二轮正文")).toBeInTheDocument();
  },
);

it.each([
  "没有轮次标记的完整观点\n\nBull Analyst: 文内例子",
  "Bull Analyst: 只有一次发言",
  "普通报告正文",
])(
  "keeps unstructured or single-turn reports readable without a turn selector: %s",
  (text) => {
    render(<Sections sections={{ bull_history: text }} />);
    expect(
      screen.queryByRole("combobox", { name: "辩论轮次" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "下一轮" }),
    ).not.toBeInTheDocument();
  },
);

it("builds an on-demand chapter menu from real Markdown headings and focuses the selected heading", () => {
  const { container } = render(
    <Sections
      sections={{
        market_report:
          "## 相同 **标题**\n正文\n\n```md\n# 不是章节\n```\n\n相同 标题\n---\n\n末段",
      }}
    />,
  );
  const headings = container.querySelectorAll(".markdown h2");
  expect(headings).toHaveLength(2);
  expect(headings[0].id).not.toBe(headings[1].id);
  expect(
    screen.queryByRole("link", { name: "相同 标题" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "章节目录" }));
  const links = screen.getAllByRole("link", { name: "相同 标题" });
  expect(links).toHaveLength(2);
  expect(
    screen.queryByRole("link", { name: "不是章节" }),
  ).not.toBeInTheDocument();
  fireEvent.click(links[1]);
  expect(headings[1]).toHaveFocus();
});

it("hides chapter navigation when a report has no headings", () => {
  render(<Sections sections={{ decision: "完整决策正文" }} />);
  expect(
    screen.queryByRole("button", { name: "章节目录" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("完整决策正文")).toBeInTheDocument();
});

it("can enter and exit focus reading with Escape and restores background scrolling", () => {
  document.body.style.overflow = "auto";
  const { unmount } = render(
    <Sections sections={{ news_report: "新闻依据" }} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "专注阅读" }));
  expect(
    screen.getByRole("button", { name: "退出专注阅读" }),
  ).toBeInTheDocument();
  expect(document.body.style.overflow).toBe("hidden");
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.getByRole("button", { name: "专注阅读" })).toHaveFocus();
  expect(document.body.style.overflow).toBe("auto");
  fireEvent.click(screen.getByRole("button", { name: "专注阅读" }));
  unmount();
  expect(document.body.style.overflow).toBe("auto");
  document.body.style.overflow = "";
});

it("preserves a selected turn when a live report adds another turn", () => {
  const { rerender } = render(
    <Sections
      sections={{ bear_history: "Bear Analyst: 首轮\n\nBear Analyst: 次轮" }}
    />,
  );
  fireEvent.change(screen.getByRole("combobox", { name: "辩论轮次" }), {
    target: { value: "1" },
  });
  rerender(
    <Sections
      sections={{
        bear_history:
          "Bear Analyst: 首轮\n\nBear Analyst: 次轮\n\nBear Analyst: 新轮",
      }}
    />,
  );
  expect(screen.getByText("次轮")).toBeInTheDocument();
  expect(screen.queryByText("新轮")).not.toBeInTheDocument();
  expect(
    within(screen.getByRole("combobox", { name: "辩论轮次" })).getAllByRole(
      "option",
    ),
  ).toHaveLength(3);
});

it("restores background scrolling if focused reports disappear in a live update", () => {
  const { rerender } = render(
    <Sections sections={{ news_report: "新闻依据" }} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "专注阅读" }));
  expect(document.body.style.overflow).toBe("hidden");
  rerender(<Sections sections={{}} />);
  expect(screen.getByText("暂无报告章节")).toBeInTheDocument();
  expect(document.body.style.overflow).not.toBe("hidden");
});
