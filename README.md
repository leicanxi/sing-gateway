# sing-gateway

Self-hosted singing gateway for chat bots: search a song (Bilibili / NetEase),
cut a clip, sing it in an RVC voice via Replicate, and return an audio block.
It also serves the public voice plaza: a browsable catalog of community RVC
models, self-service voice uploads with automatic review, and FlowBee SSO
login for managing your own voices.

Clients (the Octop `sing-song` plugin, the AstrBot plugin, and any future
platform plugin) are thin HTTP clients; they never touch Replicate or the music
sources directly.

```
client plugin (Octop / AstrBot / …)
  → new-api  /v1/chat/completions  model=sing-song  (user's own key)   [or direct]
    → sing-gateway (this project)
      → Bilibili/NetEase search/download → Replicate AICoverGen → disk cache
        → audio block
```

Only the Replicate prediction costs money; search/download and ffmpeg run
locally. AICoverGen already bundles vocal separation, RVC and mixing, so one
prediction is the whole paid step.

## Install

```bash
pip install sing-gateway               # service + tools
pip install "sing-gateway[modelscope]" # + ModelScope uploads (recommended in CN)
pip install "sing-gateway[hf]"         # + Hugging Face uploads
```

Three console scripts are installed: `sing-gateway` (the service),
`sing-catalog-scrape` (refresh the public voice catalog) and
`sing-voice-overrides` (re-point catalog entries whose upstream zip is broken;
run it after a scrape).

## Run the gateway

Install the optional runtime dependencies on the gateway host (the plugin's
install normally does this already):

```bash
uv pip install "yt-dlp>=2025.1.1" "imageio-ffmpeg>=0.5"
```

Start it next to Octop (same host or same Docker network):

```bash
export SING_GATEWAY_TOKEN='choose-a-long-random-secret'
export REPLICATE_API_TOKEN='r8_...'
export SING_VOICE_URL='https://huggingface.co/leicanxi/rvc-models/resolve/main/keine_genso_flat.zip'

sing-gateway            # reads SING_GATEWAY_HOST / SING_GATEWAY_PORT
# or: uvicorn sing_gateway.server.sing:app --host 127.0.0.1 --port 9001
```

Defaults to `127.0.0.1:9001`. A systemd unit and a whitelist example live in
[`deploy/`](deploy/); point new-api's custom channel at `http://<host>:9001/v1`.

### Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `SING_GATEWAY_TOKEN` | — | Required shared secret; new-api's channel key must match |
| `REPLICATE_API_TOKEN` | — | Required; the operator's Replicate account |
| `SING_VOICE_URL` | built-in Keine zip | RVC voice model zip |
| `SING_REPLICATE_MODEL` | `zsxkib/realistic-voice-cloning` | Cover model |
| `SING_REPLICATE_VERSION` | latest | Pin a Replicate version |
| `SING_REPLICATE_BASE_URL` | `https://api.replicate.com/v1` | Replicate API base |
| `SING_PITCH` | `2` | Default semitone shift |
| `SING_START` | `60` | Default clip start (seconds) |
| `SING_DURATION` | `25` | Default clip length (5–600) |
| `SING_GENDER_CACHE_FILE` | `~/.octop/sing-gender-cache.json` | Artist/voice genders for `pitch_mode=auto`; hand-editable, LLM verdicts are cached here |
| `SING_GENDER_LLM_BASE_URL` | falls back to `SING_REVIEW_BASE_URL` | Optional chat model that classifies unknown artists/voices |
| `SING_GENDER_LLM_API_KEY` | falls back to `SING_REVIEW_API_KEY` | Key for that model |
| `SING_GENDER_LLM_MODEL` | falls back to `SING_REVIEW_MODEL` | Model name (default `deepseek-chat`) |
| `SING_INSTRUMENTAL_VOLUME` | `-60` | Default instrumental gain in dB, `-60` (muted) to `+12` (boosted); payload `"instrumental_volume"` overrides per request |
| `SING_BACKUP_VOCALS_VOLUME` | `-60` | Default backup-vocal (harmony) gain in dB, same scale; that stem keeps the original singer's voice; payload `"backup_vocals_volume"` overrides per request |
| `SING_MUSIC_SOURCE` | `bilibili` | Music source for search/download: `bilibili`, `netease`, `qq`, or `auto` (QQ → NetEase → Bilibili, first usable hit wins); payload `"source"` overrides per request |
| `SING_STRICT_SOURCE` | off | Refuse a free recording by another artist when the requested one is paid (see song-choice policy below) |
| `SING_CACHE_TTL_HOURS` | `168` | Disk cache TTL |
| `SING_CACHE_MAX_ENTRIES` | `50` | Disk cache entries (up to 5000) |
| `SING_MAX_CONCURRENCY` | `2` | Concurrent background renders; extra jobs queue |
| `SING_JOB_TTL_SECONDS` | `3600` | Finished job rows kept for status polling |
| `SING_VOICES_FILE` | `~/.octop/sing-voices.json` | Admin-managed voice whitelist |
| `SING_VOICES_CATALOG_FILE` | `~/.octop/sing-voices-catalog.json` | Scraped public catalog (see [Voice catalog](#voice-catalog)) |
| `SING_VOICE_ALIASES_FILE` | `~/.octop/sing-voice-aliases.json` | Extra search aliases, flat JSON (`{"初音": ["hatsune miku"]}`) |
| `SING_VOICE_PLAZA_URL` | `https://voice-models.flowbee.top` | Voice plaza link returned by the guide endpoints |
| `SING_BILI_COOKIES` | — | Path to a Netscape `cookies.txt` for Bilibili (see HTTP 412 below) |
| `SING_QQ_COOKIES` | — | Path to a Netscape `cookies.txt` for QQ Music; a logged-in account unlocks VIP tracks |
| `SING_PROXY` | — | Optional proxy (`http://host:port`) for Bilibili search/download |
| `SING_NCM_API` | — | Base URL of a running ncm-api sidecar (see below); unlocks VIP tracks |

### Key selection (`pitch_mode=auto`)

Passing `"pitch_mode": "auto"` makes the gateway choose the key instead of
asking the caller for semitones. It compares the gender of the song's artist
with the gender of the chosen voice:

| Artist | Voice | Shift |
|--------|-------|-------|
| male | female | `+12` |
| female | male | `-12` |
| same | same | `0` |

The shift is applied to the **whole mix** — vocals and accompaniment — so the
cover stays in key. That is also what an explicit `pitch_mode=male-to-female`
or `female-to-male` now does: the octave is folded into one key shift instead
of transposing the vocal alone (which used to leave the instrumental in the old
key). `pitch_mode=no-change` plus an integer `pitch` keeps the old behaviour
when callers care.

Genders are resolved in trust order:

1. `gender` on the voice entry in the voices JSON (`"male"`/`"female"`, also
   accepts `男`/`女`) — authored by us, so it wins;
2. a gender word in the voice label (`Female`, `Girl`, `Male`, …), derived by
   `voice_meta` — deterministic, no cost, and it covers most of the scraped
   catalog;
3. `SING_GENDER_CACHE_FILE` — a small JSON you can edit by hand:
   `{"artists": {"杨丞琳": "female"}, "voices": {"keine": "female"}}`;
4. an optional chat model (`SING_GENDER_LLM_*`, or the review model), called at
   most once per artist/voice and then cached in that file.

The label guess outranks the cache and the model because those are machine
verdicts too, and the guess is deterministic. If a guess is wrong, the override
channel is the voice entry's own `gender` field (it survives a catalog
re-scrape), not the cache.

If either gender is unknown the render still runs with the normal
`SING_PITCH` fallback, so auto mode never fails a request. The response block
reports the shift it used as `pitch` and sets `pitch_auto: true`.

### Bilibili HTTP 412

Bilibili risk-controls datacenter IPs: on a cloud VPS every request — search
included — can fail with `HTTP Error 412 Precondition Failed` regardless of
headers.

**Easiest fix on an overseas host: set `SING_MUSIC_SOURCE=netease`.** NetEase's
anonymous APIs (plain search JSON + direct mp3 links for free songs) work from
datacenter IPs and need no cookies; VIP-only songs fail with an explicit
"needs VIP" error, so pick free tracks.

The Bilibili-specific alternatives: export cookies from a logged-in account
while visiting bilibili.com (browser extension such as "Get cookies.txt
LOCALLY"), place the file on the gateway host, and set `SING_BILI_COOKIES` to
its path. The file is re-read on every download, so refreshing an expired
cookie file takes effect without a restart. Alternatively set `SING_PROXY` to
route music traffic through a different exit node.

**QQ Music is the other cookie-free option.** `SING_MUSIC_SOURCE=qq` (or
`"source": "qq"` per request) searches QQ Music anonymously and resolves a
stream through its vkey endpoint. Free tracks download as m4a; VIP and
digital-album tracks answer `104003`, which becomes the same explicit 400 the
NetEase path uses instead of an empty render.

For VIP tracks, export cookies from a logged-in QQ Music account (same
"Get cookies.txt LOCALLY" flow as Bilibili) and point `SING_QQ_COOKIES` at the
file. The gateway reads `uin` and `qqmusic_key` from it and sends the account
with the vkey request; the file is re-read when it changes, so refreshing an
expired session needs no restart. One shared account is one session: heavy
concurrency can trip QQ's risk control, and the account's own rights apply.

**Cross-source fallback.** With `"source": "auto"` the gateway tries QQ, then
NetEase, then Bilibili and keeps the first source that yields a usable
recording. That covers the common case where a track is VIP-only on one service
but free on another. Each attempt is a search plus up to five probes, all inside
the background job.

**Song-choice policy.** When the requested singer has no free recording, the
gateway may fall back to a free recording of the same title by someone else
(usually a re-upload, sometimes a cover), because availability matters more than
an exact match for a cover service. Hits are ranked before probing:

1. the best title match (the reference recording);
2. same-artist alternatives;
3. clean-titled uploads by another artist;
4. decorated titles (live, cover, piano, remix …).

Instrumental uploads and AI covers (`AI翻唱`, `RVC`, …) are dropped outright:
one has no vocal to convert, the other would stack artifacts.
`SING_STRICT_SOURCE=1` turns the fallback off and fails instead. Either way the
result says what was used: `artist` is the recording that was sung,
`source_match` is `same-artist` / `other-artist` / `unknown` (Bilibili uploads,
where the artist field is the uploader), and `original_artist` names the
requested singer when it differs.

Third-party VIP "resolver" APIs are deliberately not wired in: the ones used by
comparable projects are either dead (api.lolimi.cn no longer resolves), paid
key-only services, or return unrelated songs. If you have a working provider,
the cookie path above is the more stable way to unlock the same catalogue.

When searching by song name, the gateway probes up to five hits per source:
tracks whose clip window has no lyric line are skipped, and for QQ a hit with no
anonymous stream is skipped in favour of the next one. The `QQ` probe costs one
extra request per candidate (a few hundred milliseconds), and it runs inside the
background job.

### Expanding the NetEase catalog (ncm-api sidecar)

Anonymous NetEase APIs only issue audio links for free tracks. The community
[ncm-api](https://github.com/moeyy01/ncm-api) project (NeteaseCloudMusicApi
Enhanced, Node.js) maintains "unblock" parameter tricks that often get VIP
tracks too — sampled hit rate was 11/11: some full 320kbps tracks, most a
~45s free-trial clip (enough for short covers). Run it as a sidecar:

```bash
docker run -d --name ncm-api --restart always \
  -p 127.0.0.1:3010:3000 moefurina/ncm-api:latest
export SING_NCM_API=http://127.0.0.1:3010
```

The gateway resolves audio URLs through the sidecar first and falls back to
the bare endpoint (free tracks only) when it fails, so a broken/updated
sidecar degrades gracefully. Trial clips are trimmed within their own
duration automatically.

Caveats: the unlock tricks are community-maintained attempts against
NetEase's unofficial API — they can stop working at any time (the fallback
path keeps free tracks working); trial clips are typically ~45 seconds.

## Voices

Two JSON files, both re-read on lookup (mtime-cached), so edits apply without
a restart. Lookups check the whitelist first, then the public catalog.

**Whitelist** — curated voices (built-in defaults + admin-approved custom),
shared by the gateway and its client plugins:

```
~/.octop/sing-voices.json
```

```json
{
  "keine": {
    "label": "Keine",
    "url": "https://huggingface.co/leicanxi/rvc-models/resolve/main/keine_genso_flat.zip",
    "gender": "female"
  },
  "cirno": {
    "label": "Cirno",
    "url": "https://huggingface.co/Sergeantzero/Touhou_Project/resolve/main/Cirno%20%28Touhou%20Cannonball%29.zip"
  }
}
```

A plain string value (`"keine": "https://..."`) is accepted as the URL. The
optional `gender` field feeds [`pitch_mode=auto`](#key-selection-pitch_modeauto);
when it is missing the gateway falls back to the gender cache and then to the
optional classifier.

**Public catalog** — machine-scraped community models, browsable on the voice
plaza and selectable by name:

```
~/.octop/sing-voices-catalog.json   # generated by `sing-catalog-scrape`
```

- `sing_song(voice="cirno")` resolves whitelist names first, then catalog names.
- An empty name uses the whitelist's `keine` entry (or `SING_VOICE_URL` on the
  gateway when it is set).
- An unknown name returns `400 unknown voice '...'` **without** listing the
  available names: whitelist entries (including future per-user custom voices)
  rely on staying unknown, and the plaza is the only public browsable surface.
- Users cannot pass a raw RVC URL. New custom voices must be reviewed by the
  admin and added to this file, because `.pth` checkpoints are untrusted
  code/data and arbitrary URLs also create SSRF risk.
- `GET /v1/voices` and the `sing-voices` chat model only return a guide block
  pointing at the plaza (`{"type": "guide", "plaza_url": ...}`) — they no
  longer enumerate voices.

### Server deployment

Set `SING_VOICES_FILE` to an absolute path on the server and use the same value
for both the Octop service (plugin) and the gateway:

```bash
sudo mkdir -p /etc/octop
sudo cp deploy/sing-voices.example.json /etc/octop/sing-voices.json
export SING_VOICES_FILE=/etc/octop/sing-voices.json
```

Docker: mount the file and set the same environment variable, for example
`-v /srv/octop/sing-voices.json:/config/sing-voices.json -e SING_VOICES_FILE=/config/sing-voices.json`.

If `SING_VOICES_FILE` is unset, the fallback is `$OCTOP_HOME/sing-voices.json`,
then `~/.octop/sing-voices.json` (handy for local development).

Populate the catalog on the gateway host (Hugging Face is reachable from
overseas VPS; only direct HF zip links are kept, Google Drive sources are
skipped):

```bash
sing-catalog-scrape                 # full catalog, ~640 pages
sing-catalog-scrape --limit 200
```

## Configure new-api

1. Create a **custom / OpenAI-compatible** channel with:
   - Base URL: `http://<octop-host>:9001/v1`
   - Key: the same value as `SING_GATEWAY_TOKEN`
2. Add model `sing-song` to the channel.
3. Add models `sing-voices` and `sing-search` to the channel too and price both
   at **0**: clients
   use `sing-voices` to fetch the voice plaza link and `sing-search` to search
   songs (the confirm step) through new-api. Neither runs a generation; the
   gateway only returns the guide/candidate block. Directly reachable clients
   use `POST /v1/songs/search` instead.
4. Set the `sing-song` price to **per-call billing** (`QuotaType=1`). With the
   1:1 RMB/USD convention, `0.7` per call covers the worst-case cold start
   (about $0.08 of T4 time) with a healthy margin.
5. Raise the relay timeout to **at least 300 seconds**: a warm generation is
   about 70 seconds and a cold start can take 2–4 minutes. Current new-api
   builds have no UI field for this — set env `RELAY_TIMEOUT=300` on the
   new-api container instead.

The gateway returns a standard chat completion whose assistant content is a
JSON audio block. `usage` is zero because billing is per-call.

### Async job API

Long generations can be submitted as a background job instead of holding one
HTTP request open. The same endpoint is served on the gateway root and is the
contract every client plugin (AstrBot, Octop, DSH) uses:

```http
POST /sing/v1/jobs
Authorization: Bearer <SING_GATEWAY_TOKEN>
{"song": "雨爱", "voice": "keine", "start": 60, "duration": 60}
```

Optional mixing fields (dB gains, `-60` muted to `+12` boosted): `"instrumental_volume"`
keeps the original accompaniment under the converted vocal, `"backup_vocals_volume"`
keeps the backing-harmony stem. Note that AICoverGen runs RVC on the main vocal
only, so that stem is the **original singer's** harmony — turning it up mixes the
two voices. Both default to `-60` (vocals only); pass `0` for a full-band cover,
or a positive value (up to `+12`) to push that stem above its source level.

Key fields: `"pitch"` (semitones) and `"pitch_mode"` (`no-change`,
`male-to-female`, `female-to-male`, or `auto` — see
[Key selection](#key-selection-pitch_modeauto)). With `"song"` the gateway
already knows the artist; with a direct `"url"` you can pass `"artist"` so auto
mode has a source gender to compare against.

```json
{"id": "job_...", "status": "queued", "stage": "queued", ...}
```

```http
GET /sing/v1/jobs/job_...
```

```json
{
  "id": "job_...",
  "status": "succeeded",
  "stage": "done",
  "audio_url": "https://cdn/cover.mp3",
  "filename": "雨爱.mp3",
  "title": "雨爱",
  "artist": "杨丞琳",
  "duration_seconds": 60,
  "cached": true,
  "pitch": 12,
  "pitch_auto": true,
  "source_match": "same-artist"
}
```

When a free recording by another artist was used instead, `source_match` is
`other-artist` and `original_artist` carries the requested singer; Bilibili
results report `unknown` because their artist field is the uploader.

- Statuses: `queued`, `running`, `succeeded`, `failed` (`failed` carries
  `error`). Clients poll every few seconds; `SING_JOB_TTL_SECONDS` keeps
  finished rows around for late polls.
- Identical submissions share one job (same song/url + artist + voice +
  start/duration + pitch mode + mixing gains), so double-clicks and retries do
  not re-render.
- Only `SING_MAX_CONCURRENCY` renders run at once; the rest wait in `queued`.
- `duration_seconds` is the actual clip length (a VIP preview can be shorter
  than the requested duration) and `cached` marks a disk-cache hit. Both let a
  billing layer charge per second and price cache hits differently.
- `POST /v1/sing/jobs` is an alias, so clients that already speak `/v1` can use
  it without changing their base URL.
- Job state is in-process: run a single gateway worker (the systemd unit does).
  A gateway restart loses finished rows but not the disk cache, so a client
  retry usually hits the cache and returns in about a second.

The synchronous `POST /v1/chat/completions` path stays for old clients; it
returns the same `duration_seconds` / `cached` fields in the audio block.

### Per-second billing (`sing` task plugin)

The `sing` task plugin in the `flowbee-api` fork wraps this job API so new-api
tracks the async task and settles the bill:

1. Build/deploy a new-api image that includes `plugins/tasks/sing/plugin.js`.
2. Create a **Task Plugin** channel:
   - Base URL: `http://<host>:9001` (the gateway root, without `/v1`)
   - Key: the same value as `SING_GATEWAY_TOKEN`
   - Bind plugin `sing`, add model `sing-song`
3. Keep the ordinary channel above for the synchronous `chat/completions`
   path. Both providers may share `sing-song`; price them separately.
4. Invoice the task provider per second. Task expressions return USD directly
   (`billing_setting.plugin_billing_expr`, key `sing::sing-song`):
   - flat: `tier("base", u("seconds") * 0.0032)` → $0.0032/s
   - cache discount:
     `u("cached") ? u("seconds") * 0.0005 : u("seconds") * 0.0032`
5. Clients submit `POST /sing/v1/jobs` with `"model": "sing-song"` and poll
   `GET /sing/v1/jobs/{id}`. AstrBot does this automatically with
   `transport=auto` (falls back to the sync endpoint on old gateways).

new-api reserves the requested duration at submit (`extractUsage`) and settles
on the gateway's actual `duration_seconds` and `cached` at completion
(`extractUsageOnComplete`). A failed render refunds; a cache hit can be
discounted or made free by the expression.

## Voice catalog

Voice names are picked on the voice plaza (`SING_VOICE_PLAZA_URL`, default
`https://voice-models.flowbee.top`) and passed back by name. The endpoints
below only return the plaza link so every client plugin (Octop, AstrBot, DSH, …)
can show the same guidance:

- Direct gateway access: `GET /v1/voices` with the gateway token returns
  `{"object": "list", "data": [], "note": "...", "plaza_url": "..."}`.
- Behind new-api: unknown paths like `GET /v1/voices` are not relayed. Post
  `/v1/chat/completions` with `"model": "sing-voices"` instead (include a
  dummy user message — new-api rejects empty `messages` lists before
  forwarding). The assistant content is a guide block:

  ```json
  {
    "type": "guide",
    "text": "音色列表已迁移到音色广场：打开 plaza_url 挑选音色，点歌时把音色名传给 voice。…",
    "plaza_url": "https://voice-models.flowbee.top"
  }
  ```

Keep `sing-voices` priced at 0 on new-api — the response `usage` is all zeros,
so the call is free either way.

### Catalog browsing API

The plaza no longer ships the whole scraped catalog to the browser. It pages
through the gateway instead:

```text
GET /v1/voices/catalog?q=&lang=&gender=&type=&sort=hot|favorites|new|label&limit=60&offset=0
```

- `sort=hot` orders by `voice_stats.uses`, then upstream favorites; `new` uses
  the source `weights_id`; the response includes `total`, `items` and
  `next_offset`.
- Each item may include `preview_url` — the source's A/B sample (female first,
  male fallback). The browser plays it with `preload="none"` and only one
  preview at a time. `sing-catalog-scrape --sample-base …` overrides the
  object-store base if a deployment cannot reach the default mirror.
- Facets (`language`, `gender`, `type`, `rvc_version`, feature tags) are
  derived from the scraped label at read time and stored by the scraper.
- `q` is normalized and expanded through a small Chinese/English alias table
  (`初音` → `Hatsune Miku`, `原神` → `Genshin Impact`, …); prefix matches work
  while the user is typing. Add custom aliases with `SING_VOICE_ALIASES_FILE`
  (flat JSON: `{"初音": ["hatsune miku", "miku"]}`).
- The endpoint is public; the plaza calls it same-origin through Caddy.

## Voice submissions (self-service uploads)

FlowBee-mode users (who cannot edit this whitelist themselves) submit their own
RVC models from the plaza upload page. Submissions are auto-reviewed and
approved without a human queue:

1. **Rules layer** (always on): the archive must be a zip with a `.pth`, no
   script/executable members, no path traversal, within the size cap, and its
   pickles must not reference dangerous globals (`os`, `posix`, `subprocess`,
   `ctypes`, ...). This is the gate that protects the operator's Replicate
   token from `.pth` pickle payloads.
2. **LLM layer** (optional): a compact summary (label, FlowBee user, source,
   file manifest, deduplicated pickle globals) is sent to a cheap chat model
   which approves or rejects. When it is not configured or the call fails, the
   rules verdict is used instead.

Endpoints (public, no gateway token — the plaza calls them same-origin):

Uploading requires a FlowBee login; submissions are bound to the account that
created them and each user can manage (list/delete) their own from the plaza.

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `GET /v1/auth/login?next=…` | public | sets a short-lived state cookie and redirects to the FlowBee SSO relay |
| `GET /v1/auth/callback?code&state` | public | verifies the FlowBee ticket, sets the session cookie, redirects back |
| `GET /v1/auth/me` | session | `{uid, username, name}` or 401 |
| `POST /v1/auth/logout` | session | clears the session cookie |
| `POST /v1/voice-requests` | session | multipart (`label`, `file` \| `url`, optional `description`/`language`/`gender`/`tags`) or JSON; identity comes from the session |
| `GET /v1/voice-requests/mine` | session | the caller's submissions, including `visibility` |
| `POST /v1/voice-requests/{id}/publish` | session (owner) | list an approved voice on the plaza |
| `POST /v1/voice-requests/{id}/unpublish` | session (owner) | remove it from the plaza (the name still works for anyone who knows it) |
| `DELETE /v1/voice-requests/{id}` | session (owner) | removes the whitelist entry **and** the stored model file |
| `POST /v1/voice-requests/{id}/moderate` | gateway token | `{moderation: "ok"\|"blocked", reason}` for takedowns; blocking also unpublishes |
| `GET /v1/voices/public?limit=&sort=new\|hot` | public | published community voices (no uid/username in the projection) |
| `GET /v1/voice-requests/{id}` | public | submission status (the id is the capability) |

### Login (FlowBee SSO)

The gateway never sees passwords. FlowBee (new-api) exposes a generic relay
page `GET /sso/<client>?state=<opaque>`: an anonymous visitor is sent to the
sign-in page with a redirect back, and a logged-in user's browser is handed a
**60-second** HS256 ticket whose `aud` is the client id, then redirected to the
callback registered for that client (`SSO_CLIENTS`).

The gateway verifies the ticket with that client's secret (`SING_SSO_SECRET`,
`aud` must equal `SING_SSO_CLIENT_ID`) and mints its own session JWT. The legacy
`/sso/octop` relay + `/api/user/octop_sso` pair still works for migration.

| Variable | Default | Meaning |
|----------|---------|---------|
| `SING_JWT_SECRET` | — | Session JWT signing secret; empty disables login **and** uploads (fail closed) |
| `SING_JWT_TTL_HOURS` | `168` | Session lifetime |
| `SING_SSO_CLIENT_ID` | `sing` | Relying-party id registered in FlowBee's SSO client table (also the expected `aud`) |
| `SING_SSO_SECRET` | — | That client's secret in FlowBee's `SSO_CLIENTS` |
| `SING_SSO_URL` | `https://flowbee.top/sso/sing` | FlowBee entry for this relying party (the relay page path carries the client id) |
| `SING_PLAZA_BASE` | `https://voice-models.flowbee.top` | Plaza origin used for post-login redirects |

Set `OCTOP_SSO_SECRET` / `OCTOP_SSO_CALLBACK=https://<plaza-host>/v1/auth/callback`
on the new-api container too (restart required there).

Security notes: the session cookie is httpOnly + Secure + SameSite=Lax and
host-only to the plaza domain; SSO state travels in a one-time HttpOnly cookie
(600 s) compared with `hmac.compare_digest`; state-changing requests additionally
check the `Origin`/`Referer` host. A disabled FlowBee account keeps a valid
session for at most `SING_JWT_TTL_HOURS` (no per-request callback to new-api).

Approved voices are written into the whitelist with a random 4-hex name
suffix (`atri-7f3k`) so a submitted voice stays private by default. Owners can
publish an approved voice to the plaza; publishing only changes its listing
state, not the name — anyone who knows the name can still use it after an
unpublish. Deleting is the operation that removes it from the whitelist.

Submission state, publication state and the audit trail live in SQLite
(`SING_DB_PATH`, default `~/.octop/sing.db`):

- `voice_requests` — current submission/publication state (source of truth)
- `voice_events` — append-only lifecycle audit (`approved`/`rejected`/
  `published`/`unpublished`/`blocked`/`deleted`/`imported`)
- `voice_stats` — per-voice `uses`/`last_used` counters for the hot list

The old `sing-voice-requests.json` is imported once on first start and then
kept only as an operator backup. Tags and facets (`language`, `gender`,
`rvc_version`, free-form `tags`) are stored with the submission; the plaza
projects them, while the resolver ignores them.

`sing-voices.json` remains the runtime resolver index. Approved rows are
mirrored into it, and the gateway reconciles it on startup: missing approved
entries are restored from SQLite, while deleted/rejected ones are removed.
Manual entries with no submission row are never touched.

File storage priority — the gateway host can keep zero model files:

1. **Hugging Face** (`SING_HF_REPO` + `SING_HF_TOKEN`): the archive is uploaded
   to `{repo}/resolve/main/{SING_HF_PREFIX}/{name}.zip`. Requires
   `pip install huggingface_hub` (optional runtime dependency) and outbound
   access to huggingface.co — note that `hf-mirror.com` only proxies
   **downloads**, its upload API redirects back to huggingface.co.
2. **ModelScope** (`SING_MS_REPO` + `SING_MS_TOKEN`): the archive is uploaded
   to `{repo}/resolve/master/{SING_MS_PREFIX}/{name}.zip`
   (e.g. `https://modelscope.cn/models/…/resolve/master/uploads/…` — publicly
   fetchable, so Replicate can pull it). Requires `pip install modelscope`.
   This is the working choice on hosts that cannot reach Hugging Face
   (e.g. mainland/adjacent networks).
3. **Local disk** (`SING_UPLOAD_DIR` + `SING_PUBLIC_BASE_URL`): served from
   `{SING_PUBLIC_BASE_URL}/uploads/…`.

Link submissions keep the submitted URL after the archive is downloaded and
validated.

| Variable | Default | Meaning |
|----------|---------|---------|
| `SING_HF_REPO` | — | Hugging Face repo for uploaded models (e.g. `user/rvc-models`) |
| `SING_HF_TOKEN` | — | Write token for `SING_HF_REPO` |
| `SING_HF_PREFIX` | `uploads` | Path prefix inside the HF repo |
| `SING_MS_REPO` | — | ModelScope repo for uploaded models (e.g. `user/rvc-voice-uploads`) |
| `SING_MS_TOKEN` | — | ModelScope access token (`ms-…`) |
| `SING_MS_PREFIX` | `uploads` | Path prefix inside the ModelScope repo |
| `SING_UPLOAD_DIR` | — | Local directory for uploaded zips (fallback when HF is unset) |
| `SING_PUBLIC_BASE_URL` | — | Public base URL that serves `SING_UPLOAD_DIR` (e.g. the plaza origin) |
| `SING_UPLOAD_MAX_MB` | `300` | Per-submission archive size cap |
| `SING_UPLOAD_DAILY_LIMIT` | `5` | Submissions per client IP per day (`0` disables the limit) |
| `SING_DB_PATH` | `~/.octop/sing.db` | SQLite database for submissions, publication state, events and usage |
| `SING_VOICE_REQUESTS_FILE` | `~/.octop/sing-voice-requests.json` | Legacy submission JSON, imported once into SQLite |
| `SING_REVIEW_BASE_URL` | — | OpenAI-compatible base URL for LLM review (disabled when empty) |
| `SING_REVIEW_API_KEY` | — | Key for the review model |
| `SING_REVIEW_MODEL` | `deepseek-chat` | Review model name |

## Client plugins

Use the acting user's own FlowBee key (no shared-key fallback):

1. The user configures their model credential in Octop (Base URL such as
   `https://flowbee.top/v1` and their FlowBee key).
2. In the plugin's `sing_song` settings:
   - `billing_mode=flowbee`
   - `flowbee_model=sing-song`
   - `flowbee_base_url` can stay empty; the user's Base URL is used.
3. If the user has no key, `sing_song` returns a clear error instead of
   charging the operator's account.

Octop injects the resolved user credential into the run's internal tool context
(`plugin_user_credential`); it is not part of the prompt, tool output, or agent
config.

## AstrBot / other clients

Ready-made AstrBot plugin:
[`leicanxi/astrbot_plugin_deepseek_sing`](https://github.com/leicanxi/astrbot_plugin_deepseek_sing)
(config page supports FlowBee and self-hosted modes, voice list pull, and a
self-managed whitelist file).

Any client with an OpenAI-compatible provider can use the same model directly:

- Base URL: `https://flowbee.top/v1`
- Model: `sing-song`
- Key: the user's FlowBee key

The gateway accepts either a JSON user message (`{"song": "...", "start": 60}`)
or plain text (`雨爱`). Plain text is treated as the song name.

## Notes

- Song-level failures — a NetEase VIP track with no anonymous audio link, or a
  query that finds nothing — return HTTP **400** with the reason, not 502.
  Relays like new-api treat 4xx as non-retryable and pass the message to the
  user; a 502 would burn channel retries and end in a misleading
  "no channel available" error.

- The clip sent to Replicate is cut to lossless WAV, so RVC never hears a second
  mp3 generation. The *returned* file is still the model's own mp3:
  AICoverGen exports mp3 without a bitrate (ffmpeg's 128 kbps default) and only
  offers WAV as an alternative, whose ~10 MB/minute URLs are too large for QQ
  voice/file sends. Raising that ceiling means running our own inference
  pipeline instead of `zsxkib/realistic-voice-cloning`.
- Returned audio URLs are Replicate delivery URLs (public), so QQ can fetch
  them directly. Cache hits return the original public delivery URL stored in
  the cache entry (validated with a HEAD request; stale or pre-upgrade entries
  regenerate once and refresh the stored URL).
- Cache hits still count as one new-api call unless you create a separate
  lower-priced model for them.
- Keep `sing-song` at or above 0.7 per call under the 1:1 convention; typical
  cost is $0.016–0.054 and the cache hit cost is near zero.


## Voice plaza web

The plaza frontend lives in [`web/voice-plaza/`](web/voice-plaza/): the catalog
browser, the upload drawer and the account page are a Vite + React 19 app using
HeroUI v3 (`dist/index.html` and `dist/account.html`). It calls the gateway same-origin
(`/v1/voices` guide, `/v1/voices/catalog`, `/v1/voices/public`,
`/v1/voice-requests*`, `/v1/auth/*`); deploy the built files to any static
webroot fronting the gateway (the FlowBee host uses Caddy at
`/opt/caddy/data/voice-models/`).

```bash
cd web/voice-plaza
pnpm install
pnpm dev     # local dev on :5173, /v1 proxied to 127.0.0.1:9001
pnpm build   # dist/ — copy this to the webroot
```

Hashed files under `dist/assets/` can be cached immutably; serve `index.html`
with a short cache.

The gateway reads the catalog from `SING_VOICES_CATALOG_FILE` on its own host,
so the old webroot `catalog.json` copy is no longer required by the frontend.
Keep it only if another consumer still reads it.

## License

GNU AGPL-3.0-or-later (see [LICENSE](LICENSE)). Versions up to 0.1.0 were
released under MIT; later versions are AGPL so that hosted deployments of
modified versions share their source.
