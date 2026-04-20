import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Tabs,
  Typography,
  message,
} from 'antd';
import { api } from './api';

const COMMON_BACKTEST_FIELDS = [
  { name: 'start', label: '开始日期', type: 'text', required: true, placeholder: '2025-10-01' },
  { name: 'end', label: '结束日期', type: 'text', required: true, placeholder: '2026-04-08' },
  {
    name: 'backtestBackend',
    label: '回测后端',
    type: 'select',
    required: true,
    options: [
      { label: '原生引擎', value: 'native' },
      { label: 'Zipline', value: 'zipline' },
    ],
  },
  { name: 'initialCash', label: '初始资金', type: 'number', required: true, min: 1 },
  { name: 'commissionRate', label: '手续费率', type: 'number', required: true, min: 0, step: 0.0001 },
  { name: 'slippage', label: '滑点', type: 'number', required: true, min: 0, step: 0.01 },
];

function numberColor(value) {
  if (value > 0) return '#389e0d';
  if (value < 0) return '#cf1322';
  return '#595959';
}

function KLineChart({ chart }) {
  const width = 960;
  const height = 360;
  const padding = { top: 20, right: 20, bottom: 40, left: 56 };

  const model = useMemo(() => {
    const bars = chart?.bars || [];
    const trades = chart?.trades || [];
    if (!bars.length) return null;

    const prices = bars.flatMap((bar) => [bar.high, bar.low]).filter((value) => typeof value === 'number');
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const priceRange = Math.max(maxPrice - minPrice, 0.0001);
    const innerWidth = width - padding.left - padding.right;
    const innerHeight = height - padding.top - padding.bottom;
    const candleWidth = Math.max(Math.min((innerWidth / bars.length) * 0.72, 16), 4);

    const xForIndex = (index) => padding.left + (innerWidth / Math.max(bars.length - 1, 1)) * index;
    const yForPrice = (price) => padding.top + ((maxPrice - price) / priceRange) * innerHeight;

    const tradeMap = trades.reduce((acc, trade) => {
      if (!acc[trade.time]) acc[trade.time] = [];
      acc[trade.time].push(trade);
      return acc;
    }, {});

    const path = bars
      .map((bar, index) => `${index === 0 ? 'M' : 'L'} ${xForIndex(index)} ${yForPrice(bar.close)}`)
      .join(' ');

    const ticks = Array.from({ length: 5 }, (_, index) => {
      const ratio = index / 4;
      const price = maxPrice - priceRange * ratio;
      return {
        label: price.toFixed(2),
        y: padding.top + innerHeight * ratio,
      };
    });

    const step = Math.max(Math.floor(bars.length / 6), 1);
    const xTicks = bars
      .filter((_, index) => index % step === 0)
      .map((bar, index) => ({
        time: bar.time,
        x: xForIndex(index * step),
      }));

    return {
      bars,
      tradeMap,
      path,
      ticks,
      xTicks,
      xForIndex,
      yForPrice,
      candleWidth,
    };
  }, [chart]);

  if (!model) {
    return <Empty description="暂无可绘制的 K 线数据" />;
  }

  return (
    <div className="chart-shell">
      <div className="chart-caption">
        <Typography.Text strong>{chart.code}</Typography.Text>
        <Typography.Text type="secondary">历史 K 线与买卖点标注</Typography.Text>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="kline-chart">
        <rect x="0" y="0" width={width} height={height} rx="28" fill="#fffdf7" />
        {model.ticks.map((tick) => (
          <g key={tick.label}>
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={tick.y}
              y2={tick.y}
              stroke="rgba(145, 158, 171, 0.18)"
              strokeDasharray="4 6"
            />
            <text x={12} y={tick.y + 4} className="chart-axis-label">
              {tick.label}
            </text>
          </g>
        ))}
        <path d={model.path} fill="none" stroke="#1677ff" strokeWidth="2.5" opacity="0.22" />
        {model.bars.map((bar, index) => {
          const x = model.xForIndex(index);
          const openY = model.yForPrice(bar.open);
          const closeY = model.yForPrice(bar.close);
          const highY = model.yForPrice(bar.high);
          const lowY = model.yForPrice(bar.low);
          const isUp = bar.close >= bar.open;
          const bodyY = Math.min(openY, closeY);
          const bodyHeight = Math.max(Math.abs(closeY - openY), 2);
          const trades = model.tradeMap[bar.time] || [];

          return (
            <g key={bar.time}>
              <line x1={x} x2={x} y1={highY} y2={lowY} stroke={isUp ? '#16a34a' : '#dc2626'} strokeWidth="1.4" />
              <rect
                x={x - model.candleWidth / 2}
                y={bodyY}
                width={model.candleWidth}
                height={bodyHeight}
                rx="3"
                fill={isUp ? '#8ee3b3' : '#ffb3b0'}
                stroke={isUp ? '#16a34a' : '#dc2626'}
                strokeWidth="1.2"
              />
              {trades.map((trade, tradeIndex) => {
                const markerY = model.yForPrice(trade.price);
                const color = trade.side === 'BUY' ? '#16a34a' : '#dc2626';
                const direction = trade.side === 'BUY' ? -1 : 1;
                const markerX = x + tradeIndex * 10 - (trades.length - 1) * 5;
                return (
                  <g key={`${trade.time}-${trade.side}-${tradeIndex}`}>
                    <line x1={markerX} x2={markerX} y1={markerY} y2={markerY + direction * 18} stroke={color} strokeWidth="1.5" />
                    <circle cx={markerX} cy={markerY} r="4" fill={color} />
                    <text x={markerX - 8} y={markerY + direction * 28} className="chart-marker-label" fill={color}>
                      {trade.side}
                    </text>
                  </g>
                );
              })}
            </g>
          );
        })}
        {model.xTicks.map((tick) => (
          <text key={tick.time} x={tick.x - 16} y={height - 12} className="chart-axis-label">
            {tick.time.slice(5, 10)}
          </text>
        ))}
      </svg>
    </div>
  );
}

