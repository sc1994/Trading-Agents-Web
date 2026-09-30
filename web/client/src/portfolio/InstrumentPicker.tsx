import { useEffect, useState } from "react";
import { AutoComplete, Alert, Input } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { errorMessage, type Instrument, type PortfolioApi } from "./api";

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
  useEffect(() => {
    if (value) setQuery(`${value.name} · ${value.symbol}`);
  }, [value]);
  useEffect(() => {
    if (disabled || value || query.trim().length < 2) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setState("搜索中");
      api
        .searchInstruments(query, controller.signal)
        .then((data) => {
          if (controller.signal.aborted) return;
          setResults(data.results);
          setState(
            data.unavailable
              ? "股票名录暂不可用，请稍后重试。"
              : data.results.length
                ? ""
                : "未找到可确认的股票。",
          );
        })
        .catch(() => {
          if (!controller.signal.aborted)
            setState("股票搜索失败，请稍后重试。");
        });
    }, 300);
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
        style={{ width: "100%" }}
        options={results.map((item) => ({
          value: item.symbol,
          disabled: !item.supported,
          label: (
            <div className="instrument-option">
              <strong>
                {item.name} · {item.symbol}
              </strong>
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
          setQuery(text);
          setResults([]);
          onChange(undefined);
        }}
        onSelect={(symbol) => {
          const item = results.find((r) => r.symbol === symbol);
          if (item?.supported) onChange(item);
        }}
      >
        <Input
          aria-label="股票"
          prefix={<SearchOutlined />}
          placeholder="搜索 A 股名称或代码"
        />
      </AutoComplete>
      {state && <small className="muted">{state}</small>}
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
