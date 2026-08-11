const OWNER = "hhhhhhxq";
const REPO = "petnest-resources";
const BRANCH = "main";
const MANIFEST_CACHE_TTL_MS = 10_000;

let manifestCache = { expiresAt: 0, files: null };
let manifestRefreshPromise = null;

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }
    if (!["GET", "HEAD"].includes(request.method)) {
      return new Response("Method Not Allowed", { status: 405 });
    }

    const url = new URL(request.url);
    let path;
    if (url.pathname === "/v1/manifest.json") {
      path = "manifest.json";
    } else if (url.pathname === "/v1/archive.zip") {
      // Do not proxy GitHub's branch zipball: it contains the entire private
      // repository, not just the runtime resources.  Clients transparently
      // fall back to the resource-scoped file route.
      return new Response("Not Found", { status: 404, headers: corsHeaders() });
    } else if (url.pathname.startsWith("/v1/files/")) {
      try {
        path = decodeURIComponent(url.pathname.slice("/v1/files/".length));
      } catch {
        return new Response("Invalid path", { status: 400 });
      }
    } else {
      return new Response("Not Found", { status: 404 });
    }

    const parts = path ? path.split("/") : [];
    if (path !== undefined && (!path || parts.some((part) => !part || part === "." || part === ".." || part.includes("\\")))) {
      return new Response("Invalid path", { status: 400, headers: corsHeaders() });
    }
    if (path !== "manifest.json" && (!path || !path.startsWith("resources/"))) {
      return new Response("Not Found", { status: 404, headers: corsHeaders() });
    }
    const requestedSha = url.searchParams.get("sha256") ?? "";
    if (path !== "manifest.json" && !/^[0-9a-f]{64}$/i.test(requestedSha)) {
      return new Response("sha256 query parameter required", { status: 400, headers: corsHeaders() });
    }
    if (!env.GITHUB_TOKEN) {
      return new Response("GITHUB_TOKEN is missing", { status: 500, headers: corsHeaders() });
    }

    if (path !== "manifest.json") {
      const allowlist = await resourceAllowlist(env);
      if (allowlist === null) {
        return new Response("Resource manifest unavailable", { status: 502, headers: corsHeaders() });
      }
      if (allowlist.get(path) !== requestedSha.toLowerCase()) {
        return new Response("Not Found", { status: 404, headers: corsHeaders() });
      }
    }

    const githubUrl = githubResourceUrl(path);
    let upstream;
    try {
      upstream = await fetch(githubUrl, githubRequestOptions(env));
    } catch {
      return new Response("Resource unavailable", { status: 502, headers: corsHeaders() });
    }
    if (!upstream.ok) {
      return new Response("Resource unavailable", {
        status: upstream.status === 404 ? 404 : 502,
        headers: corsHeaders(),
      });
    }

    if (path === "manifest.json") {
      try {
        const files = await parseManifestAllowlist(upstream.clone());
        if (files !== null) {
          manifestCache = { expiresAt: Date.now() + MANIFEST_CACHE_TTL_MS, files };
        }
      } catch {
        // The desktop client performs the authoritative manifest validation.
        // A malformed catalog must not turn the manifest endpoint into a 502.
      }
    }

    const headers = new Headers(upstream.headers);
    headers.set("Access-Control-Allow-Origin", "*");
    headers.set("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
    // Resource URLs include the manifest SHA as a query parameter.  They are
    // safe to cache immutably; a changed file gets a different cache key. An
    // old client without the SHA query remains uncached. The manifest itself
    // is always uncached so manual checks see catalog changes immediately.
    const cacheableResource = path !== "manifest.json" && /^[0-9a-f]{64}$/i.test(requestedSha);
    headers.set("Cache-Control", cacheableResource ? "public, max-age=31536000, immutable" : "no-store");
    return new Response(request.method === "HEAD" ? null : upstream.body, {
      status: upstream.status,
      headers,
    });
  },
};

async function resourceAllowlist(env) {
  const now = Date.now();
  if (manifestCache.files !== null && manifestCache.expiresAt > now) {
    return manifestCache.files;
  }
  if (manifestRefreshPromise !== null) {
    return manifestRefreshPromise;
  }
  manifestRefreshPromise = loadResourceAllowlist(env);
  try {
    return await manifestRefreshPromise;
  } finally {
    manifestRefreshPromise = null;
  }
}

async function loadResourceAllowlist(env) {
  let upstream;
  try {
    upstream = await fetch(githubResourceUrl("manifest.json"), githubRequestOptions(env));
  } catch {
    return null;
  }
  if (!upstream.ok) {
    return null;
  }
  try {
    const files = await parseManifestAllowlist(upstream);
    if (files === null) {
      return null;
    }
    manifestCache = { expiresAt: Date.now() + MANIFEST_CACHE_TTL_MS, files };
    return files;
  } catch {
    return null;
  }
}

async function parseManifestAllowlist(upstream) {
  const text = await upstream.text();
  if (text.length > 8 * 1024 * 1024) {
    return null;
  }
  const raw = JSON.parse(text);
  const files = new Map();
  if (!raw || !Array.isArray(raw.resources)) {
    return null;
  }
  for (const resource of raw.resources) {
    if (!resource || !Array.isArray(resource.files)) {
      return null;
    }
    for (const file of resource.files) {
      if (
        !file ||
        typeof file.path !== "string" ||
        !file.path.startsWith("resources/") ||
        !/^[0-9a-f]{64}$/i.test(file.sha256)
      ) {
        return null;
      }
      if (files.has(file.path)) {
        return null;
      }
      files.set(file.path, file.sha256.toLowerCase());
    }
  }
  return files;
}

function githubResourceUrl(path) {
  const encodedPath = path.split("/").map(encodeURIComponent).join("/");
  return `https://api.github.com/repos/${OWNER}/${REPO}/contents/${encodedPath}?ref=${encodeURIComponent(BRANCH)}`;
}

function githubRequestOptions(env) {
  return {
    headers: {
      Accept: "application/vnd.github.raw+json",
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "PetNest-Assets-Worker",
    },
    redirect: "follow",
  };
}

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
  };
}
