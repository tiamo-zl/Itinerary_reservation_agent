import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8081';

export const options = {
  vus: Number(__ENV.VUS || 5),
  duration: __ENV.DURATION || '30s',
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<5000'],
  },
};

export default function () {
  const body = JSON.stringify({
    message: '下周二去北京出差两天，预算 1000 元',
    session_id: `k6-${__VU}-${__ITER}`,
  });
  const response = http.post(`${BASE_URL}/chat`, body, {
    headers: {
      'Content-Type': 'application/json',
      'X-Mock-User': 'u001',
    },
    timeout: '30s',
    tags: { endpoint: 'chat' },
  });
  check(response, {
    'chat is 200': (r) => r.status === 200,
    'chat produced an SSE event': (r) =>
      r.body.includes('event:') &&
      (r.body.includes('event: result') || r.body.includes('event: interrupt')),
  });
  sleep(1);
}
