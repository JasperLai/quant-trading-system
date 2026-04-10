export async function fetchJson(url, options) {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  return response.json();
}

export const api = {
  getSystemStatus: () => fetchJson('/api/system/status'),
  listStrategies: () => fetchJson('/api/strategies'),
  listRuns: () => fetchJson('/api/runs'),
  listTradeOrders: ({ market = 'HK', tradeEnv = 'SIMULATE', accId, code, refresh = true, limit = 200 } = {}) => {
    const params = new URLSearchParams({
      market,
      trade_env: tradeEnv,
      refresh: String(refresh),
      limit: String(limit),
    });
    if (accId != null && accId !== '') params.set('acc_id', String(accId));
    if (code) params.set('code', code);
    return fetchJson(`/api/trading/orders?${params.toString()}`);
  },
  listTradeDeals: ({ market = 'HK', tradeEnv = 'SIMULATE', accId, code, refresh = true, limit = 200 } = {}) => {
    const params = new URLSearchParams({
      market,
      trade_env: tradeEnv,
      refresh: String(refresh),
      limit: String(limit),
    });
    if (accId != null && accId !== '') params.set('acc_id', String(accId));
    if (code) params.set('code', code);
    return fetchJson(`/api/trading/deals?${params.toString()}`);
  },
  runBacktestValidation: (payload) =>
    fetchJson('/api/backtests/replay-validation', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  startRun: (payload) =>
    fetchJson('/api/runs', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  stopRun: (id) =>
    fetchJson(`/api/runs/${id}/stop`, {
      method: 'POST',
    }),
  deleteRun: (id) =>
    fetchJson(`/api/runs/${id}`, {
      method: 'DELETE',
    }),
  readLogs: (id) => fetchJson(`/api/runs/${id}/logs?lines=200`),
};
