# 결과보고서: tasks-job-crawler-push21.md

> 완료일: 2026-08-24
> Push 범위: 화면에 그리는 시각을 저장된 UTC 에서 운영자의 시간대로 옮긴다

## 구현 요약

| 작업 | 상태 | 커밋 |
|---|---|---|
| 21.1 표시용 시각 필터 | 완료 | `b4e17f5` |
| 21.2 시각을 그리는 모든 화면에 적용 | 완료 | `ce6c3dc` |
| 21.3 제공 API 는 UTC 그대로 | 완료 | `543cafb` |

## 생성·수정 파일

- `app/api/ui.py` - `format_time` 이 시간대 없는 저장 형식을 UTC 로 읽어 설정된 시간대로 옮기고
  약칭을 붙인다. `_zone()` 이 못 찾은 시간대를 UTC 로 떨어뜨려 설정 오타로 화면이 죽지 않는다
- `app/config.py`, `.env.example`, `docker-compose.yml`, `docker-compose.coolify.yml` -
  `DISPLAY_TIMEZONE` 추가, 기본값 `Asia/Seoul`
- `app/templates/fragments/health.html` - 필터를 거치지 않던 유일한 자리. 라우트가 서버
  프로세스의 로컬 시각을 넘기고 있어 컨테이너가 UTC 로 뜬 상태에서 화면 하단만 어긋나 있었다
- `.claude/docs/api-contract.md` - 응답의 시각과 화면의 시각이 다르다는 절 추가
- `tests/test_display_timezone.py` - 변환 단위 테스트와 누락 검사

## 무엇을 바꾸지 않았나

저장된 값은 하나도 건드리지 않았다. 마이그레이션 없음, `app/api/jobs.py` 변경 없음.

`normalized_at` 은 제공 API 의 폴링 커서다. 값을 옮기면 소비 측 커서가 어긋나 이미 받은 행을
다시 받거나 건너뛴다 (`.claude/docs/api-contract.md`). 바뀌는 것은 화면에 그리는 순간뿐이다.

## 검증 결과

포트 8000 운영 컨테이너는 그대로 두고, 컨테이너 안에서 `VACUUM INTO` 로 뜬 DB 사본을 8060 에
띄워 확인했다. 사본에서 워크플로우를 `paused` 로 내려 실사이트 재수집이 나가지 않게 했다.

기준 시각 `2026-08-24 05:50 KST`, DB 원본 `last_run_at = 2026-08-23 20:45:53`.

| 화면 | 확인한 값 |
|---|---|
| `/ui/workflows` | 최근 실행 `05:45:53 KST`, 다음 실행 `06:19:50 KST (약 29분 뒤)` |
| `/ui/jobs` | 정규화 `03:56:43 KST`, 전달 `04:30:00 KST` |
| `/ui/jobs/188` | 수집·정규화·전달 전부 KST |
| `/ui/review`, `/ui/review/modal/188` | 수집 시각 전부 KST |
| `/ui/renormalize` | 실제 재정규화 실행, 시작·종료 KST |
| `/rules` | 시각 출력 없음. 보이는 날짜는 운영자가 쓴 규칙 note 본문이라 대상 아님 |
| 푸터 `/ui/health` | `05:50:10 KST`, 벽시계와 일치 |

HTMX 스왑 3건도 갈려 들어온 조각에 KST 가 들어 있는지 확인했다 — 카드 폴링
`GET /ui/workflows/2/card`, 주기 저장 `PATCH /ui/workflows/2`, 데이터 조회 필터
`GET /ui/jobs?workflow_id=2`. 7개 페이지 전부 200.

누락 검사는 grep 을 테스트로 굳혔다.
`tests/test_display_timezone.py::test_시각을_그리는_모든_자리가_필터를_거친다` 가
`app/templates/` 전체를 훑는다. 일부러 필터 없는 줄을 넣어 실패하는 것을 확인하고 되돌렸다.

테스트 715 passed, 0 failed (`-m "not live"`). ruff, mypy 변경 파일 error 0.

## 이슈 및 특이사항

- 운영 컨테이너(8000)는 아직 옛 이미지라 화면이 UTC 다. 재빌드해야 반영된다
- `app/api/ui_settings.py:152` 의 스냅샷 파일명 스탬프(`jobs-20260823-2049.db`)는 UTC 로 두었다.
  화면에 그리는 값이 아니라 데이터 파일 이름이고, 서버 지역이 달라도 같은 이름이 나오는 편이 낫다
- 같은 저장소에서 Push 22 가 동시에 진행 중이라 `app/api/auth.py`, `tests/conftest.py`,
  `app/main.py`, `app/templates/base.html` 은 스테이징에서 제외했다
