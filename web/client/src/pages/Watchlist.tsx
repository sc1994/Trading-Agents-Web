import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Empty, Input, Modal, Spin, Tooltip } from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { InstrumentPicker } from "../portfolio/InstrumentPicker";
import { PlanForm } from "../portfolio/PlanForm";
import type {
  Instrument,
  PortfolioApi,
  ResearchNavigate,
  Watch,
} from "../portfolio/api";

export function Watchlist({
  api,
  navigate,
}: {
  api: PortfolioApi;
  navigate: ResearchNavigate;
}) {
  const [rows, setRows] = useState<Watch[]>();
  const [referenceDate, setReferenceDate] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [editor, setEditor] = useState<Watch | "new" | null>(null);
  const [selected, setSelected] = useState<Instrument>();
  const [reason, setReason] = useState("");
  const [holding, setHolding] = useState<Instrument>();
  const [removing, setRemoving] = useState<Watch>();
  const [saving, setSaving] = useState(false);
  const load = useCallback(async () => {
    try {
      const [list, view] = await Promise.all([
        api.listWatchlist(),
        api.getOverview(),
      ]);
      setRows(list.watchlist);
      setReferenceDate(view.reference_date);
      setError("");
    } catch {
      setError("自选股加载失败，请重试。");
    }
  }, [api]);
  useEffect(() => {
    let active = true;
    Promise.all([api.listWatchlist(), api.getOverview()])
      .then(([list, view]) => {
        if (active) {
          setRows(list.watchlist);
          setReferenceDate(view.reference_date);
        }
      })
      .catch(() => {
        if (active) setError("自选股加载失败，请重试。");
      });
    return () => {
      active = false;
    };
  }, [api]);
  function edit(value: Watch | "new") {
    setEditor(value);
    setSelected(value === "new" ? undefined : value);
    setReason(value === "new" ? "" : value.reason);
    setError("");
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>自选股</h1>
          <p>关注清单 · A 股</p>
        </div>
        <div className="portfolio-toolbar">
          <Tooltip title="刷新清单">
            <Button
              aria-label="刷新清单"
              icon={<ReloadOutlined />}
              onClick={load}
            />
          </Tooltip>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => edit("new")}
          >
            添加自选
          </Button>
        </div>
      </div>
      {error && (
        <Alert
          type="error"
          showIcon
          message={error}
          className="portfolio-alert"
        />
      )}
      {!rows && !error && <Spin aria-label="加载自选股" />}
      {rows?.length === 0 && (
        <Empty description="尚无自选股">
          <Button icon={<PlusOutlined />} onClick={() => edit("new")}>
            添加自选
          </Button>
        </Empty>
      )}
      <div className="watchlist-rows">
        {rows?.map((row) => (
          <article className="watchlist-row" key={row.symbol}>
            <div className="watchlist-identity">
              <h2>{row.name}</h2>
              <span>
                {row.symbol} · {row.exchange}
              </span>
              <p>{row.reason || "尚未记录关注理由"}</p>
            </div>
            <div className="portfolio-toolbar">
              <Button
                icon={<SearchOutlined />}
                onClick={() =>
                  navigate("/", {
                    symbol: row.symbol,
                    name: row.name,
                    date: referenceDate,
                  })
                }
              >
                发起研究
              </Button>
              <Button
                aria-label="建立持仓计划"
                icon={<PlusOutlined />}
                onClick={() => setHolding(row)}
              >
                建立持仓计划
              </Button>
              <Tooltip title="编辑关注理由">
                <Button
                  aria-label={`编辑${row.name}关注理由`}
                  icon={<EditOutlined />}
                  onClick={() => edit(row)}
                />
              </Tooltip>
              <Tooltip title="移出自选">
                <Button
                  aria-label={`移出${row.name}自选`}
                  icon={<DeleteOutlined />}
                  onClick={() => setRemoving(row)}
                />
              </Tooltip>
            </div>
          </article>
        ))}
      </div>
      <Modal
        title={editor === "new" ? "添加自选股" : "编辑关注理由"}
        open={!!editor}
        onCancel={() => setEditor(null)}
        confirmLoading={saving}
        okText="保存"
        onOk={async () => {
          if (!selected) {
            setError("请先选择已确认的 A 股股票。");
            return;
          }
          setSaving(true);
          try {
            if (editor === "new") await api.addWatch(selected.symbol, reason);
            else await api.updateWatch(selected.symbol, reason);
            setEditor(null);
            await load();
          } catch (failure) {
            setError(
              failure instanceof Error
                ? failure.message
                : "保存失败，输入已保留。",
            );
          } finally {
            setSaving(false);
          }
        }}
      >
        {error && (
          <Alert type="error" message={error} className="portfolio-alert" />
        )}
        <div className="watch-form-field">
          <label>股票</label>
          <InstrumentPicker
            api={api}
            value={selected}
            onChange={setSelected}
            disabled={editor !== "new"}
          />
        </div>
        <div className="watch-form-field">
          <label htmlFor="watch-reason">关注理由</label>
          <Input.TextArea
            id="watch-reason"
            value={reason}
            maxLength={2000}
            rows={3}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>
      </Modal>
      <Modal
        title="新增持仓计划"
        open={!!holding}
        footer={null}
        destroyOnHidden
        onCancel={() => setHolding(undefined)}
      >
        {holding && (
          <PlanForm
            key={holding.symbol}
            api={api}
            initialInstrument={holding}
            onSaved={() => {
              setHolding(undefined);
              navigate("/holdings");
            }}
            onCancel={() => setHolding(undefined)}
          />
        )}
      </Modal>
      <Modal
        title="移出自选股"
        open={!!removing}
        okText="确认移出"
        confirmLoading={saving}
        onCancel={() => setRemoving(undefined)}
        onOk={async () => {
          if (!removing) return;
          setSaving(true);
          try {
            await api.removeWatch(removing.symbol);
            setRemoving(undefined);
            await load();
          } catch (failure) {
            setError(
              failure instanceof Error ? failure.message : "移出失败，请重试。",
            );
          } finally {
            setSaving(false);
          }
        }}
      >
        <p>移出 {removing?.name}？持仓计划和研究报告不受影响。</p>
        {error && <Alert type="error" message={error} />}
      </Modal>
    </>
  );
}
