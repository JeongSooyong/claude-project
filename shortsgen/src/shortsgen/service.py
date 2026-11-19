"""Project lifecycle + state machine (plan §3). The web layer is a thin wrapper around this."""

from __future__ import annotations

import io
import threading
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from PIL import Image

from . import audio
from .config import MAX_SECONDS, MIN_SECONDS, Settings
from .cost import CostGuard
from .hashing import content_hash, file_sha256, image_source_hash, scene_hash, tts_source_hash
from .ingest import markdown as md_ingest
from .ingest import url as url_ingest
from .models import AssetRecord, CodeRef, Project, ProjectState, Sentence, Timeline
from .providers.base import Providers
from .providers.retry import with_retries
from .publish import metadata
from .publish.youtube import YouTubeUploader, video_url
from .render import compose
from .script.generate import generate_script
from .script.validate import validate
from .storage import Storage
from .timeline import plan

S = ProjectState
EDITABLE_STATES = {S.scripted, S.reviewing, S.approved, S.render_failed, S.rendered, S.upload_failed}


class Conflict(RuntimeError):
    """Maps to HTTP 409."""


class Service:
    def __init__(self, storage: Storage, providers: Providers, settings: Settings, uploader: YouTubeUploader | None = None):
        self.storage = storage
        self.providers = providers
        self.settings = settings
        self.uploader = uploader or YouTubeUploader(settings.secrets_dir)
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    # ---------- helpers ----------
    @contextmanager
    def _lock(self, pid: str):
        with self._guard:
            lock = self._locks.setdefault(pid, threading.Lock())
        with lock:
            yield

    def dir(self, pid: str) -> Path:
        return self.storage.project_dir(pid)

    def get(self, pid: str) -> Project:
        if not self.storage.exists(pid):
            raise KeyError(pid)
        return self.storage.load(pid)

    def cost(self, pid: str) -> CostGuard:
        return CostGuard(self.storage, pid, self.settings)

    def _tts_hash(self, scene) -> str:
        return tts_source_hash(scene, self.settings.tts_voice, self.settings.tts_model)

    def _fresh(self, p: Project, key: str, expected: str) -> bool:
        rec = p.assets.get(key)
        return rec is not None and rec.source_hash == expected and (self.dir(p.id) / rec.path).exists()

    def scene_status(self, p: Project) -> dict[str, dict]:
        out = {}
        for sc in p.script.scenes if p.script else []:
            out[sc.id] = {
                "image_fresh": self._fresh(p, f"image:{sc.id}", image_source_hash(sc)),
                "tts_fresh": self._fresh(p, f"tts:{sc.id}", self._tts_hash(sc)),
            }
        return out

    def _all_fresh(self, p: Project) -> bool:
        st = self.scene_status(p)
        return bool(st) and all(v["image_fresh"] and v["tts_fresh"] for v in st.values())

    def _require_script(self, p: Project):
        if p.script is None:
            raise Conflict("대본이 아직 없습니다.")

    def _reset_review(self, p: Project) -> None:
        if p.state in (S.rendering, S.uploading):
            raise Conflict("렌더링/업로드 중에는 수정할 수 없습니다.")
        p.state = S.reviewing
        p.approved_hash = None
        p.upload_uri = None  # an old resumable session carries old metadata/size
        p.error = None

    # ---------- create / script ----------
    def create_from_markdown(self, text: str, name: str = "document.md") -> Project:
        return self.storage.create(md_ingest.parse(text, source=name))

    def create_from_url(self, url: str) -> Project:
        return self.storage.create(url_ingest.ingest(url))

    def generate_script(self, pid: str) -> tuple[Project, list[str]]:
        with self._lock(pid):
            p = self.get(pid)
            if p.state in (S.rendering, S.uploading):
                raise Conflict("렌더링/업로드 중입니다.")
            script, issues = generate_script(p.doc, self.providers.script, self.cost(pid))
            p.script = script
            p.state = S.reviewing
            p.approved_hash = None
            self.storage.save(p)
            return p, issues

    def issues(self, p: Project) -> list[str]:
        return validate(p.script, p.doc) if p.script else []

    # ---------- edits ----------
    def update_scene(self, pid: str, sid: str, fields: dict) -> Project:
        with self._lock(pid):
            p = self.get(pid)
            self._require_script(p)
            scene = p.script.scene(sid)
            if scene is None:
                raise KeyError(sid)
            upd = {}
            if "narration" in fields:
                upd["narration"] = [Sentence.model_validate(s) for s in fields["narration"]]
            if "on_screen_text" in fields:
                upd["on_screen_text"] = str(fields["on_screen_text"])
            if "image_prompt" in fields:
                upd["image_prompt"] = str(fields["image_prompt"])
            if "code" in fields:
                upd["code"] = CodeRef.model_validate(fields["code"]) if fields["code"] else None
            new = scene.model_copy(update=upd)
            if scene_hash(new) == scene_hash(scene):
                return p
            p.script.scenes = [new if s.id == sid else s for s in p.script.scenes]
            self._reset_review(p)
            self.storage.save(p)
            return p

    def update_metadata(self, pid: str, title: str, description: str, hashtags: list[str]) -> Project:
        with self._lock(pid):
            p = self.get(pid)
            self._require_script(p)
            new = p.script.model_copy(update={"title": title, "description": description, "hashtags": list(hashtags)})
            if new != p.script:
                p.script = new
                self._reset_review(p)
                self.storage.save(p)
            return p

    # ---------- assets ----------
    def generate_image(self, pid: str, sid: str) -> Project:
        with self._lock(pid):
            p = self.get(pid)
            self._require_script(p)
            if p.state in (S.rendering, S.uploading):
                raise Conflict("렌더링/업로드 중입니다.")
            scene = p.script.scene(sid)
            if scene is None:
                raise KeyError(sid)
            guard = self.cost(pid)
            guard.check(self.providers.image.estimate_usd(scene.image_prompt))
            data, usage = with_retries(lambda: self.providers.image.generate(scene.image_prompt))
            guard.record(usage)
            rel = f"assets/img_{sid}.png"
            path = self.dir(pid) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(io.BytesIO(data)) as im:
                im.convert("RGB").save(path, "PNG")
            p.assets[f"image:{sid}"] = AssetRecord(path=rel, source_hash=image_source_hash(scene))
            self._reset_review(p)
            self.storage.save(p)
            return p

    def generate_missing_images(self, pid: str) -> Project:
        p = self.get(pid)
        self._require_script(p)
        for sid, st in self.scene_status(p).items():
            if not st["image_fresh"]:
                p = self.generate_image(pid, sid)
        return self.get(pid)

    def generate_tts(self, pid: str) -> tuple[Project, Timeline]:
        """TTS for stale scenes only; rebuild the timeline; return predicted duration via timeline."""
        with self._lock(pid):
            p = self.get(pid)
            self._require_script(p)
            if p.state in (S.rendering, S.uploading):
                raise Conflict("렌더링/업로드 중입니다.")
            guard = self.cost(pid)
            changed = False
            for scene in p.script.scenes:
                expected = self._tts_hash(scene)
                if self._fresh(p, f"tts:{scene.id}", expected):
                    continue
                guard.check(sum(self.providers.tts.estimate_usd(s.text) for s in scene.narration))
                parts = []
                for sent in scene.narration:
                    pcm, usage = with_retries(lambda t=sent.text: self.providers.tts.synthesize(t))
                    guard.record(usage)
                    parts.append(pcm)
                rel = f"assets/tts_{scene.id}.wav"
                audio.write_wav(self.dir(pid) / rel, np.concatenate(parts) if parts else np.zeros(0, np.int16), self.providers.tts.sample_rate)
                p.assets[f"tts:{scene.id}"] = AssetRecord(
                    path=rel, source_hash=expected, samples=sum(len(x) for x in parts), sentence_samples=[len(x) for x in parts]
                )
                changed = True
            if changed:
                self._reset_review(p)
            tl = self._timeline(p)
            self.storage.save_timeline(pid, tl)
            self.storage.save(p)
            return p, tl

    def _timeline(self, p: Project) -> Timeline:
        samples = {}
        for scene in p.script.scenes:
            rec = p.assets.get(f"tts:{scene.id}")
            if rec is None or rec.sentence_samples is None:
                raise Conflict(f"[{scene.id}] 음성이 아직 없습니다.")
            samples[scene.id] = rec.sentence_samples
        return plan.build(p.script, samples, self.providers.tts.sample_rate)

    def predicted_seconds(self, p: Project) -> float | None:
        if p.script is None or not all(v["tts_fresh"] for v in self.scene_status(p).values()):
            return None
        return self._timeline(p).total_seconds

    def _scene_sentences(self, p: Project) -> dict[str, list[np.ndarray]]:
        out = {}
        for scene in p.script.scenes:
            rec = p.assets[f"tts:{scene.id}"]
            arr, _ = audio.read_wav(self.dir(p.id) / rec.path)
            out[scene.id] = audio.split_sentences(arr, rec.sentence_samples)
        return out

    # ---------- approve / render / upload ----------
    def approve(self, pid: str) -> Project:
        with self._lock(pid):
            p = self.get(pid)
            self._require_script(p)
            if p.state not in (S.scripted, S.reviewing):
                raise Conflict(f"현재 상태({p.state.value})에서는 승인할 수 없습니다.")
            issues = self.issues(p)
            if issues:
                raise Conflict("검증 오류를 먼저 고쳐 주세요: " + " / ".join(issues))
            if not self._all_fresh(p):
                raise Conflict("이미지와 음성을 최신 대본으로 다시 생성해 주세요.")
            secs = self._timeline(p).total_seconds
            if not MIN_SECONDS <= secs <= MAX_SECONDS:
                raise Conflict(f"예상 길이 {secs:.1f}초가 {MIN_SECONDS:.0f}~{MAX_SECONDS:.0f}초 범위를 벗어났습니다. 내레이션을 조정해 주세요.")
            p.approved_hash = content_hash(p, self.dir(pid))
            p.state = S.approved
            p.error = None
            self.storage.save(p)
            return p

    def _check_approved_hash(self, p: Project) -> None:
        if p.approved_hash is None or content_hash(p, self.dir(p.id)) != p.approved_hash:
            raise Conflict("승인 이후 내용이 바뀌었습니다. 다시 승인해 주세요.")

    def start_render(self, pid: str) -> Project:
        with self._lock(pid):
            p = self.get(pid)
            if p.state not in (S.approved, S.render_failed):
                raise Conflict(f"렌더링은 승인 후에만 가능합니다 (현재 {p.state.value}).")
            self._check_approved_hash(p)
            p.state = S.rendering
            p.error = None
            self.storage.save(p)
            return p

    def run_render(self, pid: str) -> Project:
        p = self.get(pid)
        try:
            tl = self._timeline(p)
            self.storage.save_timeline(pid, tl)
            out = self.dir(pid) / "out" / "video.mp4"
            bgs = {s.id: self.dir(pid) / p.assets[f"image:{s.id}"].path for s in p.script.scenes}
            compose.render_video(self.dir(pid), p.script, p.doc, tl, bgs, self._scene_sentences(p), out)
            metadata.write(p.script, self.dir(pid) / "out")
            p = self.get(pid)
            p.rendered_hash = f"{p.approved_hash}:{file_sha256(out)}"
            p.upload_uri = None  # new file -> new upload session
            p.state = S.rendered
        except Exception as e:  # noqa: BLE001 - surfaced to the UI
            p = self.get(pid)
            p.state = S.render_failed
            p.error = getattr(e, "stderr", None) or str(e)
        self.storage.save(p)
        return p

    def render(self, pid: str) -> Project:
        self.start_render(pid)
        return self.run_render(pid)

    def start_upload(self, pid: str) -> Project:
        with self._lock(pid):
            p = self.get(pid)
            if p.video_id:
                raise Conflict(f"이미 업로드되었습니다: {video_url(p.video_id)}")
            if p.state not in (S.rendered, S.upload_failed):
                raise Conflict(f"업로드는 렌더링 후에만 가능합니다 (현재 {p.state.value}).")
            self._check_approved_hash(p)
            out = self.dir(pid) / "out" / "video.mp4"
            if not out.exists() or p.rendered_hash != f"{p.approved_hash}:{file_sha256(out)}":
                raise Conflict("렌더링된 영상 파일이 승인된 내용과 다릅니다. 다시 렌더링해 주세요.")
            p.state = S.uploading
            p.error = None
            self.storage.save(p)
            return p

    def run_upload(self, pid: str) -> Project:
        p = self.get(pid)

        def remember(uri: str):
            q = self.get(pid)
            if q.upload_uri != uri:
                q.upload_uri = uri
                self.storage.save(q)

        try:
            vid = self.uploader.upload(self.dir(pid) / "out" / "video.mp4", p.script, resume_uri=p.upload_uri, on_uri=remember)
            p = self.get(pid)
            p.video_id = vid
            p.state = S.uploaded
        except Exception as e:  # noqa: BLE001
            p = self.get(pid)
            p.state = S.upload_failed
            p.error = str(e)
            status = getattr(getattr(e, "resp", None), "status", None) or getattr(e, "status_code", None)
            if status in (404, 410):  # resumable session expired/unknown: start fresh next time
                p.upload_uri = None
        self.storage.save(p)
        return p

    def upload(self, pid: str) -> Project:
        self.start_upload(pid)
        return self.run_upload(pid)

    # ---------- preview ----------
    def preview_path(self, p: Project, sid: str) -> Path:
        scene = p.script.scene(sid)
        key = scene_hash(scene)[:16]
        d = self.dir(p.id)
        a = file_sha256(d / p.assets[f"tts:{sid}"].path)[:8] + file_sha256(d / p.assets[f"image:{sid}"].path)[:8]
        return self.dir(p.id) / "preview" / sid / f"{key}_{a}.mp4"

    def check_preview(self, p: Project, sid: str) -> None:
        """Raise Conflict/KeyError if a preview of this scene cannot be built now."""
        self._require_script(p)
        if p.state == S.rendering:
            raise Conflict("전체 렌더링 중에는 미리보기를 만들 수 없습니다.")
        st = self.scene_status(p).get(sid)
        if st is None:
            raise KeyError(sid)
        if not (st["image_fresh"] and st["tts_fresh"]):
            raise Conflict("이 장면의 이미지/음성이 최신이 아닙니다. 먼저 다시 생성해 주세요.")

    def make_preview(self, pid: str, sid: str) -> Path:
        with self._lock(pid):
            p = self.get(pid)
            self.check_preview(p, sid)
            scene = p.script.scene(sid)
            out = self.preview_path(p, sid)
            if out.exists():
                return out
            tl = self._timeline(p)
            sents = self._scene_sentences(p)[sid]
            compose.render_scene_preview(self.dir(pid), scene, p.doc, tl, self.dir(pid) / p.assets[f"image:{sid}"].path, sents, out)
            return out

    def cached_preview(self, pid: str, sid: str) -> Path | None:
        p = self.get(pid)
        try:
            path = self.preview_path(p, sid)
        except (KeyError, AttributeError):
            return None
        return path if path.exists() else None
