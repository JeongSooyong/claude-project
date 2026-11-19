import json

import pytest

from shortsgen.models import Scene, Script, Sentence
from shortsgen.publish import metadata
from shortsgen.publish.youtube import SCOPES, YouTubeUploader, video_url

SCRIPT = Script(
    title="json 모듈 1분 정리",
    description="파이썬 json 모듈 핵심",
    hashtags=["#파이썬", "json"],
    scenes=[Scene(id="s1", narration=[Sentence(text="a")], image_prompt="x")],
)


class FakeRequest:
    def __init__(self, body):
        self.body = body
        self.resumable_uri = None
        self.calls = 0

    def next_chunk(self):
        self.calls += 1
        if self.calls == 1:
            self.uri_at_first_chunk = self.resumable_uri
        self.resumable_uri = "https://upload.example/resumable/abc"
        if self.calls < 2:
            return None, None
        return None, {"id": "VID123"}


class FakeYouTube:
    def __init__(self):
        self.inserted = None

    def videos(self):
        return self

    def insert(self, part, body, media_body):
        self.inserted = (part, body)
        self.request = FakeRequest(body)
        return self.request


class Creds:
    def __init__(self, valid=True, expired=False, refresh_token=None, refresh_error=None):
        self.valid, self.expired, self.refresh_token = valid, expired, refresh_token
        self.refresh_error = refresh_error

    def refresh(self, request):
        raise self.refresh_error

    def to_json(self):
        return json.dumps({"token": "new"})


def test_upload_body_private_and_metadata(tmp_path):
    yt = FakeYouTube()
    up = YouTubeUploader(tmp_path, service_factory=lambda c: yt, credentials_loader=lambda p: Creds())
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 100)
    uris = []
    vid = up.upload(video, SCRIPT, on_uri=uris.append)
    part, body = yt.inserted
    assert vid == "VID123" and part == "snippet,status"
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["selfDeclaredMadeForKids"] is False
    assert body["snippet"]["title"] == SCRIPT.title
    assert body["snippet"]["description"].startswith(SCRIPT.description)
    assert "#파이썬 #json" in body["snippet"]["description"]
    assert uris and uris[-1].startswith("https://upload.example")
    assert video_url(vid) == "https://youtu.be/VID123"


def test_resume_uri_is_applied(tmp_path):
    yt = FakeYouTube()
    up = YouTubeUploader(tmp_path, service_factory=lambda c: yt, credentials_loader=lambda p: Creds())
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    up.upload(video, SCRIPT, resume_uri="https://upload.example/resumable/old")
    # the stored URI was applied before the first chunk was sent
    assert yt.request.uri_at_first_chunk == "https://upload.example/resumable/old"
    up.upload(video, SCRIPT)
    assert yt.request.uri_at_first_chunk is None


def test_invalid_grant_triggers_reauth(tmp_path):
    flows = []

    class Flow:
        def run_local_server(self, port, open_browser):
            flows.append(port)
            return Creds()

    expired = Creds(valid=False, expired=True, refresh_token="r", refresh_error=Exception("invalid_grant: Token has been expired or revoked."))
    up = YouTubeUploader(tmp_path, flow_factory=lambda secret, scopes: Flow(), credentials_loader=lambda p: expired)
    creds = up.credentials()
    assert flows == [0] and creds.valid
    assert json.loads((tmp_path / "token.json").read_text()) == {"token": "new"}


def test_other_refresh_errors_propagate(tmp_path):
    expired = Creds(valid=False, expired=True, refresh_token="r", refresh_error=Exception("network down"))
    up = YouTubeUploader(tmp_path, flow_factory=lambda s, sc: pytest.fail("no reauth"), credentials_loader=lambda p: expired)
    with pytest.raises(Exception, match="network down"):
        up.credentials()


def test_scope_and_secret_location(tmp_path, monkeypatch):
    assert SCOPES == ["https://www.googleapis.com/auth/youtube.upload"]
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from shortsgen.config import Settings

    s = Settings()
    up = YouTubeUploader(s.secrets_dir)
    assert up.client_secret == tmp_path / "shortsgen" / "client_secret.json"
    assert up.token_path == tmp_path / "shortsgen" / "token.json"


def test_metadata_file(tmp_path):
    p = metadata.write(SCRIPT, tmp_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["title"] and data["description"] and data["hashtags"]
