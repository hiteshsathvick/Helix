// Load test for GET /api/v1/orgs/{org_id}/search (SPEC.md §7 target: p95 < 400ms).
//
// Run against the local docker-compose stack:
//   docker run --rm -i --network helix_default -e BASE_URL=http://api:8000 grafana/k6 run - < infra/load/search.js
//
// setup() registers one user/org and ingests a fixed document once, so every
// VU/iteration hits real, non-empty search results rather than warming an
// empty index.
import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
// Plain constant, not read back via `options.scenarios.search.vus` in
// setup() below -- k6 (run via stdin) doesn't reliably let a script
// self-reference its own exported `options` object.
// Capped at 5, not higher: every VU registers through setup() sequentially
// from the same k6 container, so they share one source IP -- core/
// rate_limit.py's per-IP auth_rate_limit_max_attempts (5/60s, Phase 19)
// would otherwise reject login attempt #6+ before setup() even finishes.
const VUS = 5;

export const options = {
  scenarios: {
    search: {
      executor: "constant-vus",
      vus: VUS,
      duration: "30s",
    },
  },
  thresholds: {
    // SPEC.md §7: "p95 search < 400ms (excl. LLM)".
    http_req_duration: ["p(95)<400"],
    http_req_failed: ["rate<0.01"],
  },
};

function registerLoginAndCreateOrg(n) {
  // `n` (the setup() loop index), not __VU -- inside setup() every call
  // runs in the same fixed VU context, so __VU alone doesn't vary between
  // iterations and every user/slug would collide.
  const email = `k6-search-${n}-${Date.now()}@example.com`;
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
    JSON.stringify({ name: "k6 Org", slug: `k6-search-${n}-${Date.now()}` }),
    { headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` } }
  );
  return { token, orgId: org.json("id") };
}

function uploadAndIngest(token, orgId) {
  const body = {
    file: http.file(
      "load-test doc. mentions a searchable keyword: zylophant.",
      "notes.txt",
      "text/plain"
    ),
  };
  const upload = http.post(`${BASE_URL}/api/v1/orgs/${orgId}/documents`, body, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const documentId = upload.json("id");

  // Ingestion runs async in the worker; poll status until it's no longer
  // "pending" so search() below actually finds the content.
  for (let i = 0; i < 30; i++) {
    const doc = http.get(`${BASE_URL}/api/v1/orgs/${orgId}/documents/${documentId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (doc.json("status") !== "pending") return;
    sleep(1);
  }
}

export function setup() {
  const users = [];
  for (let vu = 1; vu <= VUS; vu++) {
    const ctx = registerLoginAndCreateOrg(vu);
    uploadAndIngest(ctx.token, ctx.orgId);
    users.push(ctx);
  }
  return { users };
}

export default function (data) {
  const user = data.users[(__VU - 1) % data.users.length];
  const response = http.get(
    `${BASE_URL}/api/v1/orgs/${user.orgId}/search?q=zylophant`,
    { headers: { Authorization: `Bearer ${user.token}` } }
  );
  check(response, { "status is 200": (r) => r.status === 200 });
}
