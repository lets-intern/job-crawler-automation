# Tasks: 본문 나누기 - Push 1

> PRD: `.claude/tasks/todo/prd-split-body.md`
> Push 범위: 열한 사이트 응답을 대조해 칸을 확정하고 스키마를 만든다
> 상태: 완료

## 배경 (PRD 를 안 봐도 되도록)

지금 `normalized_jobs` 는 공고를 여섯 칸에 담는다 — `company` `title` `department`
`deadline` `body` `requirements`. 그런데 **사이트가 이미 나눠서 주는 것을 도로 합치고 있다.**

칸이 모자라 빈 칸을 채우려다 **한화 `department` 에 근무지(`ruWorkpl`)가 들어가 있다.**
307건 중 `department` 43건, `requirements` 23건이 비어 있다.

## 확정 기준

**넷 이상의 사이트에서 나오는 것만 칸으로 만든다.** 한 사이트만 가진 값을 칸으로 만들면 나머지
열 곳이 비는 칸이 하나 는다.

지금 여섯 곳으로 뽑은 안이 PRD 에 있다. **열한 곳으로 다시 세어 확정하는 것이 1.1 이다.**
새 다섯 곳이 `모집인원` 을 준다면 그 칸이 살아나고, 반대로 지금 넣기로 한 칸이 빠질 수도 있다.

## 매핑하지 않은 필드는 저장하지 않는다

결정된 사항이다 (PRD). `raw_jobs` 에는 매핑한 칸만 들어가고 나머지는 버린다. 나중에 칸을
늘리려면 재크롤링해야 하고, 그때까지 마감돼 내려간 공고는 그 값을 얻지 못한다.

## 관련 파일

- `migrations/` - 0010 까지 있다. 새 파일은 `0011_` 로 시작한다
- `app/api/jobs.py` - 제공 API 의 응답 모델
- `app/normalize/engine.py`, `app/normalize/rules.py` - 정규화가 칸마다 돈다
- `app/crawler/runner.py` 의 `_record()` - 목록 값과 상세 값을 합쳐 `raw_jobs` 행을 만든다
- `app/selector/schema.py`, `app/selector/api_schema.py` - 어떤 필드 이름이 허용되는지
- `.claude/site-recipes/` - 열한 사이트 기록
- `tests/fixtures/` - 여섯 사이트 응답이 있다. 새 다섯 곳은 없다

## 선행 조건

- 없음

## 작업

