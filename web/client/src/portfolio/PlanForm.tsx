import { useState } from "react";
import {
  Alert,
  Button,
  Form,
  Input,
  InputNumber,
  Segmented,
  Switch,
} from "antd";
import { SaveOutlined } from "@ant-design/icons";
import { InstrumentPicker } from "./InstrumentPicker";
import {
  PortfolioError,
  type Instrument,
  type Plan,
  type PlanInput,
  type PortfolioApi,
} from "./api";

export const horizonLabels = { short: "短线", medium: "中线", long: "长期" };
export function PlanForm({
  api,
  plan,
  initialInstrument,
  onSaved,
  onCancel,
}: {
  api: PortfolioApi;
  plan?: Plan;
  initialInstrument?: Instrument;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [form] = Form.useForm<PlanInput>();
  const [selected, setSelected] = useState<Instrument | undefined>(
    plan?.instrument ?? initialInstrument,
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function save(values: PlanInput) {
    if (!selected) {
      setError("请先选择已确认的 A 股股票。");
      return;
    }
    setSaving(true);
    setError("");
    const input = {
      ...values,
      symbol: selected.symbol,
      reason: values.reason ?? "",
      lower: values.lower ?? null,
      upper: values.upper ?? null,
      review_date: values.review_date || null,
      cost_pending: values.cost_pending ?? false,
    };
    try {
      if (plan) {
        const { symbol: _symbol, ...changes } = input;
        await api.updatePlan(plan.id, plan.revision, changes);
      } else await api.createPlan(input);
      onSaved();
    } catch (failure) {
      setError(
        failure instanceof PortfolioError
          ? failure.message
          : "保存失败，当前输入已保留。",
      );
    } finally {
      setSaving(false);
    }
  }
  return (
    <Form
      form={form}
      layout="vertical"
      onFinish={save}
      requiredMark={false}
      initialValues={plan ?? { horizon: "medium", cost_pending: false }}
    >
      {error && (
        <Alert
          showIcon
          type="error"
          message={error}
          className="portfolio-alert"
        />
      )}
      <Form.Item label="股票" required>
        <InstrumentPicker
          api={api}
          value={selected}
          onChange={setSelected}
          disabled={!!plan}
        />
      </Form.Item>
      <Form.Item name="horizon" label="投资周期">
        <Segmented
          block
          options={Object.entries(horizonLabels).map(([value, label]) => ({
            value,
            label,
          }))}
        />
      </Form.Item>
      <div className="form-grid">
        <Form.Item
          name="shares"
          label="持有股数"
          rules={[{ required: true, message: "请填写股数" }]}
        >
          <InputNumber
            style={{ width: "100%" }}
            min={1}
            max={1000000000}
            precision={0}
          />
        </Form.Item>
        <Form.Item
          name="cost"
          label="每股成本（元）"
          rules={[{ required: true, message: "请填写每股成本" }]}
        >
          <InputNumber stringMode style={{ width: "100%" }} precision={6} />
        </Form.Item>
      </div>
      <Form.Item name="reason" label="买入理由">
        <Input.TextArea rows={2} maxLength={2000} />
      </Form.Item>
      <div className="form-grid">
        <Form.Item name="lower" label="下观察线（可选）">
          <InputNumber stringMode precision={6} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="upper" label="上观察线（可选）">
          <InputNumber stringMode precision={6} style={{ width: "100%" }} />
        </Form.Item>
      </div>
      <Form.Item name="review_date" label="复核日期（可选）">
        <Input type="date" />
      </Form.Item>
      <Form.Item name="cost_pending" label="成本待核对" valuePropName="checked">
        <Switch />
      </Form.Item>
      <p className="portfolio-note">
        送转等公司行动后，请核对股数、成本及观察线。费用、分红和税费不自动计入。
      </p>
      <div className="portfolio-form-actions">
        <Button onClick={onCancel} disabled={saving}>
          取消
        </Button>
        <Button
          aria-label="保存计划"
          htmlType="submit"
          type="primary"
          loading={saving}
          icon={<SaveOutlined />}
        >
          保存计划
        </Button>
      </div>
    </Form>
  );
}
