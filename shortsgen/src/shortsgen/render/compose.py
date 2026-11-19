"""Compose the final video.

Per scene: a VIDEO-ONLY clip (zoompan background + static foreground + highlight bands
+ subtitle cards, each enabled by frame number). Clips are concatenated, then ONE master
audio track is muxed once (no per-scene AAC priming drift).

ffmpeg runs with cwd=<work dir> and relative paths, so non-ASCII project paths are safe.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

from .. import audio
from ..config import FPS, SAMPLE_RATE
from ..models import Scene, SceneTiming, Script, TechDoc, Timeline
from . import code_card, ffmpeg, layers, layout


def _card_for(scene: Scene, doc: TechDoc) -> code_card.CodeCard | None:
    if scene.code is None:
        return None
    block = doc.block(scene.code.block_id)
    if block is None:
        raise ValueError(f"scene {scene.id}: unknown code block {scene.code.block_id}")
    lines = block.line_range(scene.code.start_line, scene.code.end_line)
    return code_card.render(lines, block.language)


def prepare_layers(work: Path, scene: Scene, doc: TechDoc, bg_image: Path, timing: SceneTiming) -> layers.SceneLayers:
    d = work / f"scene_{scene.id}"
    d.mkdir(parents=True, exist_ok=True)
    with Image.open(bg_image) as im:
        layers.cover_crop(im, layout.WIDTH * 2, layout.HEIGHT * 2).save(d / "bg.png")
    card = _card_for(scene, doc)
    layers.build_foreground(scene.on_screen_text, card).save(d / "fg.png")
    highlights: dict[int, Path] = {}
    if card is not None and scene.code is not None:
        for line in sorted({c.highlight_line for c in timing.cues if c.highlight_line is not None}):
            row = line - scene.code.start_line
            if not 0 <= row < len(card.line_tops):
                raise ValueError(f"scene {scene.id}: highlight line {line} outside code range")
            p = d / f"hl_{line}.png"
            layers.build_highlight(card, row).save(p)
            highlights[line] = p
    subs: list[Path] = []
    for i, cue in enumerate(timing.cues):
        p = d / f"sub_{i:03d}.png"
        layers.build_subtitle(cue.lines).save(p)
        subs.append(p)
    return layers.SceneLayers(bg=d / "bg.png", fg=d / "fg.png", highlights=highlights, subtitles=subs)


def _rel(p: Path, base: Path) -> str:
    return p.relative_to(base).as_posix()


def render_scene_clip(work: Path, lay: layers.SceneLayers, timing: SceneTiming, out: Path) -> None:
    n = timing.frames
    s0 = timing.start_frame
    inputs = ["-i", _rel(lay.bg, work), "-i", _rel(lay.fg, work)]
    graph = [
        f"[0:v]zoompan=z='min(1+0.0006*on,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={n}:s={layout.WIDTH}x{layout.HEIGHT}:fps={FPS},format=rgba[v0]",
        "[v0][1:v]overlay=0:0[v1]",
    ]
    idx, cur = 2, "v1"

    def add(path: Path, enable: str):
        nonlocal idx, cur
        inputs.extend(["-i", _rel(path, work)])
        nxt = f"v{idx}"
        graph.append(f"[{cur}][{idx}:v]overlay=0:0:enable='{enable}'[{nxt}]")
        idx += 1
        cur = nxt

    for line, path in lay.highlights.items():
        ranges = [
            f"between(n,{c.start_frame - s0},{c.end_frame - s0 - 1})"
            for c in timing.cues
            if c.highlight_line == line
        ]
        add(path, "+".join(ranges))
    for cue, path in zip(timing.cues, lay.subtitles):
        add(path, f"between(n,{cue.start_frame - s0},{cue.end_frame - s0 - 1})")
    graph.append(f"[{cur}]format=yuv420p[vout]")

    ffmpeg.run(
        [
            *inputs,
            "-filter_complex", ";".join(graph),
            "-map", "[vout]",
            "-frames:v", str(n),
            "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-an",
            _rel(out, work),
        ],
        cwd=work,
    )


def mux(work: Path, video: Path, wav: Path, out: Path) -> None:
    """Writes to a temp file and renames, so a crash never leaves a partial `out` (e.g. a cached preview)."""
    tmp = out.with_name(out.stem + ".partial.mp4")
    ffmpeg.run(
        [
            "-i", _rel(video, work), "-i", _rel(wav, work),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", str(SAMPLE_RATE),
            "-shortest", "-movflags", "+faststart",
            _rel(tmp, work),
        ],
        cwd=work,
    )
    os.replace(tmp, out)


def render_video(
    project_dir: Path,
    script: Script,
    doc: TechDoc,
    timeline: Timeline,
    bg_images: dict[str, Path],
    scene_sentences: dict[str, list[np.ndarray]],
    out: Path,
) -> Path:
    """Render the full video. scene_sentences: per scene, TTS-rate PCM arrays per sentence."""
    work = project_dir
    rdir = work / "render"
    rdir.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    for scene, timing in zip(script.scenes, timeline.scenes):
        lay = prepare_layers(rdir, scene, doc, bg_images[scene.id], timing)
        clip = rdir / f"clip_{scene.id}.mp4"
        render_scene_clip(work, lay, timing, clip)
        clips.append(clip)
    concat_list = rdir / "concat.txt"
    concat_list.write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")
    video = rdir / "video_noaudio.mp4"
    ffmpeg.run(["-f", "concat", "-safe", "0", "-i", _rel(concat_list, work), "-c", "copy", _rel(video, work)], cwd=work)
    master = audio.build_master(timeline, scene_sentences)
    wav = rdir / "master.wav"
    audio.write_wav(wav, master, SAMPLE_RATE)
    out.parent.mkdir(parents=True, exist_ok=True)
    mux(work, video, wav, out)
    return out


def render_scene_preview(
    project_dir: Path,
    scene: Scene,
    doc: TechDoc,
    timeline: Timeline,
    bg_image: Path,
    sentences: list[np.ndarray],
    out: Path,
) -> Path:
    """Preview one scene through the same path (layers + clip + muxed audio)."""
    timing = next(t for t in timeline.scenes if t.scene_id == scene.id)
    # Re-base timing so the preview starts at frame 0.
    shift = timing.start_frame
    local = timing.model_copy(
        update={
            "start_frame": 0,
            "cues": [c.model_copy(update={"start_frame": c.start_frame - shift, "end_frame": c.end_frame - shift}) for c in timing.cues],
        }
    )
    work = project_dir
    pdir = work / "preview" / scene.id
    pdir.mkdir(parents=True, exist_ok=True)
    lay = prepare_layers(pdir, scene, doc, bg_image, local)
    clip = pdir / "clip.mp4"
    render_scene_clip(work, lay, local, clip)
    one = Timeline(fps=timeline.fps, sample_rate=timeline.sample_rate, scenes=[local])
    wav = pdir / "audio.wav"
    audio.write_wav(wav, audio.build_master(one, {scene.id: sentences}), SAMPLE_RATE)
    out.parent.mkdir(parents=True, exist_ok=True)
    mux(work, clip, wav, out)
    return out
