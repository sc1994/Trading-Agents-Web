import { AutoComplete, Form, Input, Select } from "antd";

export const providerLabels: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google Gemini",
  xai: "xAI",
  deepseek: "DeepSeek",
  qwen: "Qwen · 国际",
  "qwen-cn": "Qwen · 中国",
  glm: "GLM · 国际",
  "glm-cn": "GLM · 中国",
  minimax: "MiniMax · 国际",
  "minimax-cn": "MiniMax · 中国",
  ollama: "Ollama",
  openai_compatible: "OpenAI 兼容服务",
  mistral: "Mistral",
  kimi: "Kimi",
  groq: "Groq",
  nvidia: "NVIDIA NIM",
  bedrock: "Amazon Bedrock",
};
export const keyLabel = (name: string) =>
  providerLabels[name] ??
  {
    fred: "FRED",
    alpha_vantage: "Alpha Vantage",
    azure: "Azure OpenAI",
    openrouter: "OpenRouter",
  }[name] ??
  name;
export const languageOptions = [
  "简体中文",
  "English",
  "繁體中文",
  "日本語",
].map((value) => ({ value, label: value }));
// Curated choices mirror the server catalog. Custom-model providers accept an ID.
const models: Record<string, [string[], string[]]> = {
  openai: [
    ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.4-mini"],
    ["gpt-5.6", "gpt-5.6-terra", "gpt-5.5", "gpt-5.4"],
  ],
  anthropic: [
    ["claude-sonnet-5", "claude-haiku-4-5"],
    ["claude-fable-5", "claude-opus-4-8", "claude-sonnet-5", "claude-opus-4-7"],
  ],
  google: [
    ["gemini-3.5-flash", "gemini-3.1-flash-lite"],
    ["gemini-3.1-pro-preview", "gemini-3.5-flash"],
  ],
  xai: [
    ["grok-4.3", "grok-4.20-0309-non-reasoning", "grok-build-0.1"],
    ["grok-4.3", "grok-4.20-0309-reasoning", "grok-4.20-multi-agent-0309"],
  ],
  deepseek: [["deepseek-v4-flash"], ["deepseek-v4-pro", "deepseek-v4-flash"]],
  qwen: [
    ["qwen3.7-plus", "qwen3.6-plus"],
    ["qwen3.7-max", "qwen3.6-max", "qwen3.7-plus"],
  ],
  glm: [
    ["glm-5.3-flash", "glm-5-turbo", "glm-4.5-air"],
    ["glm-5.3", "glm-5.2", "glm-5.1", "glm-4.7"],
  ],
  minimax: [
    ["MiniMax-M3", "MiniMax-M2.7-highspeed", "MiniMax-M2.5-highspeed"],
    ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5"],
  ],
  ollama: [
    ["qwen3:latest", "gpt-oss:latest", "glm-4.7-flash:latest"],
    ["glm-4.7-flash:latest", "gpt-oss:latest", "qwen3:latest"],
  ],
};
function choices(provider: string, mode: number) {
  return models[provider.replace(/-cn$/, "")]?.[mode] ?? [];
}
export function modelDefaults(provider: string) {
  return {
    quick_model: choices(provider, 0)[0] ?? "",
    deep_model: choices(provider, 1)[0] ?? "",
  };
}
export function ModelFields({ provider }: { provider: string }) {
  const strict = ["openai", "anthropic", "google", "xai"].includes(provider);
  return (
    <div className="form-grid">
      {(["quick_model", "deep_model"] as const).map((name, mode) => (
        <Form.Item
          key={name}
          name={name}
          label={mode === 0 ? "快速推理模型" : "深度推理模型"}
          rules={[
            {
              required: true,
              whitespace: true,
              message: "请选择或输入模型 ID",
            },
            { max: 128 },
          ]}
        >
          {strict ? (
            <Select
              showSearch
              options={choices(provider, mode).map((value) => ({
                value,
                label: value,
              }))}
            />
          ) : (
            <AutoComplete
              options={choices(provider, mode).map((value) => ({ value }))}
            >
              <Input placeholder="输入可用的模型 ID" />
            </AutoComplete>
          )}
        </Form.Item>
      ))}
    </div>
  );
}
