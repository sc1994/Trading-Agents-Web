import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Form,
  Grid,
  Input,
  Select,
  Skeleton,
  Space,
  Switch,
  Tabs,
  Tag,
  Tooltip,
} from "antd";
import {
  DeleteOutlined,
  InfoCircleOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import { type SettingsChanges, type SettingsView, type WebApi } from "../api";
import {
  keyLabel,
  languageOptions,
  ModelFields,
  modelDefaults,
  providerLabels,
} from "../configuration";

export function Settings({ api }: { api: WebApi }) {
  const [form] = Form.useForm<SettingsChanges>();
  const screens = Grid.useBreakpoint();
  const [settings, setSettings] = useState<SettingsView>();
  const [passwords, setPasswords] = useState<Record<string, string>>({});
  const [clearKeys, setClearKeys] = useState<string[]>([]);
  const [loadFailed, setLoadFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{
    type: "success" | "error" | "info";
    text: string;
  }>();
  const [testing, setTesting] = useState<string>();
  const provider =
    Form.useWatch("provider", form) ?? settings?.provider ?? "openai";
  useEffect(() => {
    let active = true;
    setLoadFailed(false);
    api
      .getSettings()
      .then((value) => {
        if (active) {
          setSettings(value);
          const { keys: _keys, ...defaults } = value;
          form.setFieldsValue(defaults);
        }
      })
      .catch(() => {
        if (active) setLoadFailed(true);
      });
    return () => {
      active = false;
    };
  }, [api, attempt, form]);

  async function save(values: SettingsChanges) {
    setSaving(true);
    setNotice(undefined);
    try {
      const result = await api.saveSettings({
        ...values,
        keys: Object.fromEntries(
          Object.entries(passwords).filter(
            ([name, value]) => value.trim() && !clearKeys.includes(name),
          ),
        ),
        clear_keys: clearKeys,
      });
      setSettings(result);
      setPasswords({});
      setClearKeys([]);
      const { keys: _keys, ...defaults } = result;
      form.setFieldsValue(defaults);
      const remaining = clearKeys.filter(
        (name) => result.keys[name]?.configured,
      );
      setNotice(
        remaining.length
          ? {
              type: "info",
              text: `设置已保存；服务器仍提供 ${remaining.map(keyLabel).join("、")} 密钥，如需停用请移除服务器环境配置。`,
            }
          : { type: "success", text: "设置已保存" },
      );
    } catch {
      setNotice({
        type: "error",
        text: "保存失败，请检查模型、密钥格式与网络后重试。",
      });
    } finally {
      setSaving(false);
    }
  }
  async function testConnection(name: string) {
    setTesting(name);
    setNotice(undefined);
    try {
      const result = await api.testConnection(name);
      setNotice({
        type: result.ok ? "success" : "error",
        text: result.ok
          ? `${keyLabel(name)} 连接成功`
          : `${keyLabel(name)} 连接测试失败或暂不支持，请检查已保存的配置。`,
      });
    } catch {
      setNotice({ type: "error", text: "连接测试失败，请稍后重试。" });
    } finally {
      setTesting(undefined);
    }
  }
  function credentialFields(dataSource: boolean) {
    const entries = Object.entries(settings?.keys ?? {}).filter(
      ([name]) => ["fred", "alpha_vantage"].includes(name) === dataSource,
    );
    return (
      <div>
        {entries.map(([name, status]) => (
          <section key={name} className="credential-row">
            <div className="credential-heading">
              <h3>{keyLabel(name)}</h3>
              <Tag
                color={
                  clearKeys.includes(name)
                    ? "warning"
                    : status.configured
                      ? "success"
                      : "default"
                }
              >
                {clearKeys.includes(name)
                  ? "保存后清除"
                  : status.configured
                    ? `已配置${status.last4 ? ` · 尾号 ${status.last4}` : ""}`
                    : "未配置"}
              </Tag>
            </div>
            <div className="credential-controls">
              <Form.Item
                label={`${keyLabel(name)} API Key`}
                htmlFor={`key-${name}`}
                extra="留空保留原密钥；输入新值后保存以替换。"
              >
                <Input.Password
                  id={`key-${name}`}
                  autoComplete="new-password"
                  maxLength={4096}
                  placeholder="输入新密钥"
                  value={passwords[name] ?? ""}
                  disabled={clearKeys.includes(name) || saving}
                  onChange={(event) =>
                    setPasswords((current) => ({
                      ...current,
                      [name]: event.target.value,
                    }))
                  }
                />
              </Form.Item>
              <Space wrap>
                <Tooltip title="仅测试服务器已保存的密钥；更改后请先保存">
                  {!dataSource && (
                    <Button
                      aria-label={`测试 ${keyLabel(name)} 连接`}
                      loading={testing === name}
                      disabled={
                        !!testing ||
                        !!passwords[name] ||
                        clearKeys.includes(name)
                      }
                      onClick={() => testConnection(name)}
                    >
                      测试连接
                    </Button>
                  )}
                </Tooltip>
                <Button
                  danger={!clearKeys.includes(name)}
                  icon={<DeleteOutlined />}
                  aria-label={
                    clearKeys.includes(name)
                      ? `撤销清除 ${keyLabel(name)} 密钥`
                      : `清除 ${keyLabel(name)} 密钥`
                  }
                  disabled={
                    saving || (!status.configured && !clearKeys.includes(name))
                  }
                  onClick={() => {
                    setClearKeys((current) =>
                      current.includes(name)
                        ? current.filter((item) => item !== name)
                        : [...current, name],
                    );
                    setPasswords((current) => ({ ...current, [name]: "" }));
                  }}
                >
                  {clearKeys.includes(name) ? "撤销清除" : "清除"}
                </Button>
              </Space>
            </div>
          </section>
        ))}
      </div>
    );
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>模型与 API 设置</h1>
          <p>配置模型供应商、数据源和默认分析参数，密钥仅保存在当前服务器。</p>
        </div>
        <Button
          type="primary"
          aria-label="保存设置"
          icon={<SaveOutlined aria-hidden />}
          loading={saving}
          disabled={!settings}
          onClick={() => form.submit()}
        >
          保存设置
        </Button>
      </div>
      {notice && (
        <Alert
          className="form-alert"
          type={notice.type}
          showIcon
          message={notice.text}
        />
      )}
      {loadFailed ? (
        <Alert
          type="error"
          showIcon
          message="无法加载设置"
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
        <Form
          form={form}
          layout="vertical"
          requiredMark={false}
          onFinish={save}
          disabled={saving}
        >
          <Tabs
            className="settings-tabs"
            tabPosition={screens.md ? "left" : "top"}
            items={[
              {
                key: "providers",
                label: "模型供应商",
                forceRender: true,
                children: (
                  <Card
                    title="模型供应商"
                    extra={
                      <Tooltip title="密码框仅遮挡屏幕；保存后接口不返回完整密钥。">
                        <InfoCircleOutlined aria-label="密钥说明" />
                      </Tooltip>
                    }
                  >
                    {credentialFields(false)}
                  </Card>
                ),
              },
              {
                key: "data",
                label: "数据源",
                forceRender: true,
                children: (
                  <Card title="数据源">
                    <p className="muted">
                      Yahoo 标的搜索无需 API Key。其他数据源按需配置。
                    </p>
                    {credentialFields(true)}
                  </Card>
                ),
              },
              {
                key: "models",
                label: "默认模型",
                forceRender: true,
                children: (
                  <Card title="默认模型">
                    <Form.Item
                      name="provider"
                      label="默认供应商"
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
                  </Card>
                ),
              },
              {
                key: "preferences",
                label: "分析偏好",
                forceRender: true,
                children: (
                  <Card title="分析偏好">
                    <Form.Item
                      name="language"
                      label="默认报告语言"
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
                    <Form.Item
                      name="checkpoint_enabled"
                      label="启用检查点恢复"
                      valuePropName="checked"
                      extra="任务中断后，有兼容检查点时可继续分析。"
                    >
                      <Switch />
                    </Form.Item>
                  </Card>
                ),
              },
            ]}
          />
        </Form>
      )}
    </>
  );
}
