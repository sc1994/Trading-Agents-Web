import { useEffect, useState } from "react";
import { AutoComplete, Alert, Input } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import {
  errorMessage,
  type CatalogStatus,
  type Instrument,
  type PortfolioApi,
} from "./api";

const exchangeNames = { SH: "沪市", SZ: "深市", BJ: "北交所" };
const catalogErrors: Record<string, string> = {
  market_timeout: "请求超时",
  market_dependency_missing: "行情依赖未安装",
  catalog_invalid: "上游名录校验失败",
  cache_write_failed: "缓存写入失败",
  market_unavailable: "上游服务异常",
};
function catalogDate(value: string) {
  return new Date(value).toLocaleDateString("sv-SE", {
    timeZone: "Asia/Shanghai",
  });
}
function catalogMessage(status: CatalogStatus) {
  const name = exchangeNames[status.exchange];
  const reason = catalogErrors[status.error_code ?? ""] ?? "更新失败";
  const update = status.refreshing
    ? "正在后台更新。"
    : status.error_code
      ? `${reason}，后台将重试。`
      : "等待后台更新。";
  if (status.state === "stale") {
    return `${name}：使用 ${catalogDate(status.fetched_at!)} 名录。${update}`;
  }
  if (status.state === "expired") {
    return `${name}：名录已超过 7 天，暂不能添加该市场股票。${update}`;
  }
  if (
    status.state === "loading" ||
    (status.state === "unavailable" && status.refreshing)
  ) {
    return `${name}：首次加载名录，完成后可选择。`;
  }
  if (status.state === "unavailable") {
    if (!status.error_code)
      return `${name}：等待名录加载，暂不能添加该市场股票。`;
    return `${name}：名录更新失败（${reason}），后台将重试；其他市场不受影响。`;
  }
  return "";
}

export function InstrumentPicker({
  api,
  value,
  onChange,
  disabled = false,
}: {
  api: PortfolioApi;
  value?: Instrument;
  onChange: (value?: Instrument) => void;
  disabled?: boolean;
}) {
  const [query, setQuery] = useState(
    value ? `${value.name} · ${value.symbol}` : "",
  );
  const [results, setResults] = useState<Instrument[]>([]);
  const [state, setState] = useState("");
  const [catalogs, setCatalogs] = useState<CatalogStatus[]>([]);
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (value) setQuery(`${value.name} · ${value.symbol}`);
  }, [value]);
  useEffect(() => {
    if (disabled || value || query.trim().length < 2) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let polls = 0;
    const search = () => {
      api
        .searchInstruments(query, controller.signal)
        .then((data) => {
          if (controller.signal.aborted) return;
          setResults(data.results);
          setCatalogs(data.catalog_status ?? []);
          setState(
            data.unavailable && !data.catalog_status?.length
              ? "股票名录暂不可用，请稍后重试。"
              : data.results.length ||
                  data.catalog_status?.some((s) => s.refreshing)
                ? ""
                : "未找到可确认的股票。",
          );
          if (data.catalog_status?.some((s) => s.refreshing) && polls++ < 15) {
            timer = setTimeout(search, 2000);
          }
        })
        .catch(() => {
          if (!controller.signal.aborted)
            setState("股票搜索失败，请稍后重试。");
        });
    };
    setState("搜索中");
    timer = setTimeout(search, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [api, query, value, disabled]);
  return (
    <div>
      <AutoComplete
        value={query}
        disabled={disabled}
        open={focused && results.length > 0}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onInputKeyDown={(event) => {
          if (event.key === "Escape") setFocused(false);
          if (event.key === "ArrowDown") setFocused(true);
        }}
        style={{ width: "100%" }}
        options={results.map((item) => ({
          value: item.symbol,
          disabled: !item.supported,
          label: (
            <div className="instrument-option">
              <strong>
                {item.name} · {item.symbol}
              </strong>
              {item.supported &&
                item.catalog_state === "stale" &&
                item.catalog_fetched_at && (
                  <small>
                    已核实 · 名录 {catalogDate(item.catalog_fetched_at)}
                  </small>
                )}
              {!item.supported && (
                <small>
                  {item.support_code === "unsupported_market"
                    ? "非 A 股，暂不支持"
                    : errorMessage(item.support_code)}
                </small>
              )}
            </div>
          ),
        }))}
        onSearch={(text) => {
          setFocused(true);
          setQuery(text);
          setResults([]);
          setCatalogs([]);
          onChange(undefined);
        }}
        onSelect={(symbol) => {
          const item = results.find((r) => r.symbol === symbol);
          if (item?.supported) {
            setFocused(false);
            onChange(item);
          }
        }}
      >
        <Input
          onClick={() => setFocused(true)}
          aria-label="股票"
          prefix={<SearchOutlined />}
          placeholder="搜索 A 股名称或代码"
        />
      </AutoComplete>
      {state && <small className="muted">{state}</small>}
      {catalogs.some((s) => s.state !== "fresh") && (
        <Alert
          type={
            catalogs.every((s) => s.state === "fresh" || s.state === "loading")
              ? "info"
              : "warning"
          }
          className="picker-warning"
          message={
            <div aria-live="polite">
              {catalogs.map((s) => {
                const message = catalogMessage(s);
                return message ? <div key={s.exchange}>{message}</div> : null;
              })}
            </div>
          }
        />
      )}
      {results.some(
        (r) => !r.supported && r.support_code === "unsupported_market",
      ) && (
        <Alert
          type="warning"
          className="picker-warning"
          message="当前持仓与收盘检查仅支持 A 股"
        />
      )}
    </div>
  );
}
