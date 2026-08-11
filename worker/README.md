# PetNest resource Worker

This Worker keeps `petnest-resources` private while exposing only the files needed by PetNest.

## Dashboard deployment

1. Paste `src/index.js` into the Worker editor.
2. Add a Secret variable named `GITHUB_TOKEN`.
3. Deploy the Worker.
4. Test `/v1/manifest.json` and a resource URL with its manifest SHA, for example
   `/v1/files/resources/countdown/cream.png?sha256=<64-char-sha256>`.

The Worker intentionally exposes only `manifest.json` and paths below
`resources/`. It does not proxy GitHub's branch zipball because that would
make the entire private repository downloadable. Resource requests are also
checked against the manifest allowlist and must include the matching SHA-256,
so source/debug files and arbitrary cache keys are rejected. The client
downloads resource files independently and verifies each SHA-256. Only those
immutable URLs are edge-cached; the manifest is always uncached for immediate
manual checks. The Worker keeps the allowlist in an isolate for at most 10
seconds, so a newly published file may take a few seconds before its first
request is accepted.

The token must never be committed to this repository or embedded in PetNest. The current classic token is a temporary read gateway; replace it with a fine-grained read-only token when GitHub's token creation flow works again.