function normalizeStrategyDefaults(strategy) {
  const params = strategy?.params || {};
  const defaults = {
    strategyName: strategy?.name,
    start: '2025-10-01',
    end: '2026-04-08',
    backtestBackend: 'native',
    initialCash: 100000,
    commissionRate: 0.001,
    slippage: 0,
  };
  (strategy?.param_fields || []).forEach((field) => {
    const value = params[field.name];
    if (field.type === 'codes') {
      defaults[field.name] = Array.isArray(value) ? value.join(',') : '';
      return;
    }
    defaults[field.name] = value;
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

  if (field.type === 'select') {
    return (
      <Form.Item key={field.name} name={field.name} label={field.label} rules={rules}>
        <Select options={field.options || []} />
      </Form.Item>
    );
  }

  return (
    <Form.Item key={field.name} name={field.name} label={field.label} rules={rules}>
      <Input placeholder={field.placeholder} />
    </Form.Item>
  );
}

function OpenPositionsView({ positions }) {
  const entries = Object.entries(positions || {});
  if (!entries.length) {
    return <Typography.Text type="secondary">无</Typography.Text>;
  }

  return (
    <div className="open-positions-grid">
      {entries.map(([code, position]) => {
        const qty = typeof position === 'object' && position !== null ? position.qty : position;
        const entry = typeof position === 'object' && position !== null ? position.entry : null;
        const stop = typeof position === 'object' && position !== null ? position.stop : null;
        const profit = typeof position === 'object' && position !== null ? position.profit : null;

        return (
          <div key={code} className="open-position-pill">
            <div className="open-position-code">{code}</div>
            <div className="open-position-meta">{qty} 股</div>
            {entry != null ? <div className="open-position-meta">成本 {Number(entry).toFixed(2)}</div> : null}
            {stop != null ? <div className="open-position-meta">止损 {Number(stop).toFixed(2)}</div> : null}
            {profit != null ? <div className="open-position-meta">止盈 {Number(profit).toFixed(2)}</div> : null}
          </div>
        );
      })}
    </div>
  );
}

export default function BacktestPage() {
  const [form] = Form.useForm();
  const [strategies, setStrategies] = useState([]);
  const [loadingStrategies, setLoadingStrategies] = useState(true);
  const [strategyLoadError, setStrategyLoadError] = useState('');
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');
  const [tradeTabVisible, setTradeTabVisible] = useState(false);

  const selectedStrategyName = Form.useWatch('strategyName', form);
  const selectedStrategy = useMemo(
    () => strategies.find((item) => item.name === selectedStrategyName),
    [strategies, selectedStrategyName],
  );

  useEffect(() => {
    api
      .listStrategies()
      .then((data) => {
        setStrategyLoadError('');
        const supportedStrategies = data.filter((item) => item.supports_backtest !== false);
        setStrategies(supportedStrategies);
        if (supportedStrategies.length) {
          form.setFieldsValue(normalizeStrategyDefaults(supportedStrategies[0]));
        }
      })
      .catch((error) => {
        setStrategyLoadError(error.message || '策略列表加载失败');
        message.error(error.message);
      })
      .finally(() => setLoadingStrategies(false));
  }, [form]);

  useEffect(() => {
    if (!selectedStrategy) return;
    form.setFieldsValue({
      ...normalizeStrategyDefaults(selectedStrategy),
      start: form.getFieldValue('start') || '2025-10-01',
      end: form.getFieldValue('end') || '2026-04-08',
      initialCash: form.getFieldValue('initialCash') ?? 100000,
      commissionRate: form.getFieldValue('commissionRate') ?? 0.001,
      slippage: form.getFieldValue('slippage') ?? 0,
    });
  }, [selectedStrategy, form]);

  async function handleRun(values) {
    setRunning(true);
    try {
      const strategyParams = {};
      (selectedStrategy?.param_fields || []).forEach((field) => {
        const value = values[field.name];
        if (value == null || value === '') return;
        strategyParams[field.name] = value;
      });

      const payload = {
        strategyName: values.strategyName,
        strategyParams,
        backtestBackend: values.backtestBackend,
        codes: (strategyParams.codes || '')
          .split(',')
          .map((item) => item.trim())
          .filter(Boolean),
        start: values.start,
        end: values.end,
        initialCash: values.initialCash,
        commissionRate: values.commissionRate,
        slippage: values.slippage,
      };

      const result = await api.runBacktestValidation(payload);
      setReport(result);
      setTradeTabVisible(false);
      setActiveTab('overview');
      message.success('回测与流程验证已完成');
    } catch (error) {
      message.error(error.message);
    } finally {
      setRunning(false);
    }
  }

  function openTradeTab() {
    if (!report) {
      message.info('请先发起一次回测验证');
      return;
    }
    setTradeTabVisible(true);
    setActiveTab('trades');
  }

  const summary = report?.backtest?.summary;
  const tradeData = report?.backtest?.trades || [];
  const columns = [
    { title: '时间', dataIndex: 'time', key: 'time', width: 130 },
    { title: '代码', dataIndex: 'code', key: 'code', width: 100 },
    {
      title: '方向',
      dataIndex: 'side',
      key: 'side',
      width: 88,
      render: (value) => <Tag color={value === 'BUY' ? 'green' : 'red'}>{value}</Tag>,
    },
    { title: '价格', dataIndex: 'price', key: 'price', width: 90 },
    { title: '数量', dataIndex: 'qty', key: 'qty', width: 90 },
    { title: '原因', dataIndex: 'reason', key: 'reason' },
    {
      title: '已实现盈亏',
      dataIndex: 'realized_pnl',
      key: 'realized_pnl',
      width: 120,
      render: (value) =>
        value == null ? '-' : <span style={{ color: numberColor(value) }}>{Number(value).toFixed(2)}</span>,
    },
  ];

  return (
    <div className="page-shell">
      <Card className="hero-card hero-card-mint" bordered={false}>
        <Typography.Text className="hero-kicker">BACKTEST & WORKFLOW VALIDATION</Typography.Text>
        <Typography.Title level={2}>回测验证页</Typography.Title>
        <Typography.Paragraph className="hero-text">
          先选择已注册策略，再根据策略类型填写对应参数。回测页会自动生成历史 K 线、买卖点和可追溯的交易明细。
        </Typography.Paragraph>
      </Card>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        className="backtest-tabs"
        items={[
          {
            key: 'overview',
            label: '回测总览',
            children: (
              <Row gutter={[16, 16]}>
                <Col span={8}>
                  <Card className="control-card" title="回测参数">
                    {loadingStrategies ? (
                      <div style={{ minHeight: 320, display: 'grid', placeItems: 'center' }}>
                        <Spin />
                      </div>
                    ) : strategyLoadError ? (
                      <Empty description={`策略加载失败: ${strategyLoadError}`} />
                    ) : !strategies.length ? (
                      <Empty description="暂无可用策略" />
                    ) : (
                      <Form form={form} layout="vertical" onFinish={handleRun}>
                        <Form.Item name="strategyName" label="策略" rules={[{ required: true, message: '请选择策略' }]}>
                          <Select
                            options={strategies.map((item) => ({
                              label: item.title,
                              value: item.name,
                            }))}
                          />
                        </Form.Item>

                        {selectedStrategy?.param_fields?.map(renderStrategyField)}

                        {COMMON_BACKTEST_FIELDS.map((field) => (
                          <Form.Item
                            key={field.name}
                            name={field.name}
                            label={field.label}
                            rules={field.required ? [{ required: true, message: `请输入${field.label}` }] : []}
                          >
                            {field.type === 'number' ? (
                              <InputNumber min={field.min} step={field.step || 1} style={{ width: '100%' }} />
                            ) : (
                              <Input placeholder={field.placeholder} />
                            )}
                          </Form.Item>
                        ))}

                        <Button type="primary" htmlType="submit" loading={running}>
                          发起回测验证
                        </Button>
                      </Form>
                    )}
                  </Card>
                </Col>

                <Col span={16}>
                  <Space direction="vertical" size={16} style={{ width: '100%' }}>
                    <Row gutter={16}>
                      <Col span={8}>
                        <Card className="control-card">
                          <Statistic title="最终权益" value={summary?.final_equity ?? 0} precision={2} />
                        </Card>
                      </Col>
                      <Col span={8}>
                        <Card className="control-card">
                          <Statistic
                            title="收益率"
                            value={summary?.return_pct ?? 0}
                            precision={2}
                            suffix="%"
                            valueStyle={{ color: numberColor(summary?.return_pct ?? 0) }}
                          />
                        </Card>
                      </Col>
                      <Col span={8}>
                        <Card className="control-card">
                          <Statistic title="交易次数" value={summary?.trade_count ?? 0} />
                        </Card>
                      </Col>
                    </Row>

                    <Card
                      className="control-card"
                      title="回测摘要"
                      extra={
                        <Button type="link" onClick={(event) => {
                          event.stopPropagation();
                          openTradeTab();
                        }}>
                          打开交易明细
                        </Button>
                      }
                    >
                      {summary ? (
                        <Descriptions column={2} size="small">
                          <Descriptions.Item label="策略">{summary.strategy}</Descriptions.Item>
                          <Descriptions.Item label="最大回撤">{summary.max_drawdown_pct}%</Descriptions.Item>
                          <Descriptions.Item label="初始资金">{summary.initial_cash}</Descriptions.Item>
                          <Descriptions.Item label="胜率">{summary.win_rate}%</Descriptions.Item>
                          <Descriptions.Item label="已平仓次数">{summary.closed_trade_count}</Descriptions.Item>
                          <Descriptions.Item label="未平仓仓位">
                            <OpenPositionsView positions={summary.open_positions} />
                          </Descriptions.Item>
                        </Descriptions>
                      ) : (
                        <Empty description="暂无回测摘要" />
                      )}
                    </Card>

                    <Card className="control-card" title="K 线与买卖点">
                      <KLineChart chart={report?.chart} />
                    </Card>
                  </Space>
                </Col>
              </Row>
            ),
          },
          ...(tradeTabVisible
            ? [
                {
                  key: 'trades',
                  label: '交易明细',
                  children: (
                    <Card className="control-card" title="交易明细">
                      <Table
                        rowKey={(record) => `${record.time}-${record.side}-${record.code}-${record.qty}`}
                        columns={columns}
                        dataSource={tradeData}
                      />
                    </Card>
                  ),
                },
              ]
            : []),
        ]}
      />
    </div>
  );
}
