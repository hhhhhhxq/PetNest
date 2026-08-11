# PetNest resource Worker

This Worker keeps `petnest-resources` private while exposing only the files needed by PetNest.

## Dashboard deployment

1. Paste `src/index.js` into the Worker editor.
2. Add a Secret variable named `GITHUB_TOKEN`.
3. Deploy the Worker.
4. Test `/v1/manifest.json`, `/v1/archive.zip`, and (for compatibility) `/v1/files/resources/countdown/cream.png`.

`/v1/archive.zip` proxies GitHub's branch zipball so a new client can download
the complete catalog in one request. The client still falls back to the
per-file route when an older Worker has not been redeployed yet.

The token must never be committed to this repository or embedded in PetNest. The current classic token is a temporary read gateway; replace it with a fine-grained read-only token when GitHub's token creation flow works again.
