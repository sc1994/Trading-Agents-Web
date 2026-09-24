import { render, screen, within } from "@testing-library/react";
import { Markdown } from "./TaskContent";

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
  render(
    <Markdown text="~~删除线~~ 与配平 https://example.com 链接" />,
  );
  expect(screen.getByText("删除线").tagName).toBe("DEL");
  expect(screen.getByRole("link", { name: "https://example.com" })).toHaveAttribute(
    "href",
    "https://example.com",
  );
});
