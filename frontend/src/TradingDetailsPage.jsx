import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { api } from './api';

function statusColor(status) {
  const value = String(status || '').toUpperCase();
  if (value.includes('FILLED')) return 'green';
  if (value.includes('CANCEL') || value.includes('FAILED')) return 'red';
  if (value.includes('PART')) return 'orange';
  return 'blue';
}

export default function TradingDetailsPage() {
  const [form] = Form.useForm();
  const [orders, setOrders] = useState([]);
  const [deals, setDeals] = useState([]);
  const [loading, setLoading] = useState(false);

  const filterValues = Form.useWatch([], form);

  const summary = useMemo(() => {
    const filledOrders = orders.filter((item) => String(item.order_status || '').toUpperCase() === 'FILLED_ALL').length;
    const totalDealQty = deals.reduce((sum, item) => sum + Number(item.qty || 0), 0);
    return {
      orderCount: orders.length,
      filledOrders,
      dealCount: deals.length,
      totalDealQty,
    };
  }, [orders, deals]);

  async function loadData(refresh = true) {
    setLoading(true);
    const values = form.getFieldsValue();
    try {
      const payload = {
        market: values.market || 'HK',
        tradeEnv: values.tradeEnv || 'SIMULATE',
        accId: values.accId,
        code: values.code,
        refresh,
        limit: values.limit || 200,
      };
      const [orderRows, dealRows] = await Promise.all([
        api.listTradeOrders(payload),
        api.listTradeDeals(payload),
      ]);
      setOrders(orderRows);
      setDeals(dealRows);
    } catch (error) {
      message.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    form.setFieldsValue({
      market: 'HK',
      tradeEnv: 'SIMULATE',
      accId: 12105073,
      code: 'HK.03690',
      limit: 100,
    });
    loadData(true);
    const timer = window.setInterval(() => loadData(false), 5000);
    return () => window.clearInterval(timer);
  }, []);

  const orderColumns = [
    { title: '订单号', dataIndex: 'broker_order_id', key: 'broker_order_id', width: 120 },
    { title: '标的', dataIndex: 'code', key: 'code', width: 120 },
    { title: '方向', dataIndex: 'trd_side', key: 'trd_side', width: 90 },
    { title: '类型', dataIndex: 'order_type', key: 'order_type', width: 140 },
    {
      title: '状态',
      dataIndex: 'order_status',
      key: 'order_status',
      width: 120,
      render: (value) => <Tag color={statusColor(value)}>{value}</Tag>,
    },
    { title: '委托价', dataIndex: 'price', key: 'price', width: 90 },
    { title: '委托量', dataIndex: 'qty', key: 'qty', width: 90 },
    { title: '成交量', dataIndex: 'dealt_qty', key: 'dealt_qty', width: 90 },
    { title: '成交均价', dataIndex: 'dealt_avg_price', key: 'dealt_avg_price', width: 100 },
    { title: '来源', dataIndex: 'source', key: 'source', width: 100, render: (value) => value || 'manual' },
    { title: '备注', dataIndex: 'note', key: 'note', ellipsis: true },
    { title: '更新时间', dataIndex: 'updated_time', key: 'updated_time', width: 160 },
  ];

  const dealColumns = [
    { title: '成交号', dataIndex: 'deal_id', key: 'deal_id', width: 130 },
    { title: '订单号', dataIndex: 'broker_order_id', key: 'broker_order_id', width: 120 },
    { title: '标的', dataIndex: 'code', key: 'code', width: 120 },
    { title: '方向', dataIndex: 'trd_side', key: 'trd_side', width: 90 },
    { title: '成交价', dataIndex: 'price', key: 'price', width: 90 },
    { title: '成交量', dataIndex: 'qty', key: 'qty', width: 90 },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (value) => value || '-' },
    { title: '成交时间', dataIndex: 'create_time', key: 'create_time', width: 160 },
  ];

  return (
    <div className="page-shell">
      <Card className="hero-card hero-card-sky" bordered={false}>
        <Typography.Text className="hero-kicker">TRADING DETAILS</Typography.Text>
        <Typography.Title level={2}>交易明细页</Typography.Title>
        <Typography.Paragraph className="hero-text">
          查看后端记录的订单与成交明细。默认每 5 秒自动刷新一次，也可以手动刷新，方便观察下单后订单状态和成交详情变化。
        </Typography.Paragraph>
        <Row gutter={16}>
          <Col span={6}><Statistic title="订单数" value={summary.orderCount} /></Col>
          <Col span={6}><Statistic title="全成订单" value={summary.filledOrders} /></Col>
          <Col span={6}><Statistic title="成交笔数" value={summary.dealCount} /></Col>
          <Col span={6}><Statistic title="累计成交量" value={summary.totalDealQty} /></Col>
        </Row>
      </Card>

      <Card className="control-card" title="筛选条件" extra={<Button icon={<ReloadOutlined />} onClick={() => loadData(true)}>立即刷新</Button>}>
        <Form form={form} layout="vertical" onFinish={() => loadData(true)}>
          <Row gutter={16}>
            <Col span={4}>
              <Form.Item name="market" label="市场">
                <Select options={[{ value: 'HK', label: 'HK' }, { value: 'US', label: 'US' }, { value: 'CN', label: 'CN' }]} />
              </Form.Item>
            </Col>
            <Col span={4}>
              <Form.Item name="tradeEnv" label="环境">
                <Select options={[{ value: 'SIMULATE', label: 'SIMULATE' }, { value: 'REAL', label: 'REAL' }]} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="accId" label="账户 ID">
                <InputNumber style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={5}>
              <Form.Item name="code" label="标的">
                <Input placeholder="HK.03690" />
              </Form.Item>
            </Col>
            <Col span={3}>
              <Form.Item name="limit" label="条数">
                <InputNumber min={1} max={500} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={2} style={{ display: 'flex', alignItems: 'end' }}>
              <Button type="primary" htmlType="submit" loading={loading}>查询</Button>
            </Col>
          </Row>
        </Form>
      </Card>

      <Row gutter={[16, 16]}>
        <Col span={24}>
          <Card className="control-card" title="订单列表">
            <Table
              rowKey={(record) => `${record.broker_order_id}-${record.recorded_at}`}
              dataSource={orders}
              columns={orderColumns}
              loading={loading}
              pagination={{ pageSize: 10 }}
              scroll={{ x: 1400 }}
            />
          </Card>
        </Col>
        <Col span={24}>
          <Card className="control-card" title="成交列表">
            <Table
              rowKey={(record) => record.deal_id}
              dataSource={deals}
              columns={dealColumns}
              loading={loading}
              pagination={{ pageSize: 10 }}
              scroll={{ x: 1000 }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