- [x] 1.0 칸을 확정하고 스키마를 만든다
    - [x] 1.1 새 다섯 사이트의 상세 응답을 받아 픽스처로 둔다
        - 두산(31)·네이버(32)·토스(33)·카카오(30)·우아한형제들(29). 크롤러 설정의
          `detail_url` 을 그대로 열었다
        - **사이트당 상세 1회씩, 다섯 번만** 요청했다. 목록은 새로 받지 않았다 —
          카카오·우아한형제들은 목록이 API 라 2026-08-25 픽스처가 그대로 쓰인다
        - 공용 fetch 클라이언트로 나갔다. 카카오·우아한형제들 상세는 `detail_mode` 가
          `playwright` 라 `Renderer` 를 거쳤고, 그것도 `Fetcher.guard()` 안이다

          | 사이트 | 픽스처 | 바이트 |
          |---|---|---|
          | 두산 | `tests/fixtures/doosan-detail-1000361539-20260826.html` | 58,857 |
          | 네이버 | `tests/fixtures/naver-detail-30005299-20260826.html` | 111,120 |
          | 토스 | `tests/fixtures/toss-detail-7827417003-20260826.html` | 123,122 |
          | 카카오 | `tests/fixtures/kakao-detail-P-14503-20260826.html` | 14,750 |
          | 우아한형제들 | `tests/fixtures/woowa-detail-R2607031-20260826.html` | 37,145 |

        - [x] 1.1.V 검증: `tests/test_new_site_fixtures.py` 5개 통과. 픽스처마다 제목·이름표·
          본문이 실제로 들어 있는지 본다
    - [x] 1.2 열한 사이트를 대조해 칸을 확정한다 — **아래 "확정한 표"**
        - [x] 1.2.V 검증: `tests/test_split_body_columns.py` 4개 통과. 표에 적힌 자리가
          픽스처에서 실제로 값을 내놓는지까지 본다. 넷 미만인 칸 0개
    - [x] 1.3 마이그레이션 0011 로 칸을 더한다 — `migrations/0011_split_body_columns.sql`
        - `normalized_jobs` 에 `ALTER TABLE ADD COLUMN` 열 개. 전부 TEXT 이고 NULL 을
          허용한다. 기본값을 두지 않았다 — 사이트가 주지 않는 칸은 빈 칸이다
        - 기존 여섯 칸은 건드리지 않았다. `deadline` 은 모집 마감일 그대로 두고 모집 시작일을
          `start_date` 로 새로 더했다. 이 파일에 `normalized_jobs` 를 대상으로 하는 UPDATE 가
          없다
        - `job_field_overrides.field_name` 의 CHECK 는 넓히지 않았다. 그 컬럼이
          `UNIQUE (raw_job_id, field_name)` 인덱스에 걸려 있어 0009·0010 의 방법(새 CHECK 를
          단 컬럼 추가 -> 값 이동 -> 옛 컬럼 삭제)이 통하지 않는다 — SQLite 는 인덱스가 걸린
          컬럼을 DROP 하지 못한다. 손보정은 여섯 칸 그대로다
        - 되돌리기: `migrate down` 이 더한 열 칸을 역순으로 지운다. 지워지는 것은 새 칸의
          값뿐이고, 출처인 `raw_jobs` 는 append-only 라 재정규화로 되살린다. 주석에 적었다
        - `.claude/docs/data-model.md` 의 `normalized_jobs` 표를 같은 커밋에서 고쳤다
        - [x] 1.3.V 검증
            - `tests/test_migrations.py` 61개 통과. 적용·역적용, 새 칸이 NULL 인지,
              역적용이 더한 열 칸만 지우는지를 본다
            - 운영 DB(포트 8000 컨테이너, `/data/jobs.db`)에 적용했다. 컨테이너는 내리지
              않았고 삭제·수정 문장은 보내지 않았다
            - 적용 전 `VACUUM INTO /data/jobs-before-0011-20260826.db` (3,624,960바이트)
            - 적용 전후로 321건의 기존 여섯 칸 + `source_url` + `normalized_at` +
              `delivered_at` 이 같은 값이다 (sha256 `42a40126...971f1` 동일)
            - 새 칸 열 개는 321건 전부 NULL 이다
    - [x] 1.4 새 칸을 파이프라인이 나른다
        - `app/selector/schema.py` — `DetailSelectors` 에 열 필드를 더하고 그 이름을
          `SPLIT_DETAIL_FIELDS` 로 묶었다. 전부 기본값이 있어서 이 필드들이 생기기 전에
          저장된 셀렉터 JSON 이 키 없이도 그대로 통과한다(`OMITTABLE_FIELDS`), 값이 비어도
          실패가 아니다(`OPTIONAL_DETAIL_FIELDS`)
        - `app/selector/api_schema.py` — 상세 `fields` 를 `DETAIL_FIELDS` 로 검증하므로
          새 이름을 그대로 받는다. 고칠 것이 없었다
        - `app/crawler/parser.py`, `app/crawler/api_source.py` — 둘 다 `DETAIL_FIELDS` 를
          훑어 읽으므로 고칠 것이 없었다
        - `app/crawler/runner.py` 의 `_record()` — 상세에서 읽은 값을 그대로 싣는다.
          목록에서 대신 채우지 않는다
        - `app/normalize/rules.py` 의 `NORMALIZED_FIELDS` — 열 칸을 더했다. 규칙 화면의
          필드 목록이 이 값을 읽으므로 새 칸에도 규칙을 걸 수 있다
        - `app/normalize/engine.py` — `insert_normalized()` 가 `NORMALIZED_FIELDS` 에서
          INSERT 문을 만든다. 손으로 적은 목록을 두면 칸이 늘 때마다 둘이 갈린다
        - `app/normalize/engine.py` 의 `OVERRIDABLE_FIELDS` — 여섯 개로 고정했다. 늘리면
          DB 의 CHECK 가 거절하고, 그 실패는 운영자가 저장을 누른 뒤에야 드러난다
        - `app/api/jobs.py` — `JobOut` 과 `_SELECT` 에 열 필드. **더하는 방향이고 기존
          필드는 그대로다.** `.claude/docs/api-contract.md` 를 같은 커밋에서 고쳤다
        - `app/selector/generator.py` — 프롬프트에 새 필드를 적었다. **그 값만 따로 담은
          요소가 있을 때만** 채우고 본문 전체를 가리키지 말라고 못 박았다
        - [x] 1.4.V 검증
            - `tests/test_split_body_pipeline.py` 5개 통과. 두산 목록·상세 픽스처로
              워크플로우를 1회 돌려 `raw_jobs` 와 `normalized_jobs` 를 본다. 두산이 주는
              칸(`job_category`·`work_location`·`headcount`·`duties`·`hiring_process`·
              `etc_info`·`start_date`)은 채워지고, 주지 않는 칸(`department`·
              `employment_type`·`career_level`·`preferred`)은 수집에서 빈 문자열,
              정규화에서 NULL 이다
            - `tests/test_api_jobs.py` 에 소비 측 경계 시험을 더했다. 채워진 칸은 값
              그대로, 주지 않은 칸은 `null` 로 나간다
            - 전체 `pytest -m "not live"` 1,172개 통과. `import app.main` 성공
            - 포트 8000 운영 인스턴스가 새 필드를 실어 응답한다(열 개 전부 `null` —
              매핑은 Push 2 다). `GET /api/jobs` 만 불렀고 `delivered_at` 은 여전히 0건이다

