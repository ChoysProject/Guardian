# Guardian

폐쇄망에서 여러 서버 로그를 모아 이상징후를 찾고, 지정 시각에 일일 보고서를 만드는 로컬 분석 서비스입니다.

개인 PC의 `localhost`에서 검증한 뒤, 같은 코드를 사내 서버로 옮기는 것을 전제로 합니다.

## 원칙

1. **exe가 아니라 로컬 웹 서비스**입니다. 브라우저는 UI이고, 스케줄·수집·플러그인은 백엔드가 담당합니다.
2. **SSH는 첫 Collector일 뿐**입니다. 수집 방법과 분석 파이프라인은 분리되어 있습니다.
3. **탐지의 정답은 규칙/플러그인**입니다. Dify/Ollama는 추린 Finding만 해석합니다. 원본 로그 전체를 LLM에 넣지 않습니다.
4. **Stage 1은 코어**입니다. 서버별 플러그인(Stage 2)과 보고서 플러그인(Stage 3)은 그 위에 얹습니다.
5. **설정만 바꾸면 이전해집니다.** 코드에 PC 전용 경로를 박지 않습니다.

## 파이프라인

```
서버 --증분 수집--> 정규화 --> Stage1 공통 레벨
                         --> Stage2 서버 플러그인
                         --> Finding 저장
                         --> Dify(선택, 요약만)
                         --> Stage3 보고서 플러그인
```

## 빠른 시작

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy config.example.yaml config.yaml
python -m app
```

브라우저에서 http://127.0.0.1:8080 을 엽니다. `seed_demo: true` 이면 샘플 로그 서버가 등록됩니다.

## 사내 서버로 이전

1. `config.yaml`에서 `app.host` 를 `0.0.0.0` 으로 바꾸고 `auth.enabled: true` 로 켭니다.
2. 필요하면 `database.url` 을 PostgreSQL 로 바꿉니다.
3. Linux: `scripts/guardian.service` 를 systemd에 등록합니다.
4. Windows: `scripts/install-windows-service.ps1` 로 시작 시 기동 작업을 등록합니다.

설정 파일 경로는 환경변수 `GUARDIAN_CONFIG` 로 지정할 수 있습니다.
