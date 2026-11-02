import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8081';
const USER = { 'X-Mock-User': 'u001' };
const ADMIN = { 'X-Mock-User': 'u002' };

export const options = {
  scenarios: {
    read_paths: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: __ENV.RAMP || '20s', target: Number(__ENV.VUS || 20) },
        { duration: __ENV.HOLD || '1m', target: Number(__ENV.VUS || 20) },
        { duration: '10s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['p(95)<2000'],
  },
};

const endpoints = [
  () => http.get(`${BASE_URL}/healthz`, { tags: { endpoint: 'healthz' } }),
  () => http.get(`${BASE_URL}/traces?limit=20`, {
    headers: USER, tags: { endpoint: 'traces' },
  }),
  () => http.get(`${BASE_URL}/tasks/summary?limit=20`, {
    headers: USER, tags: { endpoint: 'tasks' },
  }),
  () => http.get(`${BASE_URL}/approvals?status=pending&limit=20`, {
    headers: ADMIN, tags: { endpoint: 'approvals' },
  }),
];

export default function () {
  const response = endpoints[__ITER % endpoints.length]();
  check(response, {
    'read succeeded': (r) => r.status === 200,
  });
  sleep(0.2);
}
