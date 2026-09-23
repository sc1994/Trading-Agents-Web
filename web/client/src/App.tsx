import { ConfigProvider, Empty, Button, Tooltip } from "antd";
import zhCN from "antd/locale/zh_CN";
import {
  FileTextOutlined,
  HistoryOutlined,
  PlusOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import {
  BrowserRouter,
  Link,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { webApi } from "./api";
import { Start } from "./pages/Start";
import { Settings } from "./pages/Settings";
import { Run } from "./pages/Run";
import { Report } from "./pages/Report";
import { History } from "./pages/History";

const navigation = [
  { to: "/", label: "发起分析", mobile: "分析", icon: <PlusOutlined /> },
  {
    to: "/history",
    label: "任务记录",
    mobile: "任务",
    icon: <HistoryOutlined />,
  },
  {
    to: "/history?view=reports",
    label: "决策报告",
    mobile: "报告",
    icon: <FileTextOutlined />,
  },
  {
    to: "/settings",
    label: "模型设置",
    mobile: "设置",
    icon: <SettingOutlined />,
  },
];
function TaskPage({ report = false }: { report?: boolean }) {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const Page = report ? Report : Run;
  return <Page key={id} api={webApi} taskId={id} navigate={navigate} />;
}
function Workbench() {
  const navigate = useNavigate();
  const location = useLocation();
  const activePath = location.pathname + location.search;
  const activeNav = location.pathname.startsWith("/tasks/")
    ? "/history"
    : location.pathname.startsWith("/reports/")
      ? "/history?view=reports"
      : location.pathname === "/history"
        ? new URLSearchParams(location.search).get("view") === "reports"
          ? "/history?view=reports"
          : "/history"
        : location.pathname;
  const label =
    navigation.find((item) => item.to === activePath)?.label ??
    (location.pathname.startsWith("/tasks/") ? "任务运行" : "决策报告");
  const nav = (mobile: boolean) =>
    navigation.map((item) => (
      <Link
        key={item.label}
        to={item.to}
        className={activeNav === item.to ? "nav-item active" : "nav-item"}
        aria-current={activeNav === item.to ? "page" : undefined}
      >
        {item.icon}
        <span>{mobile ? item.mobile : item.label}</span>
      </Link>
    ));
  return (
    <div className="workbench">
      <a className="skip-link" href="#main">
        跳到主要内容
      </a>
      <aside className="sidebar">
        <Link to="/" className="brand">
          <span className="brand-mark">TA</span>
          <span>
            Trading Agent<small>研究工作台</small>
          </span>
        </Link>
        <nav aria-label="主要导航">{nav(false)}</nav>
        <div className="sidebar-note">
          个人研究工作台
          <br />
          <span>分析 · 依据 · 决策</span>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="desktop-breadcrumb">工作台 / {label}</div>
          <Link to="/" className="brand mobile-brand">
            <span className="brand-mark">TA</span>
            <span>Trading Agent</span>
          </Link>
          <Tooltip title="模型与 API 设置">
            <Button
              aria-label="打开模型设置"
              icon={<SettingOutlined />}
              onClick={() => navigate("/settings")}
            />
          </Tooltip>
        </header>
        <main id="main" tabIndex={-1}>
          <Routes>
            <Route
              path="/"
              element={<Start api={webApi} navigate={navigate} />}
            />
            <Route path="/settings" element={<Settings api={webApi} />} />
            <Route
              path="/history"
              element={
                <History
                  api={webApi}
                  navigate={navigate}
                  reportsOnly={
                    new URLSearchParams(location.search).get("view") ===
                    "reports"
                  }
                />
              }
            />
            <Route path="/tasks/:id" element={<TaskPage />} />
            <Route path="/reports/:id" element={<TaskPage report />} />
            <Route
              path="*"
              element={
                <Empty description="页面不存在">
                  <Link to="/">返回工作台</Link>
                </Empty>
              }
            />
          </Routes>
        </main>
      </div>
      <nav className="bottom-nav" aria-label="手机导航">
        {nav(true)}
      </nav>
    </div>
  );
}
export function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#1f7a55",
          colorSuccess: "#1f7a55",
          colorText: "#162b35",
          colorTextSecondary: "#647780",
          colorBorder: "#ccd7d6",
          borderRadius: 8,
          borderRadiusLG: 8,
          controlHeight: 42,
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
        },
        components: {
          Card: { headerFontSize: 16 },
          Segmented: {
            itemSelectedBg: "#e4f2eb",
            itemSelectedColor: "#1f7a55",
          },
        },
      }}
    >
      <BrowserRouter>
        <Workbench />
      </BrowserRouter>
    </ConfigProvider>
  );
}
