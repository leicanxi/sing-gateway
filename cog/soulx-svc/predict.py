"""Zero-shot singing voice conversion with SoulX-Singer-SVC.

The gateway sends one target clip plus a 5–30s clean reference clip. This Cog
separates the target, extracts F0 for both sides, runs the SVC model, then
optionally remixes the converted vocal with the original accompaniment.
"""

from __future__ import annotations

import gc
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path as FilePath

import librosa
import numpy as np
import soundfile as sf
import torch
from cog import BasePredictor, Input, Path

os.environ.setdefault("HF_HOME", "/src/hf")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# A build-time proxy must not survive into the Replicate runtime:
# host.docker.internal does not resolve there and every weight is already baked
# into the image.
for _proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_proxy_var, None)

SOULX_ROOT = FilePath(os.environ.get("SOULX_ROOT", "/src/SoulX-Singer"))
SVC_CHECKPOINT = SOULX_ROOT / "pretrained_models/SoulX-Singer/model-svc.pt"
SVC_CONFIG = SOULX_ROOT / "soulxsinger/config/soulxsinger.yaml"
PREPROCESS = SOULX_ROOT / "pretrained_models/SoulX-Singer-Preprocess"
SEPARATOR_CHECKPOINT = (
    PREPROCESS / "mel-band-roformer-karaoke/mel_band_roformer_karaoke_becruily.ckpt"
)
SEPARATOR_CONFIG = PREPROCESS / "mel-band-roformer-karaoke/config_karaoke_becruily.yaml"
DEREVERB_CHECKPOINT = (
    PREPROCESS / "dereverb_mel_band_roformer/dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt"
)
DEREVERB_CONFIG = PREPROCESS / "dereverb_mel_band_roformer/dereverb_mel_band_roformer_anvuew.yaml"
RMVPE_CHECKPOINT = PREPROCESS / "rmvpe/rmvpe.pt"

# The production image bakes these in (the cog.yaml download steps). A lean
# image can omit them: setup() fetches whatever is missing, which keeps the
# image small enough to build on a 48GB host at the cost of a slower first
# cold start.
_WEIGHT_URLS = {
    SVC_CHECKPOINT: "https://huggingface.co/Soul-AILab/SoulX-Singer/resolve/main/model-svc.pt",
    SEPARATOR_CHECKPOINT: (
        "https://huggingface.co/Soul-AILab/SoulX-Singer-Preprocess/resolve/main/"
        "mel-band-roformer-karaoke/mel_band_roformer_karaoke_becruily.ckpt"
    ),
    SEPARATOR_CONFIG: (
        "https://huggingface.co/Soul-AILab/SoulX-Singer-Preprocess/resolve/main/"
        "mel-band-roformer-karaoke/config_karaoke_becruily.yaml"
    ),
    RMVPE_CHECKPOINT: (
        "https://huggingface.co/Soul-AILab/SoulX-Singer-Preprocess/resolve/main/rmvpe/rmvpe.pt"
    ),
}

SAMPLE_RATE = 24000  # model grid (hop 480)
MIX_RATE = 44100  # separator grid
MAX_REFERENCE_SECONDS = 30
MAX_TARGET_SECONDS = 600
MIN_REFERENCE_SECONDS = 3.0
MIN_F0_COVERAGE = 0.05
MUTE_DB = -60.0

sys.path.insert(0, str(SOULX_ROOT))

from preprocess.tools.f0_extraction import F0Extractor  # noqa: E402
from preprocess.tools.vocal_separation.model import VocalSeparator  # noqa: E402
from soulxsinger.models.soulxsinger_svc import SoulXSingerSVC  # noqa: E402
from soulxsinger.utils.audio_utils import load_wav  # noqa: E402
from soulxsinger.utils.file_utils import load_config  # noqa: E402


def _ensure_file(path: FilePath, url: str) -> None:
    """Fetch a weight file only when the image does not already contain it."""
    if path.is_file() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    print(f"[svc] downloading {path.name} from {url}", flush=True)
    subprocess.run(
        [
            "curl",
            "-fL",
            "--retry",
            "10",
            "--retry-delay",
            "3",
            "--retry-all-errors",
            "-C",
            "-",
            "-o",
            str(partial),
            url,
        ],
        check=True,
        timeout=3600,
    )
    partial.replace(path)


