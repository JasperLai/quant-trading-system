import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { api } from './api';

function statusColor(status) {
  if (status === 'running') return 'green';
  if (status === 'failed') return 'red';
  return 'default';
}

export default function StrategyRunsPage() {
  const [form] = Form.useForm();
  const [strategies, setStrategies] = useState([]);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(false);
  const [logModal, setLogModal] = useState({ open: false, lines: [], runId: null });

  const selectedStrategyName = Form.useWatch('strategyName', form);
  const selectedStrategy = useMemo(
    () => strategies.find((item) => item.name === selectedStrategyName),
    [strategies, selectedStrategyName],
  );

  async function loadStrategies() {
    const data = await api.listStrategies();
    setStrategies(data);
    if (data.length && !form.getFieldValue('strategyName')) {
      const defaultStrategy = data[0];
      form.setFieldsValue({
        strategyName: defaultStrategy.name,
        codes: (defaultStrategy.params.codes || []).join(','),
        shortMa: defaultStrategy.params.short_ma,
        longMa: defaultStrategy.params.long_ma,
        orderQty: defaultStrategy.params.order_qty,
        maxPositionPerStock: defaultStrategy.params.max_position_per_stock,
      });
    }
  }

  async function loadRuns() {
    const data = await api.listRuns();
    setRuns(data);
  }

  useEffect(() => {
    loadStrategies();
    loadRuns();
    const timer = window.setInterval(loadRuns, 3000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!selectedStrategy) return;
    form.setFieldsValue({
      codes: (selectedStrategy.params.codes || []).join(','),
      shortMa: selectedStrategy.params.short_ma,
      longMa: selectedStrategy.params.long_ma,
      orderQty: selectedStrategy.params.order_qty,
      maxPositionPerStock: selectedStrategy.params.max_position_per_stock,
    });
  }, [selectedStrategy, form]);

  async function handleStart(values) {
    setLoading(true);
    try {
      await api.startRun({
        strategyName: values.strategyName,
        codes: values.codes
          .split(',')
          .map((item) => item.trim())
          .filter(Boolean),
        shortMa: values.shortMa,
        longMa: values.longMa,
        orderQty: values.orderQty,
        maxPositionPerStock: values.maxPositionPerStock,
      });
      message.success('策略已启动');
      loadRuns();
    } catch (error) {
      message.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleStop(runId) {
    await api.stopRun(runId);
    message.success('策略已停止');
    loadRuns();
  }

  async function handleLogs(runId) {
    const result = await api.readLogs(runId);
    setLogModal({ open: true, lines: result.lines || [], runId });
  }

  const columns = [
    { title: '运行 ID', dataIndex: 'id', key: 'id' },
    { title: '策略', dataIndex: 'strategyName', key: 'strategyName' },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (value) => <Tag color={statusColor(value)}>{value}</Tag>,
    },
    { title: 'PID', dataIndex: 'pid', key: 'pid' },
    {
      title: '标的',
      key: 'codes',
      render: (_, record) => (record.config.codes || []).join(', '),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button onClick={() => handleLogs(record.id)}>日志</Button>
          <Button danger disabled={record.status !== 'running'} onClick={() => handleStop(record.id)}>
            停止
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Typography.Title level={4}>启动停止页</Typography.Title>
      <Row gutter={[16, 16]}>
        <Col span={10}>
          <Card title="启动策略">
            <Form layout="vertical" form={form} onFinish={handleStart}>
              <Form.Item name="strategyName" label="策略" rules={[{ required: true }]}>
                <Select
                  options={strategies.map((item) => ({
                    label: item.title,
                    value: item.name,
                  }))}
                />
              </Form.Item>
              <Form.Item name="codes" label="标的列表">
                <Input placeholder="SZ.000001,HK.03690" />
              </Form.Item>
              <Form.Item name="shortMa" label="短期均线">
                <InputNumber min={1} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="longMa" label="长期均线">
                <InputNumber min={1} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="orderQty" label="单次下单数量">
                <InputNumber min={1} style={{ width: '100%' }} />
              </Form.Item>
              {selectedStrategy?.name === 'pyramiding_ma' ? (
                <Form.Item name="maxPositionPerStock" label="单标的最大仓位">
                  <InputNumber min={1} style={{ width: '100%' }} />
                </Form.Item>
              ) : null}
              <Button type="primary" htmlType="submit" loading={loading}>
                启动策略
              </Button>
            </Form>
          </Card>
        </Col>
        <Col span={14}>
          <Card title="运行中的策略">
            <Table rowKey="id" dataSource={runs} columns={columns} pagination={false} />
          </Card>
        </Col>
      </Row>
      <Modal
        open={logModal.open}
        onCancel={() => setLogModal({ open: false, lines: [], runId: null })}
        footer={null}
        width={900}
        title={`运行日志 ${logModal.runId || ''}`}
      >
        <pre className="log-panel">{logModal.lines.join('\n')}</pre>
      </Modal>
    </div>
  );
}
