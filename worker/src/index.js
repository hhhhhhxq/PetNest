const OWNER = "hhhhhhxq";
const REPO = "petnest-resources";
const BRANCH = "main";

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
    let mode = "file";
    if (url.pathname === "/v1/manifest.json") {
      path = "manifest.json";
    } else if (url.pathname === "/v1/archive.zip") {
      mode = "archive";
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
      return new Response("Invalid path", { status: 400 });
    }
    if (!env.GITHUB_TOKEN) {
      return new Response("GITHUB_TOKEN is missing", { status: 500 });
    }

    const githubUrl = mode === "archive"
      ? `https://api.github.com/repos/${OWNER}/${REPO}/zipball/${encodeURIComponent(BRANCH)}`
      : `https://api.github.com/repos/${OWNER}/${REPO}/contents/${parts.map(encodeURIComponent).join("/")}` +
        `?ref=${encodeURIComponent(BRANCH)}`;
    const upstream = await fetch(githubUrl, {
      headers: {
        Accept: "application/vnd.github.raw+json",
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PetNest-Assets-Worker",
      },
      redirect: "follow",
    });
    if (!upstream.ok) {
      return new Response("Resource unavailable", {
        status: upstream.status === 404 ? 404 : 502,
        headers: corsHeaders(),
      });
    }

    const headers = new Headers(upstream.headers);
    headers.set("Access-Control-Allow-Origin", "*");
    headers.set("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
    headers.set(
      "Cache-Control",
      mode === "archive" || path !== "manifest.json" ? "public, max-age=86400" : "public, max-age=60",
    );
    return new Response(request.method === "HEAD" ? null : upstream.body, {
      status: upstream.status,
      headers,
    });
  },
};

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
  };
}
