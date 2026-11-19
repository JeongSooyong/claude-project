"""PCM/WAV helpers and the single master audio track."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from .config import SAMPLE_RATE, TTS_SAMPLE_RATE
from .models import Timeline


def pcm_bytes_to_array(data: bytes) -> np.ndarray:
    if len(data) % 2:
        data = data[:-1]
    return np.frombuffer(data, dtype="<i2").copy()


def write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.astype("<i2").tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        rate = w.getframerate()
        data = w.readframes(w.getnframes())
    return pcm_bytes_to_array(data), rate


def to_output_rate(samples: np.ndarray, rate: int = TTS_SAMPLE_RATE) -> np.ndarray:
    """Resample to SAMPLE_RATE (48 kHz). Output length is exactly len * 48000 / rate."""
    if rate == SAMPLE_RATE:
        return samples
    n_out = len(samples) * SAMPLE_RATE // rate
    if len(samples) == 0:
        return np.zeros(0, dtype=np.int16)
    x_old = np.arange(len(samples))
    x_new = np.arange(n_out) * (rate / SAMPLE_RATE)
    return np.round(np.interp(x_new, x_old, samples.astype(np.float64))).astype(np.int16)


def output_len(n_tts_samples: int, rate: int = TTS_SAMPLE_RATE) -> int:
    return n_tts_samples * SAMPLE_RATE // rate


def split_sentences(scene_audio: np.ndarray, sentence_samples: list[int]) -> list[np.ndarray]:
    out, pos = [], 0
    for n in sentence_samples:
        out.append(scene_audio[pos : pos + n])
        pos += n
    return out


def build_master(timeline: Timeline, scene_sentences: dict[str, list[np.ndarray]], rate: int = TTS_SAMPLE_RATE) -> np.ndarray:
    """One track for the whole video. Each scene's audio sits exactly in its frame-rounded span."""
    spf = SAMPLE_RATE // timeline.fps  # samples per frame (1600)
    master = np.zeros(timeline.total_frames * spf, dtype=np.int16)
    for st in timeline.scenes:
        base = st.start_frame * spf
        for sent, off in zip(scene_sentences[st.scene_id], st.sentence_offsets_samples):
            s48 = to_output_rate(sent, rate)
            start = base + off
            end = min(start + len(s48), base + st.frames * spf)
            master[start:end] = s48[: end - start]
    return master
