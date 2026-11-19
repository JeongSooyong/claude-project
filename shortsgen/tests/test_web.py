"""TestClient tests for the state machine (AC-4, AC-5). BackgroundTasks run synchronously in TestClient."""

import json

import pytest
from fastapi.testclient import TestClient

from shortsgen.config import Settings
from shortsgen.providers.base import Providers
from shortsgen.providers.fake import FakeImageProvider, FakeScriptProvider, FakeTTSProvider
from shortsgen.publish.youtube import YouTubeUploader
from shortsgen.service import Service
from shortsgen.storage import Storage
from shortsgen.web import app as webapp

MD = """# json 모듈

파이썬 표준 라이브러리 json으로 직렬화하는 방법.

```python
import json
data = {"name": "홍길동", "age": 30}
text = json.dumps(data, ensure_ascii=False)
print(text)
```
"""


class FakeYT:
    def __init__(self):
        self.count = 0

    def videos(self):
        return self

    def insert(self, part, body, media_body):
        self.count += 1
        yt = self

        class Req:
            resumable_uri = "https://upload.example/r/1"

            def next_chunk(self):
                return None, {"id": f"VID{yt.count}"}

        return Req()


class Creds:
    valid = True


def make_client(tmp_path, seconds_per_char=0.25):
    settings = Settings(projects_dir=tmp_path / "projects", cost_ceiling_krw=1000)
    yt = FakeYT()
    uploader = YouTubeUploader(tmp_path / "secrets", service_factory=lambda c: yt, credentials_loader=lambda p: Creds())
    svc = Service(
        Storage(settings.projects_dir),
        Providers(FakeScriptProvider(), FakeImageProvider(), FakeTTSProvider(seconds_per_char=seconds_per_char)),
        settings,
        uploader=uploader,
    )
    return TestClient(webapp.create_app(svc), headers={"X-Shortsgen": "1"}), svc, yt


def create(client):
    r = client.post("/api/projects", files={"file": ("json.md", MD.encode(), "text/markdown")})
    assert r.status_code == 200, r.text
    return r.json()


def ready(client, pid):
    assert client.post(f"/api/projects/{pid}/images").status_code == 200
    r = client.post(f"/api/projects/{pid}/tts")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def ctx(tmp_path):
    return make_client(tmp_path)


def test_index_and_create(ctx):
    client, svc, _ = ctx
    r = client.get("/")
    assert r.status_code == 200 and 'id="scenes"' in r.text
    v = create(client)
    assert v["project"]["state"] == "reviewing"
    assert v["issues"] == []
    assert len(v["project"]["script"]["scenes"]) == 3
    assert client.get("/api/projects").json()[0]["id"] == v["project"]["id"]


def test_approve_requires_fresh_assets_and_duration(ctx, tmp_path):
    client, svc, _ = ctx
    pid = create(client)["project"]["id"]
    r = client.post(f"/api/projects/{pid}/approve")
    assert r.status_code == 409  # no images / tts yet
    v = ready(client, pid)
    assert 30 <= v["predicted_seconds"] <= 59
    assert client.post(f"/api/projects/{pid}/approve").status_code == 200

    short_client, _, _ = make_client(tmp_path / "short", seconds_per_char=0.05)
    pid2 = create(short_client)["project"]["id"]
    ready(short_client, pid2)
    r = short_client.post(f"/api/projects/{pid2}/approve")
    assert r.status_code == 409 and "범위" in r.json()["detail"]


def test_render_before_approve_is_409(ctx):
    client, _, _ = ctx
    pid = create(client)["project"]["id"]
    ready(client, pid)
    assert client.post(f"/api/projects/{pid}/render").status_code == 409


def test_upload_before_render_is_409(ctx):
    client, _, _ = ctx
    pid = create(client)["project"]["id"]
    ready(client, pid)
    client.post(f"/api/projects/{pid}/approve")
    assert client.post(f"/api/projects/{pid}/upload").status_code == 409


def test_edit_after_approve_resets_and_marks_stale(ctx):
    client, _, _ = ctx
    v = create(client)
    pid = v["project"]["id"]
    ready(client, pid)
    client.post(f"/api/projects/{pid}/approve")
    s1 = v["project"]["script"]["scenes"][0]
    r = client.put(f"/api/projects/{pid}/scenes/s1", json={"narration": [{"text": "바뀐 첫 문장입니다."}] + s1["narration"][1:]})
    v = r.json()
    assert v["project"]["state"] == "reviewing"
    assert v["project"]["approved_hash"] is None
    assert v["scene_status"]["s1"] == {"image_fresh": True, "tts_fresh": False}
    assert v["predicted_seconds"] is None
    assert client.post(f"/api/projects/{pid}/approve").status_code == 409  # stale TTS
    r = client.put(f"/api/projects/{pid}/metadata", json={"title": "새 제목", "description": "d", "hashtags": ["#a"]})
    assert r.json()["project"]["script"]["title"] == "새 제목"


def test_render_on_hash_mismatch_is_409(ctx):
    client, svc, _ = ctx
    pid = create(client)["project"]["id"]
    ready(client, pid)
    client.post(f"/api/projects/{pid}/approve")
    img = svc.dir(pid) / "assets" / "img_s1.png"
    img.write_bytes(img.read_bytes() + b"tampered")
    r = client.post(f"/api/projects/{pid}/render")
    assert r.status_code == 409 and "승인" in r.json()["detail"]


