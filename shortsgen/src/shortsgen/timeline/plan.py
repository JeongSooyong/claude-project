"""Pure timeline planning: script + measured TTS sample counts -> Timeline."""

from __future__ import annotations

import math

from .. import TEXT_FONT
from ..audio import output_len
from ..config import FPS, SAMPLE_RATE, SCENE_TAIL_MS, SENTENCE_GAP_MS, TTS_SAMPLE_RATE
from ..models import Cue, SceneTiming, Script, Timeline
from ..render import fonts, layout
from ..render.text_layout import wrap

GAP = SAMPLE_RATE * SENTENCE_GAP_MS // 1000
TAIL = SAMPLE_RATE * SCENE_TAIL_MS // 1000
SPF = SAMPLE_RATE // FPS  # samples per frame


def split_cues(text: str) -> list[list[str]]:
    """Split a sentence into display cues of <= SUB_MAX_LINES lines (each <= 16 chars and <= 960 px)."""
    font = fonts.load(TEXT_FONT, layout.SUB_FONT_SIZE)
    lines = [l for l in wrap(text.strip(), font, layout.SUB_MAX_WIDTH, layout.SUB_MAX_CHARS) if l]
    return [lines[i : i + layout.SUB_MAX_LINES] for i in range(0, len(lines), layout.SUB_MAX_LINES)]


def build(script: Script, sentence_samples: dict[str, list[int]], tts_rate: int = TTS_SAMPLE_RATE) -> Timeline:
    """sentence_samples: per scene id, the TTS sample count of each narration sentence (at tts_rate)."""
    scenes: list[SceneTiming] = []
    frame = 0
    for scene in script.scenes:
        lengths = [output_len(n, tts_rate) for n in sentence_samples[scene.id]]
        if len(lengths) != len(scene.narration):
            raise ValueError(f"scene {scene.id}: audio for {len(lengths)} sentences, narration has {len(scene.narration)}")
        offsets, pos = [], 0
        for i, n in enumerate(lengths):
            if i:
                pos += GAP
            offsets.append(pos)
            pos += n
        frames = math.ceil((pos + TAIL) / SPF)

        cues: list[Cue] = []
        for i, sent in enumerate(scene.narration):
            s_start = offsets[i]
            s_end = offsets[i + 1] if i + 1 < len(offsets) else frames * SPF
            chunks = split_cues(sent.text)
            weights = [max(1, sum(len(l) for l in c)) for c in chunks]
            total_w = sum(weights)
            # allocate the spoken part proportionally; the last cue holds until the next sentence starts
            speak = lengths[i]
            acc = 0
            for j, (chunk, w) in enumerate(zip(chunks, weights)):
                c_start = s_start + speak * acc // total_w
                acc += w
                c_end = s_start + speak * acc // total_w if j + 1 < len(chunks) else s_end
                cues.append(
                    Cue(
                        start_frame=frame + c_start // SPF,
                        end_frame=frame + max(c_start // SPF + 1, c_end // SPF),
                        lines=chunk,
                        highlight_line=sent.highlight_line,
                    )
                )
        scenes.append(
            SceneTiming(
                scene_id=scene.id,
                start_frame=frame,
                frames=frames,
                sentence_offsets_samples=offsets,
                sentence_lengths_samples=lengths,
                cues=cues,
            )
        )
        frame += frames
    return Timeline(fps=FPS, sample_rate=SAMPLE_RATE, scenes=scenes)
