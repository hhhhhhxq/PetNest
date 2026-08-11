import assert from "node:assert/strict";
import test from "node:test";

import worker from "../src/index.js";

const workerUrl = "https://assets.example";
const env = { GITHUB_TOKEN: "test-token" };

test("does not expose the private repository archive or non-resource files", async () => {
  let upstreamCalls = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    upstreamCalls += 1;
    return new Response("unexpected", { status: 200 });
  };
  try {
    const archive = await worker.fetch(new Request(`${workerUrl}/v1/archive.zip`), env);
    const readme = await worker.fetch(new Request(`${workerUrl}/v1/files/README.md`), env);
    assert.equal(archive.status, 404);
    assert.equal(readme.status, 404);
    assert.equal(upstreamCalls, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("proxies only manifest and resource files with SHA-keyed edge caching", async () => {
  const requestedUrls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const textUrl = String(url);
    requestedUrls.push(textUrl);
    if (textUrl.endsWith("/manifest.json?ref=main")) {
      return new Response(
        JSON.stringify({
          resources: [
            {
              files: [
                {
                  path: "resources/cursors/demo/arrow.cur",
                  sha256: "a".repeat(64),
                },
              ],
            },
          ],
        }),
        { status: 200 },
      );
    }
    return new Response("resource-bytes", { status: 200 });
  };
  try {
    const response = await worker.fetch(
      new Request(`${workerUrl}/v1/files/resources/cursors/demo/arrow.cur?sha256=${"a".repeat(64)}`),
      env,
    );
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "resource-bytes");
    assert.equal(response.headers.get("cache-control"), "public, max-age=31536000, immutable");
    assert.deepEqual(requestedUrls, [
      "https://api.github.com/repos/hhhhhhxq/petnest-resources/contents/manifest.json?ref=main",
      "https://api.github.com/repos/hhhhhhxq/petnest-resources/contents/resources/cursors/demo/arrow.cur?ref=main",
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("does not expose resource files absent from the manifest", async () => {
  let upstreamCalls = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    upstreamCalls += 1;
    return new Response("unexpected", { status: 200 });
  };
  try {
    const response = await worker.fetch(
      new Request(`${workerUrl}/v1/files/resources/private/debug.txt?sha256=${"b".repeat(64)}`),
      env,
    );
    assert.equal(response.status, 404);
    assert.equal(upstreamCalls, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("rejects resource requests without a SHA cache key", async () => {
  let upstreamCalls = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    upstreamCalls += 1;
    return new Response("unexpected", { status: 200 });
  };
  try {
    const response = await worker.fetch(
      new Request(`${workerUrl}/v1/files/resources/cursors/demo/arrow.cur`),
      env,
    );
    assert.equal(response.status, 400);
    assert.equal(upstreamCalls, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("does not cache the manifest", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response("manifest", { status: 200 });
  try {
    const response = await worker.fetch(new Request(`${workerUrl}/v1/manifest.json`), env);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "no-store");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
