# 결과보고서: tasks-job-crawler-push22.md

> 완료일: 2026-08-24
> Push 범위: 화면 제목 변경과 환경변수 기반 비밀번호 잠금

## 구현 요약

| 작업 | 상태 | 커밋 |
|---|---|---|
| 22.2 비밀번호 잠금 | 완료 | `1b6c9cf` |
| 22.3 배포 구성과 문서 | 완료 | `67e5a64` |
| 22.1 화면 제목 | 완료 | `afbf01d` |

Push 21 이 `app/templates/base.html` 을 쓰고 있어 제목을 마지막으로 미뤘다. 21.x 커밋이 올라온
것을 확인한 뒤 건드렸고 충돌은 없었다.

## 생성·수정 파일

- `app/api/auth.py` (신규) - 비밀번호 확인과 서명 쿠키. 키는 비밀번호에서 파생한 HMAC-SHA256
- `app/templates/pages/login.html` (신규) - 로그인 화면
- `tests/conftest.py` (신규) - 모든 TestClient 에 정상 서명 쿠키를 붙인다. 잠금을 끄는 스위치를
  두지 않아 전체 스위트가 미들웨어를 그대로 통과한다
- `tests/test_admin_auth.py`, `tests/test_page_title.py` (신규)
- `app/main.py`, `app/config.py`, `app/templates/base.html`
- `.env.example`, `docker-compose.yml`, `docker-compose.coolify.yml` - 이름만, 값 없음
- `.claude/docs/api-contract.md` - 제공 API 잠금과 소비 측 자격증명 미정 명시

## 검증 결과

포트 8070 에 운영 DB 사본으로 띄워 확인했다.

`/health` 는 열려 있다. Coolify 가 이것으로 배포 성공을 판정한다.

| 경로 | 쿠키 없이 |
|---|---|
| `/health` | 200 `{"status":"ok"}` |
| `/` | 303 → `/login?next=%2F` |
| `/api/jobs`, `/api/jobs/delivered` | 401 |
| `/ui/settings/export` | 401 (DB 통째 내려받기) |
| `/ui/health` (htmx) | 401 + `HX-Redirect: /login` |
| `/openapi.json` | 401 |

`PUBLIC_PATHS` 는 `/health`, `/login`, `/logout` 셋뿐이고 기준이 "열어 둔 것 말고 전부" 라
새 라우트가 생겨도 기본이 잠김이다.

지어낸 쿠키는 전부 401 이다 — 값만 넣은 것, 형식만 맞춘 것, 43자 서명을 채운 것, 만료된 것.
다른 비밀번호로 뜬 서버에 재사용한 것도 401 이다. 비밀번호를 바꾸면 이미 나간 쿠키가 전부
무효가 되고, 별도 `SECRET_KEY` 를 둘 필요가 없다.

그 밖에:

- 틀린 비밀번호는 401 에 한 줄뿐이고 무엇이 틀렸는지 말하지 않는다
- 응답과 로그에 비밀번호 값 노출 0건
- 기본값일 때 기동 로그와 화면 양쪽에 경고, 설정하면 사라진다
- 인증 후 `/ui/settings/export` 741,376 bytes, `/api/jobs` 148건 — 미들웨어가 파일 응답과
  데이터 경로를 막지 않는다
- `docker compose -f docker-compose.coolify.yml config` exit 0
- 테스트 727 passed, ruff·mypy 에러 0

## 이슈 및 특이사항

**`hmac.compare_digest` 가 ASCII 밖 문자열에 `TypeError` 를 낸다.** 한글 비밀번호를 넣으면
로그인이 500 이 되고 쿠키에 한글이 섞여도 500 이 된다. 바이트로 견주도록 고쳤고
(`app/api/auth.py:108`) 한글 비밀번호 테스트를 넣었다.

**빈 `ADMIN_PASSWORD` 가 자물쇠를 조용히 열 뻔했다.** Coolify 에 변수를 넣지 않으면 compose 가
`ADMIN_PASSWORD: ""` 로 채워 넘긴다. 그대로 두면 빈 문자열이 비밀번호가 되면서 기본값 경고도
뜨지 않는다 — 잠갔다고 믿는 채로 열려 있는 상태다. 빈 값은 설정하지 않은 것으로 보고 기본값으로
되돌린다. `.env.example` 의 줄도 같은 이유로 주석으로 뒀다.

**탭 제목은 `화면 이름 — 크롤링 자동화 운영 화면 made by seongbin` 형태다.** 상단 제목은 요청한
문구 그대로다. 화면 7개가 저마다 `title` 블록을 채우고 있어 base.html 기본값만 바꾸면 탭에는
나오지 않는다. 탭에 서비스 이름만 나오길 원하면 `app/templates/pages/*.html` 의 `title` 블록
7줄을 지우면 된다.

## 배포 시 필요한 조치

`docker-compose.coolify.yml` 의 `image:` SHA 태그를 새 커밋 것으로 바꾸고, Coolify 환경변수에
`ADMIN_PASSWORD` 를 넣어야 한다. 넣지 않으면 배포는 되지만 기본값 `1234` 로 열린다.
