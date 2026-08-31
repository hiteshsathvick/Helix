// Load test for POST /api/v1/orgs/{org_id}/assistant/query (SPEC.md §7
// target: first token < 2s). Requires AI_DEFAULT_PROVIDER=mock (Phase 20) --
// a real provider would make this a real-money load test and the answer
// latency would measure Anthropic's API, not Helix's own code path.
//
// Run against the local docker-compose stack (with AI_DEFAULT_PROVIDER=mock
// set in .env before `docker compose up`):
//   docker run --rm -i --network helix_default -e BASE_URL=http://api:8000 grafana/k6 run - < infra/load/assistant.js
//
// Note: k6's core http module buffers the whole response body rather than
// exposing SSE frame arrival times, so `http_req_duration` here approximates
// "time to full answer," not strictly "time to first token" -- documented
// as a caveat in docs/performance/load-test-baseline.md, not something this
// script can fix without k6's experimental streaming APIs.
import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
// Plain constant, not read back via `options.scenarios...` in setup()
// below -- k6 (run via stdin) doesn't reliably let a script
// self-reference its own exported `options` object.
// Kept at/under 5 for two reasons: (1) every VU registers through setup()
// sequentially from the same k6 container -- they share one source IP, and
// core/rate_limit.py's per-IP auth_rate_limit_max_attempts (5/60s, Phase
// 19) would reject login attempt #6+ before setup() finishes; (2) each VU
// is its own user/rate-limit bucket for the *assistant* endpoint too
// (assistant_rate_limit_max_requests, 20/60s per user), so this measures
// real latency, not either rate limiter rejecting load.
const VUS = 5;

export const options = {
  scenarios: {
    assistant: {
      executor: "constant-vus",
      vus: VUS,
      duration: "20s",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
  },
};

function registerLoginAndCreateOrg(n) {
  // `n` (the setup() loop index), not __VU -- inside setup() every call
  // runs in the same fixed VU context, so __VU alone doesn't vary between
  // iterations and every user/slug would collide.
  const email = `k6-assistant-${n}-${Date.now()}@example.com`;
  const password = "a-strong-password-1";

  http.post(
    `${BASE_URL}/api/v1/auth/register`,
    JSON.stringify({ email, password }),
    { headers: { "Content-Type": "application/json" } }
  );
  const login = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ email, password }),
    { headers: { "Content-Type": "application/json" } }
  );
  const token = login.json("access_token");

  const org = http.post(
    `${BASE_URL}/api/v1/orgs`,
    JSON.stringify({ name: "k6 Org", slug: `k6-assistant-${n}-${Date.now()}` }),
    { headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` } }
  );
  return { token, orgId: org.json("id") };
}

export function setup() {
  const users = [];
  for (let vu = 1; vu <= VUS; vu++) {
    users.push(registerLoginAndCreateOrg(vu));
  }
  return { users };
}

export default function (data) {
  const user = data.users[(__VU - 1) % data.users.length];
  const response = http.post(
    `${BASE_URL}/api/v1/orgs/${user.orgId}/assistant/query`,
    JSON.stringify({ query: "What does Helix support?" }),
    { headers: { "Content-Type": "application/json", Authorization: `Bearer ${user.token}` } }
  );
  check(response, {
    "status is 200": (r) => r.status === 200,
    // MockProvider (ai/providers.py) streams its answer word-by-word as
    // separate SSE "token" events, so the full sentence never appears as
    // one contiguous substring in the raw body -- checking for the "done"
    // event is what actually proves the stream completed successfully.
    "stream completed": (r) =>
      typeof r.body === "string" && r.body.includes('"type": "done"'),
  });
}
