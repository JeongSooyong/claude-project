"""YouTube Data API v3 private upload (installed-app OAuth, youtube.upload scope only).

Secrets live outside the repo: <secrets_dir>/client_secret.json and <secrets_dir>/token.json
(default %APPDATA%/shortsgen). In Google Cloud "Testing" status, refresh tokens expire after
7 days; an `invalid_grant` refresh failure re-runs the browser consent flow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..models import Script
from .metadata import video_body

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CHUNK = 8 * 1024 * 1024


class AuthSetupError(RuntimeError):
    pass


def video_url(video_id: str) -> str:
    return f"https://youtu.be/{video_id}"


class YouTubeUploader:
    def __init__(
        self,
        secrets_dir: Path,
        service_factory: Callable | None = None,
        flow_factory: Callable | None = None,
        credentials_loader: Callable | None = None,
    ):
        self.secrets_dir = Path(secrets_dir)
        self._service_factory = service_factory
        self._flow_factory = flow_factory
        self._credentials_loader = credentials_loader

    @property
    def client_secret(self) -> Path:
        return self.secrets_dir / "client_secret.json"

    @property
    def token_path(self) -> Path:
        return self.secrets_dir / "token.json"

    # --- auth ---
    def _load(self):
        if self._credentials_loader:
            return self._credentials_loader(self.token_path)
        if not self.token_path.exists():
            return None
        from google.oauth2.credentials import Credentials

        return Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

    def _run_flow(self):
        if self._flow_factory:
            flow = self._flow_factory(self.client_secret, SCOPES)
        else:
            if not self.client_secret.exists():
                raise AuthSetupError(
                    f"OAuth 클라이언트 파일이 없습니다: {self.client_secret}. README의 'YouTube 업로드 설정'을 따라 주세요."
                )
            from google_auth_oauthlib.flow import InstalledAppFlow

            flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secret), SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
        self._save(creds)
        return creds

    def _save(self, creds) -> None:
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")

    def credentials(self):
        creds = self._load()
        if creds is not None and creds.valid:
            return creds
        if creds is not None and creds.expired and creds.refresh_token:
            try:
                from google.auth.transport.requests import Request

                creds.refresh(Request())
                self._save(creds)
                return creds
            except Exception as e:  # RefreshError('invalid_grant', ...) when the 7-day token expired
                if "invalid_grant" not in str(e):
                    raise
        return self._run_flow()

    def _service(self):
        creds = self.credentials()
        if self._service_factory:
            return self._service_factory(creds)
        from googleapiclient.discovery import build

        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    # --- upload ---
    def upload(self, video: Path, script: Script, resume_uri: str | None = None, on_uri: Callable[[str], None] | None = None) -> str:
        from googleapiclient.http import MediaFileUpload

        youtube = self._service()
        media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=CHUNK, resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=video_body(script), media_body=media)
        if resume_uri:
            request.resumable_uri = resume_uri
        response = None
        while response is None:
            _, response = request.next_chunk()
            uri = getattr(request, "resumable_uri", None)
            if uri and on_uri:
                on_uri(uri)
        return response["id"]