## 확정한 표 (1.2 결과)

열한 사이트 응답을 대조했다. 자리마다 픽스처에서 값이 실제로 나오는 것을 확인했고, 그 대조는
`tests/test_split_body_columns.py` 가 들고 있다 — **Push 2 는 그 파일의 `TABLE` 을 보고
매핑한다.** 여기 표는 사람이 읽는 판이다.

### "준다" 의 뜻

**그 값만 따로 꺼낼 수 있어야 준 것이다.** JSON 필드 하나이거나 이름표가 붙은 DOM 요소
하나여야 한다. 본문 덩어리 안에 `■ 우대사항` 으로 섞여 있는 것은 세지 않았다. 세면 Push 2 가
텍스트를 잘라 채우게 되고 그것이 PRD 가 막으려는 억지로 채우기다.

### 새로 더하는 칸 (10개)

| 칸 | 컬럼 | 주는 곳 | 사이트 |
|---|---|---|---|
| 모집 시작일 | `start_date` | 9 | LG · 한화 · 현대 · 삼성 · SK · 롯데 · 두산 · 네이버 · 우아한 |
| 직군 | `job_category` | 7 | LG · 현대 · SK · 두산 · 네이버 · 카카오 · 우아한 |
| 근무지 | `work_location` | 7 | LG · 한화 · 현대 · 삼성 · SK · 두산 · 카카오 |
| 주요 업무 | `duties` | 7 | LG · 한화 · 현대 · 삼성 · SK · 두산 · 카카오 |
| 전형 절차 | `hiring_process` | 7 | LG · 한화 · 현대 · SK · 롯데 · 두산 · 카카오 |
| 기타 | `etc_info` | 7 | LG · 한화 · 현대 · 삼성 · SK · 롯데 · 두산 |
| 경력 구분 | `career_level` | 5 | LG · 현대 · SK · 네이버 · 우아한 |
| 고용형태 | `employment_type` | 4 | SK · 네이버 · 카카오 · 우아한 |
| 모집인원 | `headcount` | 4 | LG · 한화 · 두산 · 카카오 |
| 우대 조건 | `preferred` | 4 | LG · 현대 · 삼성 · SK |

### 그대로 두는 칸 (6개)

이름도 뜻도 바꾸지 않는다. 소비 측이 읽던 것이 사라지면 안 된다.

