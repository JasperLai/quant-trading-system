import { DesktopOutlined, PlayCircleOutlined } from '@ant-design/icons';
import { Layout, Menu, Typography } from 'antd';
import { Link, Route, Routes, useLocation } from 'react-router-dom';
import StrategyCatalogPage from './StrategyCatalogPage';
import StrategyRunsPage from './StrategyRunsPage';

const { Header, Sider, Content } = Layout;

export default function App() {
  const location = useLocation();

  return (
    <Layout className="app-shell">
      <Sider width={240} className="sidebar">
        <div className="brand">
          <Typography.Title level={4} style={{ color: '#fff', margin: 0 }}>
            量化策略控制台
          </Typography.Title>
        </div>
        <Menu
          theme="dark"
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
          <Typography.Title level={3} style={{ margin: 0 }}>
            Python 策略服务管理
          </Typography.Title>
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
  );
}