def _decode(src: FilePath, dst: FilePath, max_seconds: int) -> None:
    """Normalise any input to 44.1k mono wav and cap its length."""
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(src),
                "-t",
                str(max_seconds),
                "-ac",
                "1",
                "-ar",
                str(MIX_RATE),
                str(dst),
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ValueError("INVALID_AUDIO") from exc


def _duration(path: FilePath) -> float:
    return float(sf.info(str(path)).duration)


def _coverage(f0: np.ndarray) -> float:
    return float(np.mean(f0 > 0)) if f0.size else 0.0


def _fold_octave(semitones: int) -> int:
    """Fold an octave shift to the nearest key-equivalent semitone count."""
    shift = abs(int(semitones)) % 12
    if shift > 6:
        shift -= 12
    return -shift if semitones < 0 else shift


def _pitch_shift(audio: np.ndarray, semitones: int) -> np.ndarray:
    if semitones == 0:
        return audio
    return librosa.effects.pitch_shift(audio, sr=SAMPLE_RATE, n_steps=semitones)


class Predictor(BasePredictor):
    def setup(self) -> None:
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.use_fp16 = self.device == "cuda"

        for path, url in _WEIGHT_URLS.items():
            _ensure_file(path, url)
        if not SVC_CONFIG.is_file():
            raise RuntimeError(f"model config missing: {SVC_CONFIG}")

        config = load_config(str(SVC_CONFIG))
        model = SoulXSingerSVC(config).to(self.device)
        checkpoint = torch.load(str(SVC_CHECKPOINT), weights_only=False, map_location="cpu")
        if "state_dict" not in checkpoint:
            raise RuntimeError("model-svc.pt has no state_dict")
        model.load_state_dict(checkpoint["state_dict"], strict=True)
        if self.use_fp16:
            model.half()
            # The mel frontend stays fp32: its log/clamp path is unstable in fp16.
            model.mel.float()
        model.eval().to(self.device)

        self.config = config
        self.model = model
        # Dereverb stays off to match upstream's SVC pipeline and save VRAM;
        # the paths are still required by the constructor.
        self.separator = VocalSeparator(
            sep_model_path=str(SEPARATOR_CHECKPOINT),
            sep_config_path=str(SEPARATOR_CONFIG),
            der_model_path=str(DEREVERB_CHECKPOINT),
            der_config_path=str(DEREVERB_CONFIG),
            use_der=False,
            device=self.device,
            verbose=False,
        )
        self.f0 = F0Extractor(
            model_path=str(RMVPE_CHECKPOINT),
            device=self.device,
            is_half=self.use_fp16,
            max_duration=float(MAX_TARGET_SECONDS),
            verbose=False,
        )
        print(f"[svc] ready device={self.device} fp16={self.use_fp16}", flush=True)

    def _prepare(
        self, audio: FilePath, out: FilePath, *, separate: bool
    ) -> tuple[np.ndarray, FilePath]:
        out.mkdir(parents=True, exist_ok=True)
        vocal_path = out / "vocal.wav"
        if separate:
            result = self.separator.process(str(audio), verbose=False)
            vocal = result.vocals_dereverbed.T
            accompaniment = result.accompaniment.T
            sr = int(result.sample_rate)
            sf.write(str(vocal_path), vocal, sr)
            sf.write(str(out / "acc.wav"), accompaniment, sr)
        else:
            data, sr = librosa.load(str(audio), sr=None, mono=True)
            sf.write(str(vocal_path), data, sr)
        f0 = self.f0.process(str(vocal_path), verbose=False)
        return np.asarray(f0, dtype=np.float32), vocal_path

    def predict(
        self,
        target_audio: Path = Input(description="Song clip to convert (up to 600s)."),
        reference_audio: Path = Input(
            description="Clean 5–30s solo singing used as the voice reference."
        ),
        pitch_shift: int = Input(
            default=0,
            ge=-24,
            le=24,
            description="Manual key shift in semitones; ignored when auto_shift is on.",
        ),
        auto_shift: bool = Input(
            default=True,
            description="Match the reference and target registers from their F0 medians.",
        ),
        n_steps: int = Input(default=32, ge=8, le=64, description="Flow-matching steps."),
        cfg_scale: float = Input(default=3.0, ge=1.0, le=8.0, description="Classifier-free guidance."),
        seed: int = Input(default=42, ge=0, le=4294967295, description="Sampling seed."),
        random_seed: bool = Input(default=False, description="Ignore seed and draw a new one."),
        instrumental_volume: float = Input(
            default=MUTE_DB,
            ge=MUTE_DB,
            le=12.0,
            description="Accompaniment gain in dB; -60 mutes it (vocals only).",
        ),
        reference_vocal_sep: bool = Input(
            default=False,
            description="Separate the reference too (only if it is not already dry vocals).",
        ),
        output_format: str = Input(default="mp3", choices=["mp3", "wav"]),
    ) -> Path:
        workdir = FilePath(tempfile.mkdtemp(prefix="soulx-svc-"))
        try:
            target = workdir / "target.wav"
            reference = workdir / "reference.wav"
            _decode(target_audio, target, MAX_TARGET_SECONDS)
            _decode(reference_audio, reference, MAX_REFERENCE_SECONDS)
            if _duration(reference) < MIN_REFERENCE_SECONDS:
                raise ValueError("REFERENCE_TOO_SHORT")

            reference_f0, reference_vocal = self._prepare(
                reference, workdir / "reference", separate=reference_vocal_sep
            )
            target_f0, target_vocal = self._prepare(target, workdir / "target", separate=True)
            if _coverage(reference_f0) < MIN_F0_COVERAGE:
                raise ValueError("REFERENCE_NO_VOCAL")
            if _coverage(target_f0) < MIN_F0_COVERAGE:
                raise ValueError("TARGET_NO_VOCAL")

            chosen_seed = random.randrange(0, 2**32) if random_seed else int(seed)
            torch.manual_seed(chosen_seed)
            np.random.seed(chosen_seed % (2**32))
            random.seed(chosen_seed)

            pt_wav = load_wav(str(reference_vocal), SAMPLE_RATE).to(self.device)
            gt_wav = load_wav(str(target_vocal), SAMPLE_RATE).to(self.device)
            pt_f0 = torch.from_numpy(reference_f0).unsqueeze(0).to(self.device)
            gt_f0 = torch.from_numpy(target_f0).unsqueeze(0).to(self.device)

            with torch.no_grad():
                generated, applied_shift = self.model.infer(
                    pt_wav=pt_wav,
                    gt_wav=gt_wav,
                    pt_f0=pt_f0,
                    gt_f0=gt_f0,
                    auto_shift=bool(auto_shift),
                    pitch_shift=int(pitch_shift),
                    n_steps=int(n_steps),
                    cfg=float(cfg_scale),
                    use_fp16=self.use_fp16,
                )
            vocals = generated.squeeze().float().cpu().numpy()

            accompaniment_path = workdir / "target" / "acc.wav"
            if instrumental_volume > MUTE_DB + 0.5 and accompaniment_path.exists():
                accompaniment, _ = librosa.load(
                    str(accompaniment_path), sr=SAMPLE_RATE, mono=True
                )
                accompaniment = _pitch_shift(
                    accompaniment, _fold_octave(int(applied_shift))
                )
                accompaniment = accompaniment * (10.0 ** (float(instrumental_volume) / 20.0))
                length = min(len(vocals), len(accompaniment))
                if length > 0:
                    mixed = vocals[:length] + accompaniment[:length]
                    peak = float(np.max(np.abs(mixed))) if mixed.size else 1.0
                    if peak > 1.0:
                        mixed = mixed / peak
                    vocals = mixed

            wav_path = workdir / "output.wav"
            sf.write(str(wav_path), vocals, SAMPLE_RATE)
            if output_format == "wav":
                return Path(str(wav_path))

            mp3_path = workdir / "output.mp3"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(wav_path),
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "192k",
                    str(mp3_path),
                ],
                check=True,
                capture_output=True,
            )
            return Path(str(mp3_path))
        finally:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
