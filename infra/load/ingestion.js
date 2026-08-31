// Load test for the ingestion pipeline (SPEC.md §7 target: "ingestion
// throughput >= 50 docs/min/worker"). Uploads documents back-to-back and
// times each one from upload to "no longer pending" -- the actual
// extract -> chunk -> embed -> index pipeline runs in the single `worker`
// container regardless of how many VUs upload concurrently, so this
// measures real per-worker throughput, not client-side parallelism.
//
// Run against the local docker-compose stack:
//   docker run --rm -i --network helix_default -e BASE_URL=http://api:8000 grafana/k6 run - < infra/load/ingestion.js
import http from "k6/http";
import { check, sleep } from "k6";
import { Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const timeToIngested = new Trend("time_to_ingested_ms", true);

export const options = {
  scenarios: {
    ingestion: {
      executor: "constant-vus",
      vus: 3,
      duration: "60s",
    },
  },
};

export function setup() {
  const email = `k6-ingestion-${Date.now()}@example.com`;
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
    JSON.stringify({ name: "k6 Org", slug: `k6-ingestion-${Date.now()}` }),
    { headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` } }
  );
  return { token, orgId: org.json("id") };
}

export default function (data) {
  const start = Date.now();
  const body = {
    file: http.file(
      `load-test document ${start}-${__VU}-${__ITER}. Some filler text to chunk and embed.`,
      "notes.txt",
      "text/plain"
    ),
  };
  const upload = http.post(`${BASE_URL}/api/v1/orgs/${data.orgId}/documents`, body, {
    headers: { Authorization: `Bearer ${data.token}` },
  });
  check(upload, { "upload accepted": (r) => r.status === 201 });
  const documentId = upload.json("id");

  for (let i = 0; i < 60; i++) {
    const doc = http.get(`${BASE_URL}/api/v1/orgs/${data.orgId}/documents/${documentId}`, {
      headers: { Authorization: `Bearer ${data.token}` },
    });
    if (doc.json("status") !== "pending") {
      timeToIngested.add(Date.now() - start);
      check(doc, { "ingestion did not fail": (r) => r.json("status") === "indexed" });
      return;
    }
    sleep(1);
  }
  timeToIngested.add(Date.now() - start); // timed out after 60s -- still record it
}
