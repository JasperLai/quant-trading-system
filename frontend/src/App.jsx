import { useEffect, useState } from 'react';
import { DesktopOutlined, LineChartOutlined } from '@ant-design/icons';
import { ConfigProvider, Layout, Menu, Tag, Typography } from 'antd';
import { Link, Route, Routes, useLocation } from 'react-router-dom';
import { api } from './api';
import BacktestPage from './BacktestPage';
import StrategyRunsPage from './StrategyRunsPage';

const { Header, Sider, Content } = Layout;

export default function App() {
  const location = useLocation();
  const [systemStatus, setSystemStatus] = useState({
    openD: { connected: false, quoteLogin: false, detail: 'loading' },
  });

  useEffect(() => {
    let cancelled = false;

    async function loadStatus() {
      try {
        const data = await api.getSystemStatus();
        if (!cancelled) {
          setSystemStatus(data);
        }
      } catch (_) {
        if (!cancelled) {
          setSystemStatus({
            openD: { connected: false, quoteLogin: false, detail: 'unreachable' },
          });
        }
      }
    }

    loadStatus();
    const timer = window.setInterval(loadStatus, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const openDConnected = systemStatus?.openD?.connected && systemStatus?.openD?.quoteLogin;
  const openDColor = openDConnected
    ? 'success'
    : systemStatus?.openD?.connected
      ? 'warning'
      : 'error';
  const openDLabel = openDConnected
    ? 'OpenD 已连接'
    : systemStatus?.openD?.connected
      ? 'OpenD 已连接，行情未登录'
      : 'OpenD 未连接';

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#2f54eb',
          colorSuccess: '#52c41a',
          colorWarning: '#faad14',
          colorError: '#ff4d4f',
          colorBgLayout: '#f7f4ff',
          colorBgContainer: '#ffffff',
          borderRadius: 24,
          fontFamily: '"PingFang SC", "Helvetica Neue", sans-serif',
          boxShadowSecondary: '0 18px 50px rgba(100, 92, 187, 0.14)',
        },
        components: {
          Card: {
            borderRadiusLG: 28,
          },
          Button: {
            borderRadius: 999,
            controlHeight: 42,
          },
          Input: {
            borderRadius: 18,
          },
          InputNumber: {
            borderRadius: 18,
          },
          Select: {
            borderRadius: 18,
          },
          Table: {
            headerBg: '#fff7e6',
            borderColor: '#ffe7ba',
          },
        },
      }}
    >
      <Layout className="app-shell">
        <Sider width={256} className="sidebar">
          <div className="brand">
            <div className="brand-badge">ANTD 风格 · 卡通版</div>
            <Typography.Title level={3} className="brand-title">
              量化策略星球
            </Typography.Title>
            <Typography.Paragraph className="brand-subtitle">
              用更轻松的界面管理 Python 策略、运行实例和实时日志。
            </Typography.Paragraph>
          </div>
          <Menu
            className="nav-menu"
            mode="inline"
            selectedKeys={[location.pathname]}
            items={[
              {
                key: '/strategies',
                icon: <DesktopOutlined />,
                label: <Link to="/strategies">策略管理</Link>,
              },
              {
                key: '/backtests',
                icon: <LineChartOutlined />,
                label: <Link to="/backtests">回测验证</Link>,
              },
            ]}
          />
        </Sider>
        <Layout>
          <Header className="header">
            <div>
              <Typography.Text className="header-kicker">ANT DESIGN INSPIRED CONSOLE</Typography.Text>
              <Typography.Title level={2} style={{ margin: 0 }}>
                Python 策略服务管理
              </Typography.Title>
            </div>
            <Tag className="header-tag" color={openDColor}>
              {openDLabel}
            </Tag>
          </Header>
          <Content className="content">
            <Routes>
              <Route path="/" element={<StrategyRunsPage />} />
              <Route path="/strategies" element={<StrategyRunsPage />} />
              <Route path="/runs" element={<StrategyRunsPage />} />
              <Route path="/backtests" element={<BacktestPage />} />
            </Routes>
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  );
}
