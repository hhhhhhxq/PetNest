import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";

import worker, { resetCachesForTesting } from "../src/index.js";

const workerUrl = "https://assets.example";
const env = { GITHUB_TOKEN: "test-token" };

beforeEach(() => resetCachesForTesting());

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
  globalThis.fetch = async (url) => {
    upstreamCalls += 1;
    if (String(url).endsWith("/manifest.json?ref=main")) {
      return new Response(JSON.stringify({ resources: [] }), { status: 200 });
    }
    return new Response("unexpected", { status: 200 });
  };
  try {
    const response = await worker.fetch(
      new Request(`${workerUrl}/v1/files/resources/private/debug.txt?sha256=${"b".repeat(64)}`),
      env,
    );
    assert.equal(response.status, 404);
    assert.equal(upstreamCalls, 1);
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

test("proxies the store catalog without caching", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    assert.match(String(url), /\/contents\/store\/catalog\.json\?ref=main$/);
    return new Response(
      JSON.stringify({
        schema_version: 1,
        pets: [
          {
            cover: { path: "store/pets/sample_pet/cover.png", sha256: "c".repeat(64) },
            idle_preview: {
              path: "store/pets/sample_pet/idle-preview.png",
              sha256: "d".repeat(64),
            },
            package: {
              path: "store/pets/sample_pet/package.zip",
              sha256: "e".repeat(64),
            },
          },
        ],
      }),
      { status: 200 },
    );
  };
  try {
    const response = await worker.fetch(new Request(`${workerUrl}/v1/store/catalog.json`), env);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "no-store");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("proxies the v2 store catalog from its separate source file", async () => {
  const requestedUrls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    requestedUrls.push(String(url));
    return new Response(JSON.stringify({ schema_version: 1, pets: [] }), { status: 200 });
  };
  try {
    const response = await worker.fetch(new Request(`${workerUrl}/v2/store/catalog.json`), env);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.deepEqual(requestedUrls, [
      "https://api.github.com/repos/hhhhhhxq/petnest-resources/contents/store/catalog-v2.json?ref=main",
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("allows files declared only in the v2 store catalog", async () => {
  const packagePath = "store/pets/webp_pet/package-webp.zip";
  const packageSha = "9".repeat(64);
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const textUrl = String(url);
    if (textUrl.endsWith("/store/catalog-v2.json?ref=main")) {
      return new Response(
        JSON.stringify({
          schema_version: 1,
          pets: [
            {
              cover: { path: "store/pets/webp_pet/cover.png", sha256: "7".repeat(64) },
              idle_preview: {
                path: "store/pets/webp_pet/idle-preview.png",
                sha256: "8".repeat(64),
              },
              package: { path: packagePath, sha256: packageSha },
            },
          ],
        }),
        { status: 200 },
      );
    }
    if (textUrl.endsWith("/store/catalog.json?ref=main")) {
      return new Response(JSON.stringify({ schema_version: 1, pets: [] }), { status: 200 });
    }
    return new Response("webp-package", { status: 200 });
  };
  try {
    const catalog = await worker.fetch(new Request(`${workerUrl}/v2/store/catalog.json`), env);
    assert.equal(catalog.status, 200);
    const response = await worker.fetch(
      new Request(`${workerUrl}/v1/store/files/${packagePath}?sha256=${packageSha}`),
      env,
    );
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "webp-package");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("rejects a file path whose SHA conflicts between v1 and v2 catalogs", async () => {
  const packagePath = "store/pets/conflict/package.zip";
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const textUrl = String(url);
    if (textUrl.endsWith("/store/catalog.json?ref=main")) {
      return new Response(
        JSON.stringify({
          schema_version: 1,
          pets: [{
            cover: { path: "store/pets/conflict/cover-v1.png", sha256: "1".repeat(64) },
            idle_preview: { path: "store/pets/conflict/preview-v1.png", sha256: "2".repeat(64) },
            package: { path: packagePath, sha256: "3".repeat(64) },
          }],
        }),
        { status: 200 },
      );
    }
    if (textUrl.endsWith("/store/catalog-v2.json?ref=main")) {
      return new Response(
        JSON.stringify({
          schema_version: 1,
          pets: [{
            cover: { path: "store/pets/conflict/cover-v2.png", sha256: "4".repeat(64) },
            idle_preview: { path: "store/pets/conflict/preview-v2.png", sha256: "5".repeat(64) },
            package: { path: packagePath, sha256: "6".repeat(64) },
          }],
        }),
        { status: 200 },
      );
    }
    return new Response("unexpected", { status: 200 });
  };
  try {
    const catalog = await worker.fetch(new Request(`${workerUrl}/v2/store/catalog.json`), env);
    assert.equal(catalog.status, 200);
    const response = await worker.fetch(
      new Request(`${workerUrl}/v1/store/files/${packagePath}?sha256=${"3".repeat(64)}`),
      env,
    );
    assert.equal(response.status, 502);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("allows a file path shared by v1 and v2 catalogs with the same SHA", async () => {
  const packagePath = "store/pets/shared/package.zip";
  const packageSha = "3".repeat(64);
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const textUrl = String(url);
    if (textUrl.endsWith("/store/catalog.json?ref=main")) {
      return new Response(
        JSON.stringify({
          schema_version: 1,
          pets: [{
            cover: { path: "store/pets/shared/cover-v1.png", sha256: "1".repeat(64) },
            idle_preview: { path: "store/pets/shared/preview-v1.png", sha256: "2".repeat(64) },
            package: { path: packagePath, sha256: packageSha },
          }],
        }),
        { status: 200 },
      );
    }
    if (textUrl.endsWith("/store/catalog-v2.json?ref=main")) {
      return new Response(
        JSON.stringify({
          schema_version: 1,
          pets: [{
            cover: { path: "store/pets/shared/cover-v2.png", sha256: "4".repeat(64) },
            idle_preview: { path: "store/pets/shared/preview-v2.png", sha256: "5".repeat(64) },
            package: { path: packagePath, sha256: packageSha },
          }],
        }),
        { status: 200 },
      );
    }
    return new Response("shared-package", { status: 200 });
  };
  try {
    const response = await worker.fetch(
      new Request(`${workerUrl}/v1/store/files/${packagePath}?sha256=${packageSha}`),
      env,
    );
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "shared-package");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("does not cache a partial store allowlist when v2 temporarily fails", async () => {
  const packagePath = "store/pets/legacy/package.zip";
  const packageSha = "a".repeat(64);
  let catalogRequests = 0;
  let packageRequests = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const textUrl = String(url);
    if (textUrl.endsWith("/store/catalog.json?ref=main")) {
      catalogRequests += 1;
      return new Response(
        JSON.stringify({
          schema_version: 1,
          pets: [{
            cover: { path: "store/pets/legacy/cover.png", sha256: "b".repeat(64) },
            idle_preview: { path: "store/pets/legacy/preview.png", sha256: "c".repeat(64) },
            package: { path: packagePath, sha256: packageSha },
          }],
        }),
        { status: 200 },
      );
    }
    if (textUrl.endsWith("/store/catalog-v2.json?ref=main")) {
      catalogRequests += 1;
      return new Response("temporary failure", { status: 503 });
    }
    packageRequests += 1;
    return new Response("package", { status: 200 });
  };
  try {
    const request = new Request(
      `${workerUrl}/v1/store/files/${packagePath}?sha256=${packageSha}`,
    );
    assert.equal((await worker.fetch(request, env)).status, 502);
    assert.equal((await worker.fetch(request, env)).status, 502);
    assert.equal(catalogRequests, 4);
    assert.equal(packageRequests, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("rejects an allowlist refresh invalidated by a newer catalog response", async () => {
  const packagePath = "store/pets/legacy/package.zip";
  const packageSha = "a".repeat(64);
  let v2Requests = 0;
  let packageRequests = 0;
  let signalV2Started;
  let releaseStaleV2;
  const v2Started = new Promise((resolve) => {
    signalV2Started = resolve;
  });
  const staleV2Response = new Promise((resolve) => {
    releaseStaleV2 = resolve;
  });
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const textUrl = String(url);
    if (textUrl.endsWith("/store/catalog.json?ref=main")) {
      return new Response(
        JSON.stringify({
          schema_version: 1,
          pets: [{
            cover: { path: "store/pets/legacy/cover.png", sha256: "b".repeat(64) },
            idle_preview: { path: "store/pets/legacy/preview.png", sha256: "c".repeat(64) },
            package: { path: packagePath, sha256: packageSha },
          }],
        }),
        { status: 200 },
      );
    }
    if (textUrl.endsWith("/store/catalog-v2.json?ref=main")) {
      v2Requests += 1;
      if (v2Requests === 1) {
        signalV2Started();
        return staleV2Response;
      }
      return new Response(JSON.stringify({ schema_version: 1, pets: [] }), { status: 200 });
    }
    packageRequests += 1;
    return new Response("package", { status: 200 });
  };
  try {
    const fileResponsePromise = worker.fetch(
      new Request(`${workerUrl}/v1/store/files/${packagePath}?sha256=${packageSha}`),
      env,
    );
    await v2Started;
    const catalogResponse = await worker.fetch(
      new Request(`${workerUrl}/v2/store/catalog.json`),
      env,
    );
    assert.equal(catalogResponse.status, 200);
    releaseStaleV2(new Response(JSON.stringify({ schema_version: 1, pets: [] }), { status: 200 }));
    assert.equal((await fileResponsePromise).status, 502);
    assert.equal(packageRequests, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("allows only SHA-matched files listed in the store catalog", async () => {
  const coverSha = "c".repeat(64);
  const requestedUrls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const textUrl = String(url);
    requestedUrls.push(textUrl);
    if (textUrl.endsWith("/store/catalog.json?ref=main")) {
      return new Response(
        JSON.stringify({
          schema_version: 1,
          pets: [
            {
              cover: { path: "store/pets/sample_pet/cover.png", sha256: coverSha },
              idle_preview: {
                path: "store/pets/sample_pet/idle-preview.png",
                sha256: "d".repeat(64),
              },
              package: {
                path: "store/pets/sample_pet/package.zip",
                sha256: "e".repeat(64),
              },
            },
          ],
        }),
        { status: 200 },
      );
    }
    if (textUrl.endsWith("/store/catalog-v2.json?ref=main")) {
      return new Response("missing", { status: 404 });
    }
    return new Response("cover", { status: 200 });
  };
  try {
    const response = await worker.fetch(
      new Request(
        `${workerUrl}/v1/store/files/store/pets/sample_pet/cover.png?sha256=${coverSha}`,
      ),
      env,
    );
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "cover");
    assert.equal(response.headers.get("cache-control"), "public, max-age=31536000, immutable");
    assert.equal(
      requestedUrls.at(-1),
      "https://api.github.com/repos/hhhhhhxq/petnest-resources/contents/store/pets/sample_pet/cover.png?ref=main",
    );
    assert.deepEqual(requestedUrls.slice(0, 2), [
      "https://api.github.com/repos/hhhhhhxq/petnest-resources/contents/store/catalog.json?ref=main",
      "https://api.github.com/repos/hhhhhhxq/petnest-resources/contents/store/catalog-v2.json?ref=main",
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("rejects private store metadata, wrong SHA, and cross-catalog paths", async () => {
  let targetCalls = 0;
  const coverSha = "f".repeat(64);
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const textUrl = String(url);
    if (textUrl.endsWith("/store/catalog.json?ref=main")) {
      return new Response(
        JSON.stringify({
          schema_version: 1,
          pets: [
            {
              cover: { path: "store/pets/sample_pet/cover.png", sha256: coverSha },
              idle_preview: { path: "store/pets/sample_pet/idle-preview.png", sha256: "a".repeat(64) },
              package: { path: "store/pets/sample_pet/package.zip", sha256: "b".repeat(64) },
            },
          ],
        }),
        { status: 200 },
      );
    }
    if (textUrl.endsWith("/store/catalog-v2.json?ref=main")) {
      return new Response("missing", { status: 404 });
    }
    targetCalls += 1;
    return new Response("unexpected", { status: 200 });
  };
  try {
    const listing = await worker.fetch(
      new Request(`${workerUrl}/v1/store/files/store/pets/sample_pet/listing.json?sha256=${coverSha}`),
      env,
    );
    const wrongSha = await worker.fetch(
      new Request(`${workerUrl}/v1/store/files/store/pets/sample_pet/cover.png?sha256=${"0".repeat(64)}`),
      env,
    );
    const runtimePath = await worker.fetch(
      new Request(`${workerUrl}/v1/store/files/resources/cursors/demo/arrow.cur?sha256=${coverSha}`),
      env,
    );
    assert.equal(listing.status, 404);
    assert.equal(wrongSha.status, 404);
    assert.equal(runtimePath.status, 404);
    assert.equal(targetCalls, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
