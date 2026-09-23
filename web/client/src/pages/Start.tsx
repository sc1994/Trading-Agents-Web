import { useEffect, useRef, useState } from "react";
import {
  Alert,
  AutoComplete,
  Button,
  Card,
  Checkbox,
  Collapse,
  Form,
  Input,
  InputNumber,
  Segmented,
  Select,
  Skeleton,
  Space,
  Tag,
  Typography,
} from "antd";
import { ArrowRightOutlined, SearchOutlined } from "@ant-design/icons";
import {
  ApiError,
  type Asset,
  type SettingsView,
  type TaskParams,
  type WebApi,
} from "../api";
import {
  languageOptions,
  ModelFields,
  modelDefaults,
  providerLabels,
} from "../configuration";

const today = () => {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
};
const validTicker = (value: string) =>
  /^[A-Za-z0-9._^=\-]{1,32}$/.test(value.trim());
interface StartValues extends TaskParams {
  query: string;
}

export function Start({
  api,
  navigate,
}: {
  api: WebApi;
  navigate: (path: string) => void;
}) {
  const [form] = Form.useForm<StartValues>();
  const [settings, setSettings] = useState<SettingsView>();
  const [loadFailed, setLoadFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Asset>();
  const [results, setResults] = useState<Asset[]>([]);
  const [searchState, setSearchState] = useState<
    "idle" | "loading" | "ready" | "unavailable"
  >("idle");
  const [manual, setManual] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const searchController = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const provider =
    Form.useWatch("provider", form) ?? settings?.provider ?? "openai";

  useEffect(() => {
    let active = true;
    setLoadFailed(false);
    api
      .getSettings()
      .then((value) => {
        if (!active) return;
        form.setFieldsValue({
          date: today(),
          depth: "standard",
          asset_type: "auto",
          language: value.language,
          provider: value.provider,
          quick_model: value.quick_model,
          deep_model: value.deep_model,
          checkpoint_enabled: value.checkpoint_enabled,
        });
        setSettings(value);
      })
      .catch(() => {
        if (active) setLoadFailed(true);
      });
    return () => {
      active = false;
    };
  }, [api, attempt, form]);

  useEffect(() => {
    const controller = new AbortController();
    searchController.current = controller;
    const id = ++generation.current;
    const text = query.trim();
    if (selected || text.length < 2 || text.length > 64) {
      setSearchState("idle");
      return () => controller.abort();
    }
    setSearchState("loading");
    const timer = setTimeout(() => {
      api
        .searchSymbols(text, controller.signal)
        .then((response) => {
          if (controller.signal.aborted || generation.current !== id) return;
          setResults(response.results);
          setSearchState(response.unavailable ? "unavailable" : "ready");
        })
        .catch(() => {
          if (!controller.signal.aborted && generation.current === id) {
            setResults([]);
            setSearchState("unavailable");
          }
        });
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [api, query, selected]);

  async function submit(values: StartValues) {
    setError("");
    if (!settings) return;
    if (
      !["ollama", "bedrock"].includes(provider) &&
      !settings.keys[provider]?.configured
    ) {
      const message = `请先在设置中配置 ${providerLabels[provider] ?? provider} API Key。`;
      form.setFields([{ name: "provider", errors: [message] }]);
      setError(message);
      return;
    }
    const { query: _query, ...params } = values;
    for (const field of [
      "max_debate_rounds",
      "max_risk_discuss_rounds",
    ] as const) {
      if (params[field] == null) delete params[field];
    }
    setSubmitting(true);
    try {
      const task = await api.createTask({
        ...params,
        ticker: (selected?.symbol ?? query).trim().toUpperCase(),
        name: selected?.name ?? "",
      });
      navigate(`/tasks/${encodeURIComponent(task.id)}`);
    } catch (failure) {
      if (failure instanceof ApiError)
        form.setFields(
          Object.entries(failure.fields).map(([name, message]) => ({
            name: (name === "ticker" ? "query" : name) as keyof StartValues,
            errors: [message],
          })),
        );
      setError("无法创建分析任务，请检查参数、供应商密钥和网络后重试。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <h1>今天研究什么？</h1>
          <p>
            输入交易标的，Agent 团队将从市场、新闻、基本面与风险角度完成分析。
          </p>
        </div>
      </div>
      {loadFailed ? (
        <Alert
          type="error"
          showIcon
          message="无法加载默认设置"
          action={
            <Button
              aria-label="重试"
              onClick={() => setAttempt((value) => value + 1)}
            >
              重试
            </Button>
          }
        />
      ) : !settings ? (
        <Card>
          <Skeleton active />
        </Card>
      ) : (
        <div className="start-layout">
          <Card title="新建分析" className="analysis-card">
            <Form
              form={form}
              layout="vertical"
              onFinish={submit}
              requiredMark={false}
              disabled={submitting}
              validateTrigger="onBlur"
              noValidate
            >
              <div className="form-grid">
                <Form.Item
                  name="query"
                  label="股票 / 资产代码"
                  rules={[
                    {
                      validator: async (_, value) => {
                        const text = String(value ?? "").trim();
                        if (
                          !selected &&
                          validTicker(text) &&
                          searchState === "loading" &&
                          !manual
                        )
                          throw new Error("请等待搜索或确认按代码手动输入。");
                        const companyMatch = results.some(
                          (asset) =>
                            asset.symbol.toUpperCase() !== text.toUpperCase() &&
                            asset.name
                              .toLowerCase()
                              .includes(text.toLowerCase()),
                        );
                        if (
                          !selected &&
                          !manual &&
                          validTicker(text) &&
                          (/^[A-Za-z]{2,}$/.test(text) || companyMatch)
                        )
                          throw new Error(
                            "请选择搜索结果或确认按代码手动输入。",
                          );
                        if (!selected && !validTicker(text))
                          throw new Error(
                            "请选择搜索结果或输入有效代码，例如 NVDA、0700.HK。",
                          );
                      },
                    },
                  ]}
                  extra={
                    <span aria-live="polite">
                      {selected
                        ? `${selected.name} · ${selected.exchange}`
                        : searchState === "unavailable"
                          ? "搜索暂不可用，仍可直接输入有效代码。"
                          : searchState === "loading"
                            ? "正在搜索…"
                            : searchState === "ready" && !results.length
                              ? "未找到结果，可直接输入有效代码。"
                              : "输入代码或英文名称；至少 2 个字符开始搜索。"}
                    </span>
                  }
                >
                  <AutoComplete
                    virtual={false}
                    options={results.map((asset) => ({
                      value: asset.symbol,
                      label: (
                        <div className="asset-option">
                          <strong>{asset.symbol}</strong>
                          <span>{asset.name}</span>
                          <small>
                            {asset.exchange} · {asset.type}
                          </small>
                        </div>
                      ),
                    }))}
                    onChange={(value) => {
                      searchController.current?.abort();
                      ++generation.current;
                      setQuery(value);
                      setSelected(undefined);
                      setManual(false);
                      setResults([]);
                    }}
                    onSelect={(value) => {
                      const asset = results.find(
                        (item) => item.symbol === value,
                      );
                      setSelected(asset);
                      setQuery(value);
                      setResults([]);
                    }}
                    notFoundContent={
                      searchState === "loading" ? "正在搜索…" : "没有匹配结果"
                    }
                    popupMatchSelectWidth
                  >
                    <Input
                      prefix={<SearchOutlined aria-hidden />}
                      placeholder="NVDA、NVIDIA、BTC-USD"
                      autoComplete="off"
                    />
                  </AutoComplete>
                </Form.Item>
                <Form.Item
                  name="date"
                  label="分析日期"
                  rules={[
                    { required: true, message: "请选择分析日期" },
                    {
                      validator: async (_, value) => {
                        const [year, month, day] = String(value ?? "")
                          .split("-")
                          .map(Number);
                        const calendar = new Date(`${value}T00:00:00Z`);
                        if (
                          !/^\d{4}-\d{2}-\d{2}$/.test(value ?? "") ||
                          value > today() ||
                          year < 1 ||
                          calendar.getUTCFullYear() !== year ||
                          calendar.getUTCMonth() + 1 !== month ||
                          calendar.getUTCDate() !== day
                        )
                          throw new Error("请选择不晚于今天的有效日期");
                      },
                    },
                  ]}
                >
                  <Input type="date" max={today()} />
                </Form.Item>
              </div>
              {!selected && validTicker(query) && (
                <div className="manual-option">
                  <Checkbox
                    checked={manual}
                    onChange={(event) => setManual(event.target.checked)}
                  >
                    将「{query.toUpperCase()}」作为代码手动输入
                  </Checkbox>
                </div>
              )}
              <Form.Item name="depth" label="分析深度">
                <Segmented
                  block
                  options={[
                    { value: "quick", label: "快速" },
                    { value: "standard", label: "标准" },
                    { value: "deep", label: "深入" },
                  ]}
                />
              </Form.Item>
              <div className="form-grid">
                <Form.Item
                  name="language"
                  label="报告语言"
                  rules={[{ required: true }]}
                >
                  <Select
                    options={[
                      ...languageOptions,
                      ...(!languageOptions.some(
                        (option) => option.value === settings.language,
                      )
                        ? [
                            {
                              value: settings.language,
                              label: settings.language,
                            },
                          ]
                        : []),
                    ]}
                  />
                </Form.Item>
                <Form.Item name="asset_type" label="资产类型">
                  <Select
                    options={[
                      { value: "auto", label: "自动识别" },
                      { value: "stock", label: "股票" },
                      { value: "crypto", label: "加密资产" },
                    ]}
                  />
                </Form.Item>
              </div>
              <Collapse
                ghost
                items={[
                  {
                    key: "advanced",
                    forceRender: true,
                    label: "高级设置",
                    extra: (
                      <span className="muted">模型、分析师与辩论轮次</span>
                    ),
                    children: (
                      <>
                        <Form.Item
                          name="provider"
                          label="模型供应商"
                          rules={[{ required: true }]}
                        >
                          <Select
                            options={Object.entries(providerLabels).map(
                              ([value, label]) => ({ value, label }),
                            )}
                            onChange={(value) =>
                              form.setFieldsValue(modelDefaults(value))
                            }
                          />
                        </Form.Item>
                        <ModelFields provider={provider} />
                        <Form.Item
                          name="analysts"
                          label="参与分析师"
                          extra="留空使用适合当前资产的全部分析师；加密资产不支持基本面分析。"
                        >
                          <Select
                            mode="multiple"
                            allowClear
                            placeholder="使用默认分析师"
                            options={[
                              { value: "market", label: "市场与技术" },
                              { value: "social", label: "情绪" },
                              { value: "news", label: "新闻与宏观" },
                              { value: "fundamentals", label: "基本面" },
                            ]}
                            onChange={(value) => {
                              if (!value.length)
                                form.setFieldValue("analysts", undefined);
                            }}
                          />
                        </Form.Item>
                        <div className="form-grid">
                          {(
                            [
                              "max_debate_rounds",
                              "max_risk_discuss_rounds",
                            ] as const
                          ).map((name, index) => (
                            <Form.Item
                              key={name}
                              name={name}
                              label={
                                index === 0 ? "研究辩论轮次" : "风险讨论轮次"
                              }
                            >
                              <InputNumber
                                min={1}
                                max={5}
                                precision={0}
                                placeholder="跟随分析深度"
                                changeOnWheel={false}
                              />
                            </Form.Item>
                          ))}
                        </div>
                        <Form.Item
                          name="checkpoint_enabled"
                          valuePropName="checked"
                        >
                          <Checkbox>启用检查点恢复</Checkbox>
                        </Form.Item>
                      </>
                    ),
                  },
                ]}
              />
              {error && (
                <Alert
                  className="form-alert"
                  type="error"
                  showIcon
                  message={error}
                  action={
                    <Button type="link" onClick={() => navigate("/settings")}>
                      打开设置
                    </Button>
                  }
                />
              )}
              <div className="form-footer">
                <Typography.Text type="secondary">
                  分析结果用于研究参考
                </Typography.Text>
                <Button
                  type="primary"
                  aria-label="开始分析"
                  htmlType="submit"
                  loading={submitting}
                  icon={<ArrowRightOutlined aria-hidden />}
                  iconPosition="end"
                >
                  开始分析
                </Button>
              </div>
            </Form>
          </Card>
          <aside className="start-aside">
            <Card title="当前默认配置">
              <Space direction="vertical" size="middle">
                <Tag color="success">
                  {providerLabels[settings.provider] ?? settings.provider}
                </Tag>
                <div>
                  <span className="muted">快速推理模型</span>
                  <p className="model-id">{settings.quick_model}</p>
                </div>
                <div>
                  <span className="muted">深度推理模型</span>
                  <p className="model-id">{settings.deep_model}</p>
                </div>
                <Button onClick={() => navigate("/settings")}>
                  管理模型与 API Key
                </Button>
              </Space>
            </Card>
            <Card title="研究流程">
              <p className="muted">
                分析师团队 → 多空研究 → 交易员 → 风险团队 → 组合经理
              </p>
              <p className="muted">
                任务在后台执行。创建后可查看阶段产出，也可从任务记录重新打开。
              </p>
              <Button type="link" onClick={() => navigate("/history")}>
                查看任务记录 <ArrowRightOutlined />
              </Button>
            </Card>
          </aside>
        </div>
      )}
    </>
  );
}
