# soulx-svc — zero-shot singing voice conversion Cog

Wraps [Soul-AILab/SoulX-Singer](https://github.com/Soul-AILab/SoulX-Singer) SVC
so the gateway can sing a clip in a voice described by a **5–30 second
reference recording** instead of a trained RVC `.pth`.

```
target clip ──► BS-RoFormer karaoke separation ──► vocals + accompaniment
reference  ──► F0 (RMVPE) ─┐
target     ──► F0 (RMVPE) ─┴─► SoulX-Singer-SVC (32 steps, cfg 3) ──► converted vocal
                                                              └─► optional accompaniment mix ──► mp3
```

Upstream is Apache-2.0 (code and weights). This directory only adds the serving
glue; the model code is cloned at build time and pinned by commit
`81aeb3ae772c70093c3de74dc23c92d983801ae4`.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `target_audio` | — | Song clip, up to 600s. Separated internally. |
| `reference_audio` | — | Clean 5–30s solo singing, no accompaniment or heavy reverb. |
| `auto_shift` | `true` | Match registers from the two F0 medians. |
| `pitch_shift` | `0` | Manual semitones; ignored when `auto_shift` is on. |
| `n_steps` | `32` | Flow-matching steps. Lower is faster and rougher. |
| `cfg_scale` | `3.0` | Classifier-free guidance. |
| `seed` / `random_seed` | `42` / `false` | Reproducible output vs a fresh seed per call. |
| `instrumental_volume` | `-60` | Accompaniment gain in dB; `-60` returns vocals only. |
| `reference_vocal_sep` | `false` | Separate the reference too (only for non-dry clips). |
| `output_format` | `mp3` | `mp3` (192 kbps) or `wav`. |

Output is one audio file.

## Build and push

```bash
pip install cog
# Option A: browser/CLI token from https://replicate.com/auth/token
cog login
# Option B: the r8_ API token works as a registry password
echo "$REPLICATE_API_TOKEN" | docker login r8.im -u <account> --password-stdin

cog push r8.im/<account>/soulx-singer-svc
```

The built image is large (~34GB uncompressed): CUDA devel base, torch's bundled
CUDA libraries, and the 2.7GB checkpoint. Budget ~40GB of free disk for the
build plus push, and prefer a host with a stable upload link — large blob
uploads are the part that fails first on an unreliable connection.

`cog push` builds locally, and the build clones GitHub and downloads weights
from Hugging Face. Run it on a host that can reach both — the gateway VPS
works; a mainland network that cannot resolve `github.com` will fail during
`git clone`. If you must build from such a host, vendor the upstream tree into
this directory and drop the clone step.

This `cog.yaml` bakes only the small Whisper-base encoder into the image. The
SVC checkpoint, karaoke separator and RMVPE (about 3.5GB) are fetched by
`predict.py`'s `setup()` on the first cold start and then reused for the life
of that container. That keeps the image small enough to build and push on a
48GB host — the published `leicanxi/soulx-singer-svc` version works this way.
To bake the weights in instead, re-add the three `curl` download steps under
`build.run`; `setup()` skips files that already exist.

A first prediction therefore takes ~5 minutes (weight download) before the
~3 minutes of inference for a 4-minute clip. A warm container is much faster.

Hardware: T4 (16GB) is enough. Upstream measured ~1.6–2.7GB peak VRAM for the
SVC model alone at fp16 and RTF ≈ 0.66; separation and F0 add a few seconds.
A 6GB card is not enough (upstream issues confirm OOM).

## Gateway wiring

```bash
export SING_SVC_MODEL='<account>/soulx-singer-svc'
# optional pin instead of tracking latest:
# export SING_SVC_VERSION='<version id from the Replicate model page>'
export SING_SVC_N_STEPS=32
export SING_SVC_CFG=3.0
export SING_SVC_SEED=42
```

Any voice entry whose URL is an audio file is treated as a reference voice:

```json
{
  "my-voice-a1b2": {
    "label": "我的声音",
    "url": "https://cdn.example.com/my-voice-a1b2.mp3",
    "gender": "female"
  }
}
```

RVC zips keep working unchanged. With `pitch_mode=auto` the gateway sends
`auto_shift=true` and skips the gender classifier: SoulX resolves the key from
F0 medians itself.

## Simpler test before publishing

```bash
cog predict \
  -i target_audio=@clip.wav \
  -i reference_audio=@ref.wav \
  -i instrumental_volume=0
```

Use a real 20–30s phone recording, a clean acapella, and a noisy clip to see
where the upload gate needs to be strict.

## Failure tokens

`predict` raises values the gateway maps to user-facing messages:

- `REFERENCE_TOO_SHORT` — reference decoded to less than 3s.
- `REFERENCE_NO_VOCAL` / `TARGET_NO_VOCAL` — less than 5% of frames are voiced.
- `INVALID_AUDIO` — ffmpeg could not decode the input.

Input download failures are reported by Cog itself; the gateway matches
`reference_audio` plus a download error and returns a retry message.

## Known limitations (v1)

- **No backup-vocal preservation.** Upstream separates karaoke-style
  (vocals + accompaniment), so harmony is folded into one of the two stems.
  The RVC backend's `backup_vocals_volume` knob has no equivalent here.
- **No dereverb.** The dereverb model is skipped to match upstream's SVC
  pipeline and save VRAM. Reverb in the reference carries into the output.
- **Reference quality is the ceiling.** A 30s phone recording works; a clip
  with music under it does not. Gate uploads on duration, mono, F0 coverage
  and vocal ratio before accepting.
- Chinese/English/Cantonese are the training languages; other languages are
  untested.
- Zero-shot timbre similarity is below a well-trained RVC model. This backend
  is the zero-effort tier, not a replacement for training.

## License

Upstream SoulX-Singer code and weights are Apache-2.0. The karaoke separator
(`becruily/mel-band-roformer-karaoke`) and RMVPE are pulled from the upstream
preprocess bundle under their respective licenses. Keep the upstream `LICENSE`
in the image (the clone includes it).
