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
  listStrategies: () => fetchJson('/api/strategies'),
  listRuns: () => fetchJson('/api/runs'),
  startRun: (payload) =>
    fetchJson('/api/runs', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  stopRun: (id) =>
    fetchJson(`/api/runs/${id}/stop`, {
      method: 'POST',
    }),
  readLogs: (id) => fetchJson(`/api/runs/${id}/logs?lines=200`),
};
