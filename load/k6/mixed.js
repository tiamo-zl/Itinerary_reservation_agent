import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8081';
const USER = { 'X-Mock-User': 'u001' };
const ADMIN = { 'X-Mock-User': 'u002' };

export const options = {
  scenarios: {
    mixed: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: __ENV.RAMP || '20s', target: Number(__ENV.VUS || 20) },
        { duration: __ENV.HOLD || '60s', target: Number(__ENV.VUS || 20) },
        { duration: '10s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<3000'],
  },
};

function health() {
  return http.get(`${BASE_URL}/healthz`, { tags: { endpoint: 'healthz' } });
}

function traces() {
  return http.get(`${BASE_URL}/traces?limit=20`, {
    headers: USER,
    tags: { endpoint: 'traces' },
  });
}

function approvals() {
  return http.get(`${BASE_URL}/approvals?status=pending&limit=20`, {
    headers: ADMIN,
    tags: { endpoint: 'approvals' },
  });
}

function chat() {
  return http.post(
    `${BASE_URL}/chat`,
    JSON.stringify({
      message: '下周二去北京出差两天',
      session_id: `k6-mixed-${__VU}-${__ITER}`,
    }),
    {
      headers: { ...USER, 'Content-Type': 'application/json' },
      timeout: '30s',
      tags: { endpoint: 'chat' },
    },
  );
}

export default function () {
  const requests = [health, traces, approvals, chat];
  const response = requests[__ITER % requests.length]();
  check(response, {
    'request succeeded': (r) => r.status === 200,
  });
  sleep(0.5);
}
