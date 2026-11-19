# shortsgen — 기술 문서로 유튜브 쇼츠 만들기

기술 문서 URL 하나 또는 Markdown 파일 하나를 넣으면 다음 순서로 진행됩니다.

1. Claude가 장면별 한국어 대본, 제목, 설명, 해시태그를 씁니다.
2. 로컬 웹 화면에서 대본을 검토하고 고칩니다.
3. 승인하면 OpenAI 배경 이미지, 원문 그대로의 코드, 한국어 TTS와 자막으로 1080×1920 영상(30~59초)을 렌더링합니다.
4. 버튼 하나로 YouTube에 **비공개**로 업로드합니다.

PC 한 대에서 혼자 쓰는 도구입니다. 서버는 `127.0.0.1`에서만 열립니다.

## 동작 원칙

- **코드는 다시 쓰지 않습니다.** 대본은 코드를 "블록 ID + 줄 범위"로만 가리키고, 화면에는 문서의 원문을 그대로 그립니다. 바뀌는 것은 줄바꿈(CRLF→LF)과 탭(공백 4칸)뿐입니다. 화면에 들어가지 않는 코드는 잘라내지 않고 오류로 알려 줍니다.
- **승인한 내용 그대로 렌더링합니다.** 승인할 때 대본과 모든 이미지·음성을 해시로 기록합니다. 그 뒤에 하나라도 바뀌면 렌더링과 업로드를 거부합니다(HTTP 409). 업로드는 렌더링된 mp4 파일의 해시도 확인합니다.
- **길이는 실제로 잽니다.** TTS 음성의 샘플 수로 장면 길이와 자막 타이밍을 계산합니다. 예상 길이가 30~59초를 벗어나면 승인할 수 없습니다.

## 설치 (Windows 11)

```powershell
winget install Python.Python.3.12
winget install astral-sh.uv
winget install Gyan.FFmpeg
# 새 터미널을 열어 PATH를 갱신한 뒤:
cd shortsgen
uv sync
copy .env.example .env   # 그다음 API 키를 입력
uv run shortsgen         # http://127.0.0.1:8765
```

폰트는 저장소에 들어 있습니다. 둘 다 SIL OFL 라이선스입니다.

| 용도 | 폰트 | 출처 |
|---|---|---|
| 본문·자막 | Noto Sans KR | github.com/notofonts/noto-cjk |
| 코드 (한글 주석 포함) | D2Coding | github.com/naver/d2codingfont |

API 키 없이 화면만 둘러보려면 가짜 공급자로 실행합니다.

```powershell
$env:SHORTSGEN_FAKE="1"; uv run shortsgen
```

## API 키 (`.env`)

| 변수 | 설명 |
|---|---|
| `ANTHROPIC_API_KEY` | Claude가 대본과 메타데이터를 생성 |
| `OPENAI_API_KEY` | 배경 이미지와 한국어 TTS |
| `SCRIPT_MODEL` | 기본값 `claude-sonnet-5-5` |
| `IMAGE_MODEL` / `IMAGE_QUALITY` | 기본값 `gpt-image-1` / `low` |
| `TTS_MODEL` / `TTS_VOICE` | 기본값 `gpt-4o-mini-tts` / `alloy` |
| `COST_CEILING_KRW` | 프로젝트당 **비용 상한**(기본 1000원). 이 금액을 넘는 호출은 거부합니다. 목표는 편당 700원 이하입니다. |
| `USD_KRW` | 환율. 비용을 원화로 표시할 때 씁니다 |

`.env`, OAuth 클라이언트 파일, 토큰은 git에서 제외되어 있습니다.

## YouTube 업로드 설정

1. Google Cloud Console에서 프로젝트를 만들고 **YouTube Data API v3**를 사용 설정합니다.
2. **OAuth 동의 화면**을 "외부"로 만들고, 내 Google 계정을 **테스트 사용자**로 추가합니다.
3. **사용자 인증 정보 → OAuth 클라이언트 ID → 데스크톱 앱**을 만들고 JSON을 내려받습니다.
4. 내려받은 파일을 `%APPDATA%\shortsgen\client_secret.json`으로 저장합니다(저장소 밖).
5. 처음 업로드할 때 브라우저가 열리면 로그인하고 허용합니다. 토큰은 `%APPDATA%\shortsgen\token.json`에 저장됩니다.

