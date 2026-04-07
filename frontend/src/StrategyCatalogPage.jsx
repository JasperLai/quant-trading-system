import { useEffect, useState } from 'react';
import { Card, Col, Descriptions, Empty, Row, Spin, Typography } from 'antd';
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
    <div>
      <Typography.Title level={4}>策略管理页</Typography.Title>
      <Row gutter={[16, 16]}>
        {strategies.map((strategy) => (
          <Col span={12} key={strategy.name}>
            <Card title={strategy.title} bordered={false}>
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