| 칸 | 컬럼 | 주는 곳 | 비는 곳 |
|---|---|---|---|
| 제목 | `title` | 11 | 없음 |
| 본문 원문 | `body` | 11 | 없음 |
| 원본 주소 | `source_url` | 11 | 없음 |
| 모집 마감일 | `deadline` | 11 | 없음. **모집 마감일 그대로 두고 시작일을 새로 더한다** |
| 모집 기업 | `company` | 9 | 현대 · 우아한 |
| 필수 조건 | `requirements` | 8 | 네이버 · 토스 · 우아한 |
| 조직·부서 | `department` | 2 | 나머지 아홉 곳. 둘뿐이지만 **이미 있는 칸이라 지우지 않는다** |

`department` 가 둘(LG `orgName`, 현대 `fldCodeNm`)뿐인 것이 지금 한화 `department` 에
근무지가 들어간 이유다. 새 기준이었다면 만들지 않았을 칸이고, 남기되 **아홉 곳은 비운다.**

### 떨어진 후보

| 칸 | 주는 곳 | 판정 |
|---|---|---|
| 조직 소개 | 3 (현대 `aboutTeamNtc` · 삼성 `introKr` · 카카오 `introduction`) | 넷에 못 미쳐 칸으로 만들지 않는다. 그 값은 지금처럼 `body` 에 남는다 |

PRD 는 여섯 곳 기준으로 `조직 소개` 를 후보에 넣고 `모집인원` 을 뺐다. **열한 곳으로 다시
세니 반대가 됐다** — `모집인원` 은 두산과 카카오가 더해져 넷이 되어 살아났고, `조직 소개` 는
새 다섯 곳 중 카카오만 줘서 셋에 머물렀다.

### PRD 의 `고용형태` 는 두 칸이었다

PRD 표의 `고용형태` 행에 적힌 LG `careerTypeName`(신입) · 한화 `rtCarrYn` · SK
`recruitType`(Experienced) 은 전부 **신입/경력**이고 정규직/계약직이 아니다. 다시 세면서
둘로 갈랐다.

- `career_level` 경력 구분 — 신입 / 경력 (5곳)
- `employment_type` 고용형태 — 정규직 / 인턴 / 기간제 (4곳)

한화는 `rtCarrYn` · `rtNrcrtYn` · `rtIntnYn` 이 `Y`/`N` 플래그 셋이라 표시할 값이 아니다.
세지 않았고, 한화 `career_level` 은 **빈다.**

### 사이트가 주지 않는 칸은 비운다

억지로 채울 자리를 미리 없앤다. 값이 없으면 빈 칸이고, 빈 칸이 틀린 값보다 낫다.

| 사이트 | 비는 칸 |
|---|---|
| LG | 고용형태 |
| 한화 | 조직·부서 · 직군 · 고용형태 · 경력 구분 · 우대 조건 |
| 현대자동차 | 모집 기업 · 고용형태 · 모집인원 |
| 삼성 | 조직·부서 · 직군 · 고용형태 · 경력 구분 · 모집인원 · 전형 절차 |
| SK | 조직·부서 · 모집인원 |
| 롯데그룹 | 조직·부서 · 직군 · 고용형태 · 경력 구분 · 근무지 · 모집인원 · 주요 업무 · 우대 조건 |
| 두산 | 조직·부서 · 고용형태 · 경력 구분 · 우대 조건 |
| 네이버 | 조직·부서 · 근무지 · 모집인원 · 주요 업무 · 필수 조건 · 우대 조건 · 전형 절차 · 기타 |
| 카카오 | 조직·부서 · 경력 구분 · 우대 조건 · 기타 · 모집 시작일 |
| 토스 | 본문 원문 · 제목 · 마감일 말고 전부 |
| 우아한형제들 | 모집 기업 · 조직·부서 · 근무지 · 모집인원 · 주요 업무 · 필수 조건 · 우대 조건 · 전형 절차 · 기타 |

토스는 상세가 공고마다 마크업이 다르고(`.claude/site-recipes/toss-im.md`) 본문이 한 덩어리다.
받은 픽스처가 집중채용 랜딩 한 건이라 그 한 건으로 넓혀 말하지 않는다 — 나뉜 값을 준다고
세지 않았다.


## 하지 않는 것

- 사이트별 매핑 재작성. Push 2 다
- 비우고 재수집. Push 3 다
- LLM 분류. 이 작업은 토큰을 쓰지 않는다
