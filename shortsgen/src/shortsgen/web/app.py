"""Local web UI + JSON API. Binds to 127.0.0.1 only."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import MAX_SECONDS, MIN_SECONDS, Settings
from ..cost import CostCeilingError
from ..ingest import IngestError
from ..providers.base import Providers
from ..providers.retry import ProviderError
from ..publish.youtube import AuthSetupError, video_url
from ..render.code_card import CodeOverflowError
from ..service import Conflict, Service
from ..storage import Storage

HOST = "127.0.0.1"
PORT = 8765
STATIC = Path(__file__).parent / "static"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "testserver"}  # "testserver" = FastAPI TestClient
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "x-shortsgen"


def default_providers(settings: Settings) -> Providers:
    if os.getenv("SHORTSGEN_FAKE") == "1":
        from ..providers.fake import FakeImageProvider, FakeScriptProvider, FakeTTSProvider

        return Providers(FakeScriptProvider(), FakeImageProvider(), FakeTTSProvider())
    from ..providers.anthropic_script import AnthropicScriptProvider
    from ..providers.openai_image import OpenAIImageProvider
    from ..providers.openai_tts import OpenAITTSProvider

    return Providers(AnthropicScriptProvider(settings), OpenAIImageProvider(settings), OpenAITTSProvider(settings))


class MetadataIn(BaseModel):
    title: str
    description: str
    hashtags: list[str]


class UrlIn(BaseModel):
    url: str


def create_app(service: Service | None = None) -> FastAPI:
    if service is None:
        settings = Settings()
        service = Service(Storage(settings.projects_dir), default_providers(settings), settings)
    svc = service
    app = FastAPI(title="shortsgen")
    app.state.service = svc

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # DNS rebinding: the browser sends the attacker's hostname, so only accept local names.
        host = request.headers.get("host", "").split(":")[0].lower()
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "허용되지 않은 Host입니다."}, status_code=403)
        # Cross-site form posts cannot set custom headers (and no CORS preflight is allowed).
        if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            return JSONResponse({"detail": f"{CSRF_HEADER} 헤더가 필요합니다."}, status_code=403)
        return await call_next(request)

    @app.exception_handler(Conflict)
    async def _conflict(_: Request, e: Conflict):
        return JSONResponse({"detail": str(e)}, status_code=409)

    @app.exception_handler(KeyError)
    async def _missing(_: Request, e: KeyError):
        return JSONResponse({"detail": f"찾을 수 없습니다: {e}"}, status_code=404)

    for exc, code in ((IngestError, 400), (CodeOverflowError, 400), (CostCeilingError, 402), (ProviderError, 502), (AuthSetupError, 400)):
        app.add_exception_handler(exc, lambda _r, e, code=code: JSONResponse({"detail": str(e)}, status_code=code))

    def view(pid: str) -> dict:
        p = svc.get(pid)
        status = svc.scene_status(p)
        try:
            secs = svc.predicted_seconds(p)
        except Conflict:
            secs = None
        guard = svc.cost(pid)
        return {
            "project": p.model_dump(mode="json"),
            "issues": svc.issues(p),
            "scene_status": status,
            "predicted_seconds": secs,
            "duration_range": [MIN_SECONDS, MAX_SECONDS],
            "cost_krw": round(guard.spent_krw()),
            "cost_ceiling_krw": svc.settings.cost_ceiling_krw,
            "video_url": video_url(p.video_id) if p.video_id else None,
            "has_video": (svc.dir(pid) / "out" / "video.mp4").exists(),
            "previews": {sid: svc.cached_preview(pid, sid) is not None for sid in status},
        }

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/projects")
    def list_projects():
        root = svc.storage.root
        items = []
        for d in sorted(root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True) if root.exists() else []:
            if svc.storage.exists(d.name):  # skips hand-made folders with non-id names
                p = svc.get(d.name)
                items.append({"id": p.id, "title": (p.script.title if p.script else p.doc.title) or p.doc.source, "state": p.state.value})
        return items

    @app.post("/api/projects")
    async def create(url: str | None = Form(None), file: UploadFile | None = File(None), generate: bool = Form(True)):
        if file is not None and file.filename:
            text = (await file.read()).decode("utf-8-sig")
            p = svc.create_from_markdown(text, file.filename)
        elif url:
            p = svc.create_from_url(url.strip())
        else:
            raise HTTPException(400, "URL 또는 Markdown 파일을 입력해 주세요.")
        if generate:
            svc.generate_script(p.id)
        return view(p.id)

    @app.get("/api/projects/{pid}")
    def get_project(pid: str):
        return view(pid)

    @app.post("/api/projects/{pid}/script")
    def regenerate_script(pid: str):
        svc.generate_script(pid)
        return view(pid)

    @app.put("/api/projects/{pid}/scenes/{sid}")
    def put_scene(pid: str, sid: str, body: dict):
        svc.update_scene(pid, sid, body)
        return view(pid)

    @app.put("/api/projects/{pid}/metadata")
    def put_metadata(pid: str, body: MetadataIn):
        svc.update_metadata(pid, body.title, body.description, body.hashtags)
        return view(pid)

    @app.post("/api/projects/{pid}/scenes/{sid}/image")
    def regen_image(pid: str, sid: str):
        svc.generate_image(pid, sid)
        return view(pid)

    @app.post("/api/projects/{pid}/images")
    def missing_images(pid: str):
        svc.generate_missing_images(pid)
        return view(pid)

    @app.post("/api/projects/{pid}/tts")
    def tts(pid: str):
        svc.generate_tts(pid)
        return view(pid)

    @app.post("/api/projects/{pid}/scenes/{sid}/preview")
    def preview(pid: str, sid: str, background: BackgroundTasks):
        if svc.cached_preview(pid, sid) is None:
            # Validate synchronously (409 on stale assets / during render), build in background.
            svc.check_preview(svc.get(pid), sid)
            background.add_task(svc.make_preview, pid, sid)
            return {"status": "building"}
        return {"status": "ready"}

    @app.get("/api/projects/{pid}/scenes/{sid}/preview.mp4")
    def preview_file(pid: str, sid: str):
        path = svc.cached_preview(pid, sid)
        if path is None:
            raise HTTPException(404, "미리보기가 아직 없습니다.")
        return FileResponse(path, media_type="video/mp4")

    @app.post("/api/projects/{pid}/approve")
    def approve(pid: str):
        svc.approve(pid)
        return view(pid)

    @app.post("/api/projects/{pid}/render")
    def render(pid: str, background: BackgroundTasks):
        svc.start_render(pid)
        background.add_task(svc.run_render, pid)
        return view(pid)

    @app.post("/api/projects/{pid}/upload")
    def upload(pid: str, background: BackgroundTasks):
        svc.start_upload(pid)
        background.add_task(svc.run_upload, pid)
        return view(pid)

    @app.get("/api/projects/{pid}/job")
    def job(pid: str):
        p = svc.get(pid)
        return {"state": p.state.value, "error": p.error, "video_url": video_url(p.video_id) if p.video_id else None}

    @app.get("/api/projects/{pid}/assets/{name}")
    def asset(pid: str, name: str):
        base = (svc.dir(pid) / "assets").resolve()
        path = (base / name).resolve()
        if base not in path.parents or not path.exists():
            raise HTTPException(404)
        return FileResponse(path)

    @app.get("/api/projects/{pid}/video.mp4")
    def video(pid: str):
        path = svc.dir(pid) / "out" / "video.mp4"
        if not path.exists():
            raise HTTPException(404)
        return FileResponse(path, media_type="video/mp4")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def main() -> None:
    import uvicorn

    print(f"shortsgen: http://{HOST}:{PORT}")
    uvicorn.run(create_app(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
