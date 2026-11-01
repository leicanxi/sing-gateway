# Voice plaza — static site

Source of the static voice plaza (deployed at `https://voice-models.flowbee.top`,
served by Caddy from the webroot, e.g. `/opt/caddy/data/voice-models/`).

- `index.html` / `app.js` — catalog browser (reads `catalog.json`).
- `upload.html` / `upload.js` — self-service voice upload, calls the gateway's
  `/v1/voice-requests` and `/v1/auth/*` same-origin.
- `account.html` / `account.js` — logged-in "my voices" management.
- `catalog.json` — **generated, not committed**: produced on the gateway host by
  `sing-catalog-scrape` (`OCTOP_HOME/sing-voices-catalog.json`) and copied into
  the webroot by the refresh cron.

Deploy: copy this directory (with a fresh `catalog.json`) to the Caddy webroot
that fronts the gateway. There is no build step.
