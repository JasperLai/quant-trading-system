import { DesktopOutlined, PlayCircleOutlined } from '@ant-design/icons';
import { ConfigProvider, Layout, Menu, Tag, Typography } from 'antd';
import { Link, Route, Routes, useLocation } from 'react-router-dom';
import StrategyCatalogPage from './StrategyCatalogPage';
import StrategyRunsPage from './StrategyRunsPage';

const { Header, Sider, Content } = Layout;

export default function App() {
  const location = useLocation();

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
                key: '/runs',
                icon: <PlayCircleOutlined />,
                label: <Link to="/runs">启动停止</Link>,
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
            <Tag className="header-tag" color="gold">
              OpenD Connected UI
            </Tag>
          </Header>
          <Content className="content">
            <Routes>
              <Route path="/" element={<StrategyCatalogPage />} />
              <Route path="/strategies" element={<StrategyCatalogPage />} />
              <Route path="/runs" element={<StrategyRunsPage />} />
            </Routes>
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  );
}
