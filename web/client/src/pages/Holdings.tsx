import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  Form,
  InputNumber,
  Modal,
  Spin,
  Switch,
  Tag,
  Tooltip,
} from "antd";
import {
  CheckCircleOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  SettingOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { PlanForm, horizonLabels } from "../portfolio/PlanForm";
import {
  errorMessage,
  type HoldingSettings,
  type Overview,
  type Plan,
  type PortfolioApi,
  type ResearchNavigate,
} from "../portfolio/api";

const stateLabels = {
  review: "待复核",
  not_triggered: "已设条件未触发",
  no_conditions: "未设置条件",
  unavailable: "无法检查",
};
const checkLabels = {
  queued: "等待检查",
  running: "正在检查",
  completed: "检查完成",
  partial: "部分数据缺失",
  failed: "检查未完成",
  interrupted: "检查已中断",
};
const signalLabels: Record<string, string> = {
  lower: "触及下观察线",
  upper: "触及上观察线",
  review_date: "已到复核日期",
};
const money = (text: string | null) =>
  text === null
    ? "—"
    : Number(text).toLocaleString("zh-CN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });

export function Holdings({
  api,
  navigate,
}: {
  api: PortfolioApi;
  navigate: ResearchNavigate;
}) {
  const [data, setData] = useState<Overview>();
  const [settings, setSettings] = useState<HoldingSettings>();
  const [error, setError] = useState("");
  const [editor, setEditor] = useState<Plan | "new" | null>(null);
  const [closing, setClosing] = useState<Plan | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [settingsForm] = Form.useForm<HoldingSettings>();
  const load = useCallback(async () => {
    try {
      const [overview, config] = await Promise.all([
        api.getOverview(),
        api.getSettings(),
      ]);
      setData(overview);
      setSettings(config);
      setError("");
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "持仓加载失败，请重试。",
      );
    }
  }, [api]);
  useEffect(() => {
    let active = true;
    Promise.all([api.getOverview(), api.getSettings()])
      .then(([view, config]) => {
        if (active) {
          setData(view);
          setSettings(config);
        }
      })
      .catch(() => {
        if (active) setError("持仓加载失败，请重试。");
      });
    return () => {
      active = false;
    };
  }, [api]);
  const pending =
    data?.latest_check?.status === "queued" ||
    data?.latest_check?.status === "running";
  useEffect(() => {
    if (!pending) return;
    let active = true;
    const timer = setInterval(() => {
      api
        .getOverview()
        .then((value) => {
          if (active) setData(value);
        })
        .catch(() => {
          if (active) setError("检查进度加载失败，请刷新。");
        });
    }, 1500);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [api, pending]);
  async function check() {
    setBusy(true);
    setError("");
    try {
      await api.createCheck();
      await load();
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "检查未能启动，请重试。",
      );
    } finally {
      setBusy(false);
    }
  }
  const groups = new Map<string, Overview["plans"]>();
  data?.plans.forEach((p) => {
    groups.set(p.symbol, [...(groups.get(p.symbol) ?? []), p]);
  });
  const reviews =
    data?.plans.filter(
      (p) => !p.result_obsolete && p.result?.state === "review",
    ).length ?? 0;
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>我的持仓</h1>
          <p>收盘观察 · A 股</p>
        </div>
        <div className="portfolio-toolbar">
          <Tooltip title="刷新持仓">
            <Button
              aria-label="刷新持仓"
              icon={<ReloadOutlined />}
              onClick={load}
            />
          </Tooltip>
          <Tooltip title="检查设置">
            <Button
              aria-label="检查设置"
              icon={<SettingOutlined />}
              onClick={() => {
                if (settings) settingsForm.setFieldsValue(settings);
                setSettingsOpen(true);
              }}
              disabled={!settings}
            />
          </Tooltip>
          <Button
            icon={<CheckCircleOutlined />}
            onClick={check}
            loading={busy || pending}
            disabled={!data?.plans.length}
          >
            检查收盘
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setEditor("new")}
          >
            新增持仓
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
      {!data && !error && <Spin aria-label="加载持仓" />}
      {data && (
        <>
          <div className="portfolio-metrics">
            <div>
              <span>活动计划</span>
              <strong>{data.plans.length} 笔</strong>
              <small>同股计划合并计算集中度</small>
            </div>
            <div>
              <span>待你复核</span>
              <strong className={reviews ? "portfolio-risk" : ""}>
                {reviews} 项
              </strong>
              <small>仅依据你设定的观察条件</small>
            </div>
            <div>
              <span>已录入股票市值（元）</span>
              <strong>{money(data.summary.market_value)}</strong>
              <small>不含现金和未录入资产</small>
            </div>
          </div>
          <div className="portfolio-check-band">
            <div>
              <strong>
                {data.latest_check
                  ? checkLabels[data.latest_check.status]
                  : "尚无收盘检查"}
              </strong>
              <span>
                最近检查日期：{data.latest_check?.target_date ?? "尚未确认"}
              </span>
            </div>
            <span>
              {settings?.automatic
                ? "自动检查开启 · 交易日 16:30 后"
                : "自动检查关闭"}
            </span>
          </div>
          {data.latest_check?.error_code && (
            <Alert
              className="portfolio-alert"
              showIcon
              type="warning"
              message={errorMessage(data.latest_check.error_code)}
            />
          )}
          {!data.summary.complete && data.plans.length > 0 && (
            <Alert
              className="portfolio-alert"
              type="warning"
              showIcon
              message="数据不完整，暂不计算持仓汇总与集中度。"
            />
          )}
          {data.summary.complete && data.plans.length > 0 && (
            <div className="portfolio-summary">
              <span>
                浮动盈亏：<b>{money(data.summary.unrealized_pnl)} 元</b>
              </span>
              <span>
                按本次录入持仓与检查日收盘价估算，不含费用、分红和税费。
              </span>
            </div>
          )}
          {data.summary.concentrations
            .filter((c) => c.triggered)
            .map((c) => (
              <Alert
                key={c.symbol}
                type="warning"
                showIcon
                className="portfolio-alert"
                message={`${c.symbol} 占已录入股票持仓 ${c.percent}%，触及你设定的集中度上限。`}
              />
            ))}
          {!data.plans.length && (
            <Empty description="尚未录入持仓">
              <Button
                type="primary"
                onClick={() => setEditor("new")}
                icon={<PlusOutlined />}
              >
                新增持仓
              </Button>
            </Empty>
          )}
          {[...groups.entries()].map(([symbol, plans]) => (
            <section className="holding-stock" key={symbol}>
              <div className="holding-stock-heading">
                <div>
                  <h2>{plans[0].instrument.name}</h2>
                  <span>
                    {symbol} · {plans[0].instrument.exchange}
                  </span>
                </div>
                <div className="portfolio-toolbar">
                  <span>
                    合计{" "}
                    {plans
                      .reduce((sum, p) => sum + p.shares, 0)
                      .toLocaleString()}{" "}
                    股
                  </span>
                  <Button
                    icon={<SearchOutlined />}
                    onClick={() =>
                      navigate("/", {
                        symbol,
                        name: plans[0].instrument.name,
                        date: data.reference_date,
                      })
                    }
                  >
                    发起研究
                  </Button>
                </div>
              </div>
              <div className="holding-plans">
                {plans.map((p) => {
                  const r = p.result;
                  const label = p.result_obsolete
                    ? "计划已修改，结果待更新"
                    : r
                      ? stateLabels[r.state]
                      : "尚未检查";
                  return (
                    <article className="holding-plan" key={p.id}>
                      <div className="holding-plan-title">
                        <strong>{horizonLabels[p.horizon]}</strong>
                        <Tag
                          color={
                            !p.result_obsolete && r?.state === "review"
                              ? "red"
                              : !p.result_obsolete && r?.quality === "valid"
                                ? "green"
                                : "default"
                          }
                        >
                          {label}
                        </Tag>
                        <div className="plan-tools">
                          <Tooltip title="编辑计划">
                            <Button
                              aria-label={`编辑${horizonLabels[p.horizon]}计划`}
                              icon={<EditOutlined />}
                              onClick={() => setEditor(p)}
                            />
                          </Tooltip>
                          <Tooltip title="关闭持仓计划">
                            <Button
                              aria-label={`关闭${horizonLabels[p.horizon]}计划`}
                              icon={<StopOutlined />}
                              onClick={() => setClosing(p)}
                            />
                          </Tooltip>
                        </div>
                      </div>
                      <dl className="plan-numbers">
                        <div>
                          <dt>股数</dt>
                          <dd>{p.shares.toLocaleString()}</dd>
                        </div>
                        <div>
                          <dt>每股成本</dt>
                          <dd>{p.cost} 元</dd>
                        </div>
                        <div>
                          <dt>检查日收盘</dt>
                          <dd>
                            {!p.result_obsolete && r?.quality === "valid"
                              ? `${r.quote?.close} 元`
                              : "—"}
                          </dd>
                        </div>
                        <div>
                          <dt>浮动盈亏</dt>
                          <dd>
                            {p.result_obsolete
                              ? "—"
                              : money(r?.unrealized_pnl ?? null)}
                          </dd>
                        </div>
                      </dl>
                      <p className="plan-reason">
                        {p.reason || "尚未记录买入理由"}
                      </p>
                      <div className="plan-conditions">
                        <span>下线 {p.lower ?? "未设置"}</span>
                        <span>上线 {p.upper ?? "未设置"}</span>
                        <span>复核 {p.review_date ?? "未设置"}</span>
                      </div>
                      {p.cost_pending && (
                        <p className="portfolio-risk">
                          成本待核对，暂停价格与盈亏检查。
                        </p>
                      )}
                      {!p.result_obsolete && r && (
                        <div
                          className={`plan-observation ${r.state === "review" ? "attention" : ""}`}
                        >
                          {r.signals.map((signal) => (
                            <span key={signal}>
                              {signalLabels[signal] ?? signal}
                            </span>
                          ))}
                          {r.error_code && (
                            <span>{errorMessage(r.error_code)}</span>
                          )}
                          {r.quality === "valid" && (
                            <small>
                              {r.target_date} · {r.quote?.source} · 更新{" "}
                              {r.quote?.fetched_at
                                .replace("T", " ")
                                .slice(0, 19)}
                              {" UTC"}
                            </small>
                          )}
                          {r.state === "not_triggered" && (
                            <span>已设条件未触发，不代表投资安全。</span>
                          )}
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
              {!!data.reports[symbol]?.length && (
                <div className="holding-reports">
                  <span>通用单股研究，未结合你的持仓条件</span>
                  {data.reports[symbol].slice(0, 3).map((report) => (
                    <Button
                      type="link"
                      key={report.id}
                      onClick={() => navigate(`/reports/${report.id}`)}
                    >
                      {report.date} 报告
                    </Button>
                  ))}
                </div>
              )}
            </section>
          ))}
          <p className="portfolio-note">
            公开行情不保证可用性或交易级时效。送转等公司行动后请手动维护持仓；观察条件不构成自动交易指令。
          </p>
        </>
      )}
      <Modal
        title={editor === "new" ? "新增持仓计划" : "编辑持仓计划"}
        open={!!editor}
        footer={null}
        destroyOnHidden
        onCancel={() => setEditor(null)}
      >
        {editor && (
          <PlanForm
            key={editor === "new" ? "new" : `${editor.id}:${editor.revision}`}
            api={api}
            plan={editor === "new" ? undefined : editor}
            onSaved={() => {
              setEditor(null);
              void load();
            }}
            onCancel={() => setEditor(null)}
          />
        )}
      </Modal>
      <Modal
        title="关闭持仓计划"
        open={!!closing}
        confirmLoading={busy}
        okText="确认关闭"
        onCancel={() => setClosing(null)}
        onOk={async () => {
          if (!closing) return;
          setBusy(true);
          try {
            await api.closePlan(closing.id, closing.revision);
            setClosing(null);
            await load();
          } catch (failure) {
            setError(
              failure instanceof Error ? failure.message : "关闭失败，请重试。",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        <p>
          确认关闭 {closing?.instrument.name} 的
          {closing && horizonLabels[closing.horizon]}
          计划？历史检查和研究报告会保留。
        </p>
        {error && <Alert message={error} type="error" />}
      </Modal>
      <Modal
        title="收盘检查设置"
        open={settingsOpen}
        footer={null}
        onCancel={() => setSettingsOpen(false)}
      >
        <Form
          form={settingsForm}
          layout="vertical"
          onFinish={async (value) => {
            setBusy(true);
            try {
              const config = await api.updateSettings({
                ...value,
                concentration_limit: value.concentration_limit ?? null,
              });
              setSettings(config);
              setSettingsOpen(false);
              setError("");
            } catch (failure) {
              setError(
                failure instanceof Error ? failure.message : "设置保存失败。",
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          {error && (
            <Alert type="error" message={error} className="portfolio-alert" />
          )}
          <Form.Item
            name="automatic"
            label="交易日自动检查"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="concentration_limit"
            label="单股集中度上限（可选，%）"
          >
            <InputNumber stringMode style={{ width: "100%" }} />
          </Form.Item>
          <p className="portfolio-note">
            仅按已录入股票持仓计算占比，不含现金及其他资产。
          </p>
          <Button type="primary" htmlType="submit" loading={busy}>
            保存设置
          </Button>
        </Form>
      </Modal>
    </>
  );
}
