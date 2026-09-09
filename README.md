# Guardian

로컬에 Python만 있으면 기동하는 웹 서비스입니다. 서버 로그 이상징후와 리소스·성능을 모으고, 지정 시각에 보고서를 만듭니다.

폐쇄망 반입을 전제로 합니다. Docker, PostgreSQL, Redis, 외부망은 기본 동작에 필요 없습니다.

## 기동

브라우저: http://127.0.0.1:8080

`seed_demo` 는 기본 `false` 입니다. 켜면 데모 서버와 샘플 로그가 다시 들어갑니다.

**폐쇄망(내부)** 은 아래 [폐쇄망 반입](#폐쇄망-반입) 만 보면 됩니다. pip, venv 없습니다.

**인터넷이 되는 개발 PC** (이 저장소를 고칠 때):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy config.example.yaml config.yaml
python -m app
```

Linux/macOS는 `scripts/run.sh`, Windows는 `scripts/run.ps1` 로도 됩니다. `lib/` 가 있으면 스크립트는 venv 없이 그걸 씁니다.

## 무엇을 하나

| 구분 | 하는 일 |
| --- | --- |
| 로그 | 대상 서버에서 증분 수집 → 규칙 플러그인으로 징후(Finding) → 일일 보고서 |
| 리소스 및 성능 | 대상 서버에서 셸 스크립트로 일자별 JSON → Guardian에 넣기 → 서버별 추이 보고서 |

탐지의 정답은 규칙/플러그인입니다. AI는 추린 결과만 해석하며, 원본 로그 전체를 넣지 않습니다. AI가 꺼져 있거나 실패해도 규칙 보고서는 그대로 나옵니다.

## 리소스 및 성능

1. **플러그인 → 리소스 및 성능 쉘 스크립트**에서 모듈을 고르고 스크립트를 받습니다.
2. 리눅스 서버(또는 WSL)에서 실행하면 `DailyData/YYYY-MM-DD.json` 이 생깁니다.
3. **서버 → 리소스 및 성능 수집 대상 서버**에 서버를 등록하고, 그 JSON을 넣습니다.
4. **보고서 → 리소스 및 성능 보고서**에서 서버 박스를 눌러 목록을 고르면 상세가 열립니다.

박스에는 CPU · 메모리 · 디스크(필요하면 인스턴스)만 보입니다. 메모리는 캐시를 뺀 실사용(available 기준)과 스왑을 같이 표시합니다. WSL에서 돌리면 윈도 작업 관리자가 아니라 **그 리눅스 환경** 숫자가 맞습니다.

`df -i` 가 `-` 를 내는 마운트(Windows 드라이브 등)는 JSON을 깨지 않게 빈 값으로 읽습니다.

## 데이터가 쌓이는 곳

| 위치 | 내용 |
| --- | --- |
| `data/guardian.db` | SQLite. 서버 등록, 징후, 보고서 목록 등 시스템 데이터 |
| `data/resources/{서버}/{날짜}.json` | 리소스 일자별 원자료 |
| `data/reports/` | 보고서 HTML · Markdown 본문 |

SQLite는 별도 DB 서버가 없습니다. Guardian을 꺼도 파일은 남고, 다시 켜면 그대로 읽습니다.

## 설정

`config.example.yaml` 을 `config.yaml` 로 복사합니다. 경로를 바꾸려면 환경변수 `GUARDIAN_CONFIG` 를 씁니다.

로컬 기본값:

- `app.host: 127.0.0.1`
- `database.url: sqlite:///data/guardian.db`
- `auth.enabled: false`
- `openai.enabled` / `dify.enabled` 로 AI 경로 선택

사내·폐쇄망:

1. `app.host: 0.0.0.0`
2. `auth.enabled: true` 와 비밀번호 변경
3. `openai.enabled: false`
4. 망 안에 Dify가 있으면 `dify.enabled: true` 와 `base_url`, `api_key`, `workflow_id`
5. 필요하면 `database.url` 을 PostgreSQL 로 변경

Linux 상주: `scripts/guardian.service`  
Windows 시작 시 기동: `scripts/install-windows-service.ps1`

## 폐쇄망 반입

안쪽은 pip 를 못 씁니다. **바깥에서 패키지를 `lib/` 로 풀어 zip 에 넣고**, 안에서는 Python 만으로 기동합니다. 손대는 설정은 **Dify IP(`dify.base_url`)** 입니다.

안쪽 파이썬은 Windows 64bit **3.13** 기준입니다. 버전 확인은 `python -V` 가 아니라 `py -V` 입니다.

**1. 바깥에서 묶기** (인터넷이 되는 PC)

```powershell
.\scripts\pack-import.ps1
```

`dist/guardian-import-날짜.zip` 에 코드와 **이미 풀린 `lib/`** 가 들어갑니다. `data/`, `.venv`, `config.yaml` 은 넣지 않습니다.

이 개발 PC가 3.10 이어도, pip 가 3.13 Windows 휠만 받아 `lib/` 에 풉니다. 실패하면 안쪽과 같은 3.13 Windows 에서 스크립트를 다시 돌리면 됩니다.

**2. 내부에서 풀고 기동** (pip · venv 없음)

zip 을 풀고:

```powershell
copy config.example.yaml config.yaml
```

`config.yaml` 에서 `dify.base_url` 의 호스트만 내부 Dify IP로 바꿉니다. 예: `http://10.0.0.12/v1`

그다음:

```powershell
py -m app
```

또는 `.\scripts\run.ps1` (`lib/` 가 있으면 pip 를 돌리지 않습니다).

`python` 명령은 Windows 스토어 스텁인 경우가 있어 `Python` 만 찍히고 끝납니다. 반드시 `py` 를 쓰세요.

## 플러그인

- Stage 1: 로그 레벨 등 공통
- Stage 2: 서버별 로그 규칙
- Stage 3: 로그 보고서
- Stage 4: 리소스 수집 셸 스크립트 (`plugins/stage4/resource_basic` 이 기본본)

새 리소스 스크립트는 화면에서 모듈을 고르면 만들어집니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
