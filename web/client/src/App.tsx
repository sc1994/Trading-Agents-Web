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
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { webApi } from "./api";
import { Start } from "./pages/Start";
import { Settings } from "./pages/Settings";

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
function PendingPage({ title }: { title: string }) {
  return (
    <>
      <div className="page-heading">
        <h1>{title}</h1>
      </div>
      <div className="empty-page">
        <Empty description="此页面正在建设中，已提交的任务会继续在后台运行。">
          <Link to="/">返回发起分析</Link>
        </Empty>
      </div>
    </>
  );
}
function Workbench() {
  const navigate = useNavigate();
  const location = useLocation();
  const activePath = location.pathname + location.search;
  const label =
    navigation.find((item) => item.to === activePath)?.label ??
    (location.pathname.startsWith("/tasks/") ? "任务运行" : "决策报告");
  const nav = (mobile: boolean) =>
    navigation.map((item) => (
      <NavLink
        key={item.label}
        to={item.to}
        className={() =>
          activePath === item.to ? "nav-item active" : "nav-item"
        }
        aria-current={activePath === item.to ? "page" : undefined}
      >
        {item.icon}
        <span>{mobile ? item.mobile : item.label}</span>
      </NavLink>
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
                <PendingPage
                  title={
                    location.search === "?view=reports"
                      ? "决策报告"
                      : "任务记录"
                  }
                />
              }
            />
            <Route
              path="/tasks/:id"
              element={<PendingPage title="任务运行" />}
            />
            <Route
              path="/reports/:id"
              element={<PendingPage title="决策报告" />}
            />
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
