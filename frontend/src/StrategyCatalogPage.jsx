import { useEffect, useState } from 'react';
import { Card, Col, Descriptions, Empty, Row, Space, Spin, Tag, Typography } from 'antd';
import { api } from './api';

export default function StrategyCatalogPage() {
  const [strategies, setStrategies] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listStrategies()
      .then(setStrategies)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <Spin />;
  }

  if (!strategies.length) {
    return <Empty description="暂无可用策略" />;
  }

  return (
    <div className="page-shell">
      <Card className="hero-card hero-card-purple" bordered={false}>
        <Typography.Text className="hero-kicker">STRATEGY CATALOG</Typography.Text>
        <Typography.Title level={2}>策略管理页</Typography.Title>
        <Typography.Paragraph className="hero-text">
          这里展示当前可加载的策略模型。界面保留了管理后台的密度，但用更圆润、轻松的视觉语言来承载参数信息。
        </Typography.Paragraph>
      </Card>
      <Row gutter={[16, 16]}>
        {strategies.map((strategy) => (
          <Col span={12} key={strategy.name}>
            <Card
              className={`strategy-card ${strategy.name === 'pyramiding_ma' ? 'strategy-card-sun' : 'strategy-card-sky'}`}
              bordered={false}
              title={
                <Space>
                  <span>{strategy.title}</span>
                  <Tag color={strategy.name === 'pyramiding_ma' ? 'orange' : 'blue'}>
                    {strategy.name === 'pyramiding_ma' ? '加仓版' : '单仓版'}
                  </Tag>
                </Space>
              }
            >
              <Typography.Paragraph>{strategy.description}</Typography.Paragraph>
              <Descriptions column={1} size="small">
                <Descriptions.Item label="策略编码">{strategy.name}</Descriptions.Item>
                <Descriptions.Item label="默认标的">
                  {(strategy.params.codes || []).join(', ')}
                </Descriptions.Item>
                <Descriptions.Item label="默认 MA">
                  {strategy.params.short_ma} / {strategy.params.long_ma}
                </Descriptions.Item>
                <Descriptions.Item label="默认下单数量">
                  {strategy.params.order_qty}
                </Descriptions.Item>
                {'max_position_per_stock' in strategy.params ? (
                  <Descriptions.Item label="单标的最大仓位">
                    {strategy.params.max_position_per_stock}
                  </Descriptions.Item>
                ) : null}
              </Descriptions>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}
