import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Form,
  Grid,
  Input,
  Modal,
  Popconfirm,
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
  EditOutlined,
  LinkOutlined,
  PlusOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import {
  type ProviderEdit,
  type ProviderInput,
  type ProviderKind,
  type ProviderView,
  type SettingsChanges,
  type SettingsView,
  type WebApi,
} from "../api";
import {
  joinableBuiltIns,
  keyLabel,
  languageOptions,
  ModelFields,
  modelDefaults,
  providerOptions,
} from "../configuration";

type Notice = { type: "success" | "error" | "info"; text: string };
type DialogTarget = { mode: "add" } | { mode: "edit"; provider: ProviderView };
interface DialogValues {
  kind: ProviderKind;
  builtIn?: string;
  name?: string;
  base_url?: string;
}

export function Settings({ api }: { api: WebApi }) {
  const [form] = Form.useForm<SettingsChanges>();
  const screens = Grid.useBreakpoint();
  const [settings, setSettings] = useState<SettingsView>();
  const [passwords, setPasswords] = useState<Record<string, string>>({});
  const [clearKeys, setClearKeys] = useState<string[]>([]);
  const [dialog, setDialog] = useState<DialogTarget>();
  const [loadFailed, setLoadFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<Notice>();
  const [testing, setTesting] = useState<string>();
  const provider =
    Form.useWatch("provider", form) ?? settings?.provider ?? "openai";
  const providers = settings?.providers ?? [];
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

  function applyProviderResult(result: SettingsView, next: Notice) {
    setSettings(result);
    const { keys: _keys, ...defaults } = result;
    form.setFieldsValue(defaults);
    setDialog(undefined);
    setNotice(next);
  }
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
  async function testConnection(item: ProviderView) {
    setTesting(item.id);
    setNotice(undefined);
    try {
      const result = await api.testConnection(item.id);
      setNotice({
        type: result.ok ? "success" : "error",
        text: result.ok
          ? `${item.name} 连接成功`
          : `${item.name} 连接测试失败或暂不支持，请检查已保存的配置。`,
      });
    } catch {
      setNotice({ type: "error", text: "连接测试失败，请稍后重试。" });
    } finally {
      setTesting(undefined);
    }
  }
  async function removeProvider(id: string) {
    try {
      const result = await api.removeProvider(id);
      applyProviderResult(result, { type: "success", text: "供应商已移除" });
    } catch {
      setNotice({
        type: "error",
        text: "删除失败：该供应商可能是默认供应商或仍被未完成的任务使用。",
      });
    }
  }
  function credentialFields() {
    const entries = Object.entries(settings?.keys ?? {}).filter(([name]) =>
      ["fred", "alpha_vantage"].includes(name),
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
                      <Button
                        type="primary"
                        icon={<PlusOutlined aria-hidden />}
                        aria-label="加入供应商"
                        onClick={() => setDialog({ mode: "add" })}
                      >
                        加入供应商
                      </Button>
                    }
                  >
                    <p className="muted">
                      已加入的供应商显示在此。密钥仅保存在当前服务器，列表只展示掩码状态；修改密钥请在编辑对话框中输入新值。
                    </p>
                    <ul
                      className="provider-list"
                      aria-label="已加入的供应商"
                    >
                      {providers.map((item) => (
                        <li className="provider-row" key={item.id}>
                          <div className="provider-info">
                            <div className="provider-title">
                              <strong>{item.name}</strong>
                              <Tag>
                                {item.kind === "custom" ? "自定义" : "内置"}
                              </Tag>
                              {provider === item.id && (
                                <Tag color="blue">默认</Tag>
                              )}
                            </div>
                            {item.kind === "custom" && item.base_url && (
                              <div className="provider-url">
                                {item.base_url}
                              </div>
                            )}
                          </div>
                          <Tag
                            color={item.key.configured ? "success" : "default"}
                          >
                            {item.key.configured
                              ? `已配置${item.key.last4 ? ` · 尾号 ${item.key.last4}` : ""}`
                              : "未配置"}
                          </Tag>
                          <div className="provider-actions">
                            <Tooltip title="测试已保存的连接">
                              <Button
                                aria-label={`测试 ${item.name} 连接`}
                                icon={<LinkOutlined aria-hidden />}
                                loading={testing === item.id}
                                disabled={!!testing}
                                onClick={() => testConnection(item)}
                              />
                            </Tooltip>
                            <Tooltip title="编辑密钥与信息">
                              <Button
                                aria-label={`编辑 ${item.name}`}
                                icon={<EditOutlined aria-hidden />}
                                disabled={!!testing}
                                onClick={() =>
                                  setDialog({ mode: "edit", provider: item })
                                }
                              />
                            </Tooltip>
                            <Popconfirm
                              title={`删除后「${item.name}」将不可用，确定删除？`}
                              okText="确定删除"
                              cancelText="取消"
                              onConfirm={() => removeProvider(item.id)}
                            >
                              <Button
                                aria-label={`删除 ${item.name}`}
                                danger
                                icon={<DeleteOutlined aria-hidden />}
                              />
                            </Popconfirm>
                          </div>
                        </li>
                      ))}
                    </ul>
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
                    {credentialFields()}
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
                        options={providerOptions(providers)}
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
      {dialog && (
        <ProviderDialog
          api={api}
          target={dialog}
          providers={providers}
          onClose={() => setDialog(undefined)}
          onSaved={applyProviderResult}
        />
      )}
    </>
  );
}

function ProviderDialog({
  api,
  target,
  providers,
  onClose,
  onSaved,
}: {
  api: WebApi;
  target: DialogTarget;
  providers: ProviderView[];
  onClose(): void;
  onSaved(settings: SettingsView, notice: Notice): void;
}) {
  const [form] = Form.useForm<DialogValues>();
  const editing = target.mode === "edit" ? target.provider : undefined;
  const [kind, setKind] = useState<ProviderKind>(editing?.kind ?? "custom");
  const [key, setKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  async function submit(values: DialogValues) {
    setSaving(true);
    setFailed(false);
    const secret = key.trim();
    try {
      if (editing) {
        const edit: ProviderEdit = {};
        if (editing.kind === "custom") {
          edit.name = values.name?.trim();
          edit.base_url = values.base_url?.trim();
        }
        if (clearKey) edit.clear_key = true;
        else if (secret) edit.key = secret;
        const result = await api.editProvider(editing.id, edit);
        const ambient = clearKey && result.keys[editing.id]?.configured;
        onSaved(
          result,
          ambient
            ? {
                type: "info",
                text: `供应商已更新；服务器仍提供 ${keyLabel(editing.id)} 密钥，如需停用请移除服务器环境配置。`,
              }
            : { type: "success", text: "供应商已更新" },
        );
      } else if (kind === "built_in") {
        const input: ProviderInput = { kind: "built_in", id: values.builtIn };
        if (secret) input.key = secret;
        const result = await api.addProvider(input);
        onSaved(result, { type: "success", text: "供应商已加入" });
      } else {
        const input: ProviderInput = {
          kind: "custom",
          name: values.name?.trim() ?? "",
          base_url: values.base_url?.trim() ?? "",
        };
        if (secret) input.key = secret;
        const result = await api.addProvider(input);
        onSaved(result, { type: "success", text: "供应商已加入" });
      }
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  }
  return (
    <Modal
      title={editing ? `编辑 ${editing.name}` : "加入供应商"}
      open
      destroyOnHidden
      confirmLoading={saving}
      okText="保存"
      okButtonProps={{ "aria-label": "保存" }}
      cancelText="取消"
      cancelButtonProps={{ "aria-label": "取消" }}
      onCancel={onClose}
      onOk={form.submit}
    >
      {failed && (
        <Alert
          className="form-alert"
          type="error"
          showIcon
          message="保存失败，请检查名称、地址与密钥格式后重试。"
        />
      )}
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        initialValues={
          editing
            ? editing.kind === "custom"
              ? {
                  kind: "custom" as const,
                  name: editing.name,
                  base_url: editing.base_url ?? "",
                }
              : { kind: "built_in" as const }
            : { kind: "custom" as const }
        }
        onFinish={submit}
      >
        {!editing && (
          <Form.Item name="kind" label="类型" rules={[{ required: true }]}>
            <Select
              options={[
                { value: "custom", label: "自定义（OpenAI 兼容）" },
                { value: "built_in", label: "内置供应商" },
              ]}
              onChange={(value: ProviderKind) => setKind(value)}
            />
          </Form.Item>
        )}
        {kind === "built_in" ? (
          !editing && (
            <Form.Item
              name="builtIn"
              label="选择内置供应商"
              rules={[{ required: true, message: "请选择要加入的供应商" }]}
            >
              <Select options={joinableBuiltIns(providers)} />
            </Form.Item>
          )
        ) : (
          <>
            <Form.Item
              name="name"
              label="名称"
              rules={[
                { required: true, whitespace: true, message: "请输入供应商名称" },
                { max: 64 },
              ]}
            >
              <Input maxLength={64} placeholder="例如：云网关" />
            </Form.Item>
            <Form.Item
              name="base_url"
              label="接口地址"
              rules={[
                {
                  required: true,
                  whitespace: true,
                  message: "请输入接口地址",
                },
                { max: 2048 },
              ]}
              extra="仅支持 http/https 地址，例如 http://localhost:1234/v1。"
            >
              <Input maxLength={2048} placeholder="https://gateway.example/v1" />
            </Form.Item>
          </>
        )}
        <Form.Item
          name="key"
          label={editing ? `${editing.name} API Key` : "API Key"}
          extra={
            editing
              ? "留空保留原密钥；输入新值后保存以替换。"
              : "可选；本地服务通常无需密钥。"
          }
        >
          <Input.Password
            autoComplete="new-password"
            maxLength={4096}
            placeholder={editing ? "输入新密钥" : "输入 API Key"}
            value={key}
            disabled={clearKey || saving}
            onChange={(event) => setKey(event.target.value)}
          />
        </Form.Item>
        {editing && (
          <Button
            danger={!clearKey}
            icon={<DeleteOutlined />}
            aria-label={
              clearKey
                ? `撤销清除 ${editing.name} 密钥`
                : `清除 ${editing.name} 密钥`
            }
            disabled={saving || (!editing.key.configured && !clearKey)}
            onClick={() => {
              setClearKey((current) => !current);
              setKey("");
            }}
          >
            {clearKey ? "撤销清除" : "清除密钥"}
          </Button>
        )}
      </Form>
    </Modal>
  );
}
