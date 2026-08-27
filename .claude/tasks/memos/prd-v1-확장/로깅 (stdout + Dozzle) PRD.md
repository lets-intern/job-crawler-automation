# [확장] 로깅 (stdout + Dozzle) PRD

> 본 문서는 `job-crawler-prd.md`(채용공고 크롤링 자동화 서비스)의 확장 기능이다. 애플리케이션 로그를 어떻게 남기고 확인할지에 대한 설계다.

## 1. 개요

크롤링/정규화/임베딩/검수/ES 적재 등 여러 단계에서 발생하는 에러와 실행 상세를 파악하려면 로그가 필요하다. 단, 이 로그는 어드민 UI에서 조회해야 하는 "요약 데이터"(성공/실패 건수 등, `crawl_runs` 테이블 담당)와는 별개로, 개발/운영자가 문제 상황을 깊이 파고들 때 보는 "상세 로그"를 말한다. 이 상세 로그는 DB에 쌓지 않고 stdout으로 출력해 Dozzle로 확인하는 구조로 설계한다.

## 2. 목표 / 비목표

**목표**
- 애플리케이션 로그를 stdout으로만 출력 (파일 저장 없음)
- Docker Compose에 Dozzle을 함께 띄워 별도 인프라 없이 브라우저에서 실시간 로그 확인
- 로그를 구조화(JSON)해서 나중에 검색/파싱하기 쉽게 함
- Docker 로깅 드라이버 옵션으로 로그 파일 크기를 제한해 디스크 무한 증가 방지

**비목표**
- 로그 장기 보관/아카이빙 (Docker 로그 로테이션 범위를 벗어나는 보관은 1차 범위 밖)
- 로그 기반 알림/모니터링 시스템 구축 (Grafana/Alertmanager 연동 등)
- 여러 서버(멀티 호스트) 환경의 통합 로그 수집 — 1차는 단일 Docker 호스트 가정

## 3. 로그 설계

### 3.1 출력 방식
- Python `logging` 모듈 + `StreamHandler`(stdout)만 사용
- 파일 핸들러(`RotatingFileHandler` 등) 사용하지 않음 — Dozzle은 컨테이너의 stdout/stderr만 읽으므로, 파일로 쌓으면 오히려 Dozzle에서 안 보이고 관리 포인트만 늘어남
- 포맷은 JSON 한 줄(1 log = 1 line)로 구조화 — 사람이 Dozzle 화면에서 훑어보기도 가능하고, 필요 시 텍스트 검색(grep)도 용이

### 3.2 로그 레벨
- `INFO`: 워크플로우 실행 시작/종료, 정상 처리 건수 등 정상 흐름 기록
- `WARNING`: 재시도가 발생했지만 최종적으로는 성공한 경우, 셀렉터 매칭이 일부 실패한 경우 등
- `ERROR`: 크롤링/정규화/임베딩/ES 적재 등 각 단계에서 실패한 경우 (스택트레이스 포함)
- `DEBUG`: 개발 중 상세 추적용, 운영 환경에서는 기본 비활성화 (환경변수로 레벨 조정 가능하게)

### 3.3 로그 필드 (구조화 항목)
공통 필드를 모든 로그 라인에 포함해 Dozzle에서 훑어볼 때/추후 검색할 때 식별 가능하게 함:
- `timestamp`
- `level`
- `message`
- `workflow_id` / `workflow_name` (해당되는 경우)
- `stage` (예: crawl / normalize / embed / review / es_index)
- `error` (스택트레이스 또는 에러 메시지, ERROR 레벨인 경우)

### 3.4 로그 대상 (무엇을 남길지)
- 워크플로우 실행 시작/종료 및 소요 시간
- 크롤링 단계별 성공/실패 (사이트 접근 실패, 셀렉터 매칭 실패 등)
- 정규화/임베딩 처리 중 예외
- AI 검수 배치 처리 시작/종료, LLM 호출 실패
- ES 적재 성공/실패
- 스케줄러(크롤링 주기, 검수 주기) 트리거 로그

## 4. 확인 방법 (Dozzle)

- Docker Compose에 Dozzle 컨테이너 추가, `docker.sock` 마운트로 `api` 컨테이너의 stdout을 자동 인식
- 별도 설정/DB 없이 Dozzle 하나로 실시간 로그 확인 가능 (컨테이너가 늘어나도 Dozzle 추가 불필요, 같은 Docker 호스트면 자동으로 잡힘)
- 어드민 UI 안에 자체 로그 뷰 화면은 만들지 않음 — Dozzle이 그 역할을 대신함

```yaml
services:
  api:
    # ... 기존 설정
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  dozzle:
    image: amir20/dozzle:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    ports:
      - "8888:8080"
```

## 5. 비기능 요구사항

- 로그에 개인정보/민감정보(API 키 등)가 그대로 찍히지 않도록 주의 (예: LLM API 키는 마스킹)
- 로그 볼륨이 과도하게 커지지 않도록 `json-file` 드라이버의 `max-size`/`max-file`로 상한 설정 (오래된 로그는 자동 삭제됨을 감안하고 설계)
- `crawl_runs`(DB, 요약)와 stdout 로그(상세)의 역할을 명확히 분리 — 어드민 UI에 필요한 조회는 반드시 DB 쪽에 남기고, stdout 로그에만 의존하지 않음

## 6. 미결정 사항 (Open Questions)

- Dozzle 접근에 별도 인증을 걸지 여부 (기본적으로 인증 없음 — 내부망 전용으로만 노출할지, 인증 프록시를 앞단에 둘지)
- 로그 레벨을 환경변수로 제어하는 것 외에, 운영 중 실시간으로 레벨을 바꿀 수 있게 할지
- 추후 로그 장기 보관/검색이 필요해질 경우 Loki 등 도입 시점