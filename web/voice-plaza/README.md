# Voice plaza — static site

Source of the static voice plaza (deployed at `https://voice-models.flowbee.top`,
served by Caddy from the webroot, e.g. `/opt/caddy/data/voice-models/`).

- `index.html` / `app.js` — catalog browser (paged through
  `GET /v1/voices/catalog`) plus a "社区公开" section fed by
  `GET /v1/voices/public`.
- `upload.html` / `upload.js` — self-service voice upload, calls the gateway's
  `/v1/voice-requests` and `/v1/auth/*` same-origin; approved voices can be
  published to the plaza from the result panel.
- `account.html` / `account.js` — logged-in "my voices" management, including
  publish/unpublish and share-text copy.
- `catalog.json` — legacy static copy of the scraped catalog. The browser no
  longer fetches it; the gateway reads `SING_VOICES_CATALOG_FILE` on its own
  host. Keep or drop the webroot copy independently.

Deploy: copy this directory to the Caddy webroot that fronts the gateway and
make sure `/v1/*` is proxied to the gateway. There is no build step.