알아 둘 점:
- 요청하는 권한은 `youtube.upload` 하나뿐입니다.
- 동의 화면이 **"테스트" 상태이면 refresh token이 7일 뒤 만료됩니다.** 만료되면(`invalid_grant`) 다음 업로드 때 로그인 창이 다시 열립니다.
- 업로드는 항상 `privacyStatus=private`입니다. 그 밖에 `selfDeclaredMadeForKids=false`, `containsSyntheticMedia=true`(AI 생성 배경 이미지 공개)를 함께 보냅니다.
- 현재 YouTube 문서(2026-11 확인)에 따르면 다음과 같습니다.
  - 검증되지 않은 API 프로젝트로 올린 영상도 비공개 모드로 고정되지 않습니다. 공개 전환은 YouTube Studio에서 직접 하면 됩니다.
  - `videos.insert`는 Video Uploads 쿼터 버킷에서 1 unit을 씁니다.
- 9:16이고 3분 이하인 영상은 YouTube가 자동으로 쇼츠로 분류합니다. `#Shorts` 태그는 필요 없습니다.

## 사용 흐름

1. 왼쪽에 문서 URL을 넣거나 `.md` 파일을 고르고 **대본 만들기**를 누릅니다.
2. 장면 카드에서 다음을 고칠 수 있습니다.
   - 화면 문구
   - 내레이션 문장과, 각 문장을 말할 때 강조할 코드 줄
   - 이미지 프롬프트
   - 코드 블록과 줄 범위(원문을 보면서 고름)
3. **이미지 생성**과 **음성 생성**을 누릅니다. 바뀐 장면만 다시 생성합니다. 상단에 예상 길이와 누적 비용이 표시됩니다.
4. 장면별 **미리보기**는 실제 렌더링 경로로 만든 짧은 mp4입니다.
5. **승인 → 렌더링 → YouTube 업로드** 순서로 진행합니다. 승인 뒤에 무엇이든 고치면 다시 승인해야 합니다.

## 비용 (참고용 추정)

가격은 `src/shortsgen/config.py`의 `DEFAULT_PRICES`에 들어 있습니다. **실제 사용 전에 현재 가격으로 확인해 주세요.** 아래는 장면 5개, 약 45초 영상 1편 기준입니다(환율 1,400원).

| 항목 | 추정 |
|---|---|
| Claude 대본 (입력 약 8k, 출력 약 2k 토큰) | 약 $0.05 |
| 이미지 5장 (low, 1024×1536) | 약 $0.08 |
| TTS 약 45초 | 약 $0.01 |
| **합계** | **약 $0.14 ≈ 200원** (이미지를 재생성하면 늘어남) |

실제 사용량은 프로젝트마다 `projects/<id>/cost.json`에 기록되고 화면 상단에 표시됩니다.

## 알려진 제한

- JavaScript로 그려지는 문서 페이지는 지원하지 않습니다(정적 HTML의 `<pre>`만 읽음). 이때는 원본 `.md`나 raw URL을 사용해 주세요.
- 화면 움직임은 배경 줌과 코드 줄 하이라이트뿐입니다. 타이핑 애니메이션은 없습니다.
- 문서 하나로 영상 하나만 만듭니다. 시리즈 분할, 예약·공개 업로드, 다른 플랫폼은 범위 밖입니다.

## 실제 API 수동 점검 (키가 있을 때 한 번)

- [ ] 실제 문서 URL로 대본 생성 → 이미지·음성 생성 → 승인 → 렌더링 → 비공개 업로드까지 끝까지 진행
- [ ] 화면 상단의 비용이 **700원 이하**인지 확인 (`cost.json`)
- [ ] 휴대폰에서 코드를 읽을 수 있는지 확인
- [ ] 자막과 음성이 맞는지 확인
- [ ] 배경 이미지에 깨진 글자가 없는지 확인
- [ ] YouTube Studio에서 비공개 상태이고, 쇼츠로 분류됐는지 확인

## 개발

```powershell
uv run pytest            # 오프라인 테스트 전체 (가짜 공급자, 실제 ffmpeg 사용)
uv run pytest -m live    # (선택) 실제 API를 호출하는 테스트
```

구조는 다음과 같습니다.
- `ingest/`: 문서 읽기
- `script/`: 대본 생성·검증
- `timeline/`: 길이·자막 타이밍 계산
- `render/`: Pillow로 레이어를 그리고 ffmpeg로 합성
- `publish/`: YouTube 업로드
- `service.py`: 상태 머신
- `web/`: FastAPI와 정적 UI
