import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Dropdown,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { MoreOutlined } from '@ant-design/icons';
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
  const runningCount = runs.filter((item) => item.status === 'running').length;

  async function loadStrategies() {
    const data = await api.listStrategies();
    setStrategies(data);
    if (data.length && !form.getFieldValue('strategyName')) {
      const defaultStrategy = data[0];
      form.setFieldsValue(buildStrategyFormDefaults(defaultStrategy));
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
    if (!logModal.open || !logModal.runId) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      handleLogs(logModal.runId, false);
    }, 2000);

    return () => window.clearInterval(timer);
  }, [logModal.open, logModal.runId]);

  useEffect(() => {
    if (!selectedStrategy) return;
    form.setFieldsValue(buildStrategyFormDefaults(selectedStrategy));
  }, [selectedStrategy, form]);

  async function handleStart(values) {
    setLoading(true);
    try {
      const strategyParams = {};
      (selectedStrategy?.param_fields || []).forEach((field) => {
        const value = values[field.name];
        if (value == null || value === '') return;
        strategyParams[field.name] = value;
      });
      await api.startRun({
        strategyName: values.strategyName,
        strategyParams,
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

  async function handleLogs(runId, openModal = true) {
    const result = await api.readLogs(runId);
    setLogModal((current) => ({
      open: openModal ? true : current.open,
      lines: result.lines || [],
      runId,
    }));
  }

  async function handleDelete(runId) {
    await api.deleteRun(runId);
    message.success('策略实例已删除');
    loadRuns();
  }

  function openDeleteConfirm(record) {
    Modal.confirm({
      title: '删除策略实例',
      content:
        record.status === 'running'
          ? '请先停止该实例，再执行删除。'
          : `确认删除实例 ${record.id} 吗？删除后将移除该实例记录和对应日志文件。`,
      okText: record.status === 'running' ? '知道了' : '删除',
      okButtonProps: record.status === 'running' ? { danger: false } : { danger: true },
      cancelText: record.status === 'running' ? null : '取消',
      onOk: record.status === 'running' ? undefined : () => handleDelete(record.id),
    });
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
    {
      title: '标的',
      key: 'codes',
      render: (_, record) => (record.config.codes || []).join(', '),
    },
    {
      title: '操作',
      key: 'actions',
      width: 96,
      render: (_, record) => {
        const items = [
          {
            key: 'logs',
            label: '查看日志',
          },
          {
            key: 'stop',
            label: '停止实例',
            disabled: record.status !== 'running',
          },
          {
            key: 'delete',
            label: <span style={{ color: '#cf1322' }}>删除实例</span>,
          },
        ];

        return (
          <Dropdown
            menu={{
              items,
              onClick: ({ key }) => {
                if (key === 'logs') handleLogs(record.id);
                if (key === 'stop') handleStop(record.id);
                if (key === 'delete') openDeleteConfirm(record);
              },
            }}
            trigger={['click']}
          >
            <Button icon={<MoreOutlined />}>操作</Button>
          </Dropdown>
        );
      },
    },
  ];

  return (
    <div className="page-shell">
      <Card className="hero-card hero-card-yellow" bordered={false}>
        <Typography.Text className="hero-kicker">RUN CONTROL</Typography.Text>
        <Typography.Title level={2}>策略管理页</Typography.Title>
        <Typography.Paragraph className="hero-text">
          在这里选择策略、调整参数、启动实例，并随时查看运行状态与日志。右侧表格会自动轮询，方便你管理当前策略实例。
        </Typography.Paragraph>
        <Row gutter={16}>
          <Col span={8}>
            <Statistic title="已注册策略" value={strategies.length} />
          </Col>
          <Col span={8}>
            <Statistic title="运行中实例" value={runningCount} />
          </Col>
          <Col span={8}>
            <Statistic title="总实例数" value={runs.length} />
          </Col>
        </Row>
      </Card>
      <Row gutter={[16, 16]}>
        <Col span={10}>
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Card className="control-card" title="新建并启动策略">
              <Form layout="vertical" form={form} onFinish={handleStart}>
                <Form.Item name="strategyName" label="策略" rules={[{ required: true }]}>
                  <Select
                    options={strategies.map((item) => ({
                      label: item.title,
                      value: item.name,
                    }))}
                  />
                </Form.Item>
                {(selectedStrategy?.param_fields || []).map((field) => renderStrategyField(field))}
                <Divider />
                <Button type="primary" htmlType="submit" loading={loading}>
                  启动策略
                </Button>
              </Form>
            </Card>

            <Card className="control-card" title="策略说明">
              {selectedStrategy ? (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="策略类型">
                    {selectedStrategy.learning_notes?.style || '未定义'}
                  </Descriptions.Item>
                  <Descriptions.Item label="买入逻辑">
                    {selectedStrategy.learning_notes?.entry || selectedStrategy.description}
                  </Descriptions.Item>
                  <Descriptions.Item label="卖出逻辑">
                    {selectedStrategy.learning_notes?.exit || '按策略自身规则卖出'}
                  </Descriptions.Item>
                  <Descriptions.Item label="适用场景">
                    {selectedStrategy.learning_notes?.usage || selectedStrategy.description}
                  </Descriptions.Item>
                  <Descriptions.Item label="默认标的">
                    {(selectedStrategy.params?.codes || []).join(', ')}
                  </Descriptions.Item>
                </Descriptions>
              ) : (
                <Typography.Text type="secondary">请选择一个策略查看说明。</Typography.Text>
              )}
            </Card>
          </Space>
        </Col>
        <Col span={14}>
          <Card className="control-card" title="策略实例列表">
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

function buildStrategyFormDefaults(strategy) {
  const params = strategy?.params || {};
  const defaults = {
    strategyName: strategy?.name,
  };
  (strategy?.param_fields || []).forEach((field) => {
    const value = params[field.name];
    defaults[field.name] = field.type === 'codes' && Array.isArray(value) ? value.join(',') : value;
  });
  return defaults;
}

function renderStrategyField(field) {
  const rules = field.required ? [{ required: true, message: `请输入${field.label}` }] : [];

  if (field.type === 'codes') {
    return (
      <Form.Item key={field.name} name={field.name} label={field.label} rules={rules}>
        <Input placeholder={field.placeholder || 'SZ.000001,HK.03690'} />
      </Form.Item>
    );
  }

  if (field.type === 'number') {
    return (
      <Form.Item key={field.name} name={field.name} label={field.label} rules={rules}>
        <InputNumber min={field.min} step={field.step || 1} style={{ width: '100%' }} />
      </Form.Item>
    );
  }

  return (
    <Form.Item key={field.name} name={field.name} label={field.label} rules={rules}>
      <Input placeholder={field.placeholder} />
    </Form.Item>
  );
}