def test_full_flow_render_upload_and_guards(ctx):
    client, svc, yt = ctx
    pid = create(client)["project"]["id"]
    ready(client, pid)
    assert client.post(f"/api/projects/{pid}/approve").status_code == 200
    r = client.post(f"/api/projects/{pid}/render")
    assert r.status_code == 200
    job = client.get(f"/api/projects/{pid}/job").json()
    assert job["state"] == "rendered", job
    assert client.get(f"/api/projects/{pid}/video.mp4").status_code == 200
    meta = json.loads((svc.dir(pid) / "out" / "metadata.json").read_text(encoding="utf-8"))
    assert meta["title"] and meta["description"] and meta["hashtags"]

    # modified mp4 -> upload refused
    out = svc.dir(pid) / "out" / "video.mp4"
    original = out.read_bytes()
    out.write_bytes(original + b"x")
    assert client.post(f"/api/projects/{pid}/upload").status_code == 409
    out.write_bytes(original)

    r = client.post(f"/api/projects/{pid}/upload")
    assert r.status_code == 200
    job = client.get(f"/api/projects/{pid}/job").json()
    assert job["state"] == "uploaded" and job["video_url"] == "https://youtu.be/VID1"
    assert client.get(f"/api/projects/{pid}").json()["video_url"] == "https://youtu.be/VID1"
    r = client.post(f"/api/projects/{pid}/upload")
    assert r.status_code == 409 and yt.count == 1


def test_preview_stale_409_then_cached(ctx):
    client, svc, _ = ctx
    pid = create(client)["project"]["id"]
    r = client.post(f"/api/projects/{pid}/scenes/s2/preview")
    assert r.status_code == 409
    ready(client, pid)
    assert client.get(f"/api/projects/{pid}/scenes/s2/preview.mp4").status_code == 404
    r = client.post(f"/api/projects/{pid}/scenes/s2/preview")
    assert r.json()["status"] == "building"
    assert client.get(f"/api/projects/{pid}/scenes/s2/preview.mp4").status_code == 200
    assert client.post(f"/api/projects/{pid}/scenes/s2/preview").json()["status"] == "ready"
    assert client.get(f"/api/projects/{pid}").json()["previews"]["s2"] is True


def test_preview_409_while_rendering(ctx):
    client, svc, _ = ctx
    pid = create(client)["project"]["id"]
    ready(client, pid)
    client.post(f"/api/projects/{pid}/approve")
    svc.start_render(pid)  # state=rendering, render not run
    assert client.post(f"/api/projects/{pid}/scenes/s1/preview").status_code == 409


def test_cost_ceiling_returns_402(tmp_path):
    client, svc, _ = make_client(tmp_path)
    pid = create(client)["project"]["id"]
    svc.providers.image.estimate_usd = lambda prompt: 10.0  # 14,000 KRW > ceiling
    r = client.post(f"/api/projects/{pid}/scenes/s1/image")
    assert r.status_code == 402


def test_project_id_path_traversal_is_404(ctx, tmp_path):
    client, svc, _ = ctx
    secret = svc.storage.root.parent / "secret" / "assets"
    secret.mkdir(parents=True)
    (secret / "x.txt").write_text("LEAK")
    for path in (
        "/api/projects/..%5Csecret/assets/x.txt",
        "/api/projects/..%2Fsecret/assets/x.txt",
        "/api/projects/..%5Csecret",
    ):
        r = client.get(path)
        assert r.status_code == 404, (path, r.status_code)
        assert "LEAK" not in r.text
    pid = create(client)["project"]["id"]
    assert client.get(f"/api/projects/{pid}/assets/..%5C..%5Csecret%5Cassets%5Cx.txt").status_code == 404


def test_foreign_host_and_missing_header_rejected(ctx):
    client, _, _ = ctx
    assert client.get("/", headers={"Host": "evil.example:8765"}).status_code == 403
    bare = TestClient(client.app)  # no X-Shortsgen header, like a cross-site form post
    r = bare.post("/api/projects", data={"url": "https://example.com"})
    assert r.status_code == 403
    assert bare.get("/").status_code == 200


def test_upload_uri_cleared_on_edit_and_rerender(ctx):
    client, svc, _ = ctx
    pid = create(client)["project"]["id"]
    ready(client, pid)
    p = svc.get(pid)
    p.upload_uri = "https://upload.example/stale"
    svc.storage.save(p)
    client.put(f"/api/projects/{pid}/metadata", json={"title": "새 제목", "description": "d", "hashtags": ["#a"]})
    assert svc.get(pid).upload_uri is None
    client.post(f"/api/projects/{pid}/approve")
    p = svc.get(pid)
    p.upload_uri = "https://upload.example/stale2"
    svc.storage.save(p)
    client.post(f"/api/projects/{pid}/render")
    assert svc.get(pid).state.value == "rendered"
    assert svc.get(pid).upload_uri is None


def test_expired_upload_session_is_cleared(ctx):
    client, svc, _ = ctx
    pid = create(client)["project"]["id"]
    ready(client, pid)
    client.post(f"/api/projects/{pid}/approve")
    client.post(f"/api/projects/{pid}/render")

    class Gone(Exception):
        status_code = 410

    def boom(*a, **k):
        raise Gone("session expired")

    p = svc.get(pid)
    p.upload_uri = "https://upload.example/dead"
    svc.storage.save(p)
    svc.uploader.upload = boom
    client.post(f"/api/projects/{pid}/upload")
    p = svc.get(pid)
    assert p.state.value == "upload_failed" and p.upload_uri is None


def test_server_binds_localhost_only(monkeypatch):
    seen = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, host, port: seen.update(host=host, port=port))
    monkeypatch.setattr(webapp, "create_app", lambda: object())
    webapp.main()
    assert seen["host"] == "127.0.0.1"
