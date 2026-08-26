# Tasks: 본문 나누기 - Push 2

> PRD: `.claude/tasks/todo/prd-split-body.md`
> Push 범위: 열한 사이트 매핑을 새 칸으로 다시 쓴다
> 상태: 대기

## 배경

Push 1 이 칸을 확정하고 스키마를 만들었다. 이 Push 는 사이트마다 **응답의 어느 필드가 어느
칸인지** 다시 적는다.

## 가장 중요한 규칙

**응답에 별도 필드로 있는 값은 최대한 매핑한다. 다만 뜻이 다른 칸에는 넣지 않는다.**

기준이 2026-08-26 에 넓어졌다. 처음에는 "응답에 그 필드가 실제로 있을 때만 매핑하고 없으면
비운다" 였는데, PRD 가 **매핑하지 않은 응답 필드는 저장하지 않기로** 정해 둔 것과 겹쳐 놓고
보면 그 기준이 너무 좁다 — **지금 안 매핑한 값은 영영 사라진다.** 나중에 칸을 늘려도 그때까지
마감돼 내려간 공고는 그 값을 다시 얻지 못한다.

지금 버그는 과잉 매핑이 아니라 **잘못된 칸** 이었다. 한화에 부서 개념이 없는데 근무지
(`ruWorkpl`)를 `department` 에 넣었다. 칸이 여섯뿐이라 억지로 끼워 넣은 것이고, 이제
`work_location` 칸이 있으니 거기로는 반드시 매핑한다.

**갈 곳 없는 필드는 `etc_info` 로 모은다.** 한화 `ruInqr`(문의처), LG `submitMethodInfo`
(지원방법)처럼 열여섯 칸 어디에도 안 맞는 값이 있다. 버리지 말고 기타 칸에 모은다. 여러 값을
모을 때는 이미 있는 방식(경로 배열)을 쓴다.

**본문 덩어리 안의 문단은 잘라내지 않는다.** SK 의 `■ 우대사항` 처럼 `body` 안에 섞인 것은
안 잘라도 `body` 에 남아 사라지지 않는다. 글자를 잘라 채우는 규칙은 사이트가 문구를 바꾸면
조용히 깨진다. **응답의 별도 필드는 최대한, 덩어리 안의 문단은 그대로** 다.

## 새 다섯 사이트는 이름을 고쳐 등록한다

지금 크롤러 이름이 URL 이다 (`career.doosan.com`). **크롤러 이름이 곧 상위 기업 칸의 값이므로**
사람이 읽는 이름으로 바꾼다.

| 지금 이름 | 바꿀 이름 |
|---|---|
| `career.doosan.com` | 두산 |
| `recruit.navercorp.com` | 네이버 |
| `toss.im` | 토스 |
| `careers.kakao.com` | 카카오 |
| `career.woowayouths.com` | 우아한형제들 |

이름을 바꾸는 길이 지금 없다. 라우트를 더하거나 다시 등록한다 — **다시 등록하면 판정이 다시
돌아 브라우저와 LLM 을 쓰므로**, 이름만 바꾸는 쪽이 싸다.

기존 여섯 곳(LG·한화·삼성·SK·현대·롯데)은 이름이 이미 사람이 읽는 이름이다.

## 관련 파일

- `app/selector/api_schema.py` - API 설정 형식
- `app/crawler/api_source.py` - 응답에서 값을 뽑는다. `*` 로 배열을 훑고 경로 배열로 여러 자리를 모은다
- `app/selector/schema.py` - HTML 셀렉터 (SK·롯데·두산·네이버)
- `app/api/crawlers.py` - 크롤러 등록·수정
- `.claude/site-recipes/` - 열한 사이트 기록
- `tests/fixtures/` - Push 1 이 열한 사이트 응답을 다 넣어 두었다

## 선행 조건

- Push 1 완료. 칸이 확정되고 스키마가 있어야 한다

## 작업

- [ ] 2.0 열한 사이트 매핑을 다시 쓴다
    - [x] 2.1 크롤러 이름을 바꾸는 길을 만든다
        - `PUT /api/crawlers/{id}/name` 을 더했다. `update_company` 와 같은 모양이고, 빈
          이름은 422(`empty_name`)로 거절한다 — `crawlers.name` 은 NOT NULL 이고 목록에서
          그 행을 알아보는 유일한 값이라 지울 수 있는 `default_company` 와 다르다
        - `PUT /ui/crawlers/{id}/name` 과 크롤러 표의 이름 칸에 입력 + 저장 버튼
        - 이미 만들어진 워크플로우 이름은 따라오지 않는다. 워크플로우는 만들 때 이름을 복사해
          자기 행에 들고 있다 (`app/api/workflows.py`)
        - **이름은 `company` 칸의 값이 아니다.** 정규화가 회사명을 못 뽑았을 때 쓰는 것은
          `crawlers.default_company` 다 (`app/normalize/engine.py` 의 `resolve_company`).
          이름은 화면과 새 워크플로우의 이름에 쓰인다
        - [x] 2.1.V 검증: `tests/test_crawler_rename.py` 8개 통과. 포트 8000 인스턴스의
          `/ui/crawlers` 에 이름 폼이 열한 행 다 있고 `/openapi.json` 에 라우트가 있다
    - [x] 2.2 새 다섯 사이트의 이름을 고친다
        - 포트 8000 인스턴스에 `PUT /api/crawlers/{id}/name` 을 다섯 번 보냈다. 다시 등록하지
          않았고 브라우저도 모델도 쓰지 않았다
        - 29 우아한형제들 · 30 카카오 · 31 두산 · 32 네이버 · 33 토스
        - [x] 2.2.V 검증: `/data/jobs.db` 의 `crawlers` 열한 행이 전부 사람이 읽는 이름이다
    - [x] 2.3 API 사이트의 매핑을 다시 쓴다
        - LG·한화·삼성·현대(상세도 API), 카카오·우아한형제들(목록만 API)
        - **한화 `department` 에서 `ruWorkpl` 을 뺐다.** 근무지는 `work_location` 으로 간다.
          한화에 부서 개념이 없어 `department` 는 비운다
        - Push 1 의 표를 따르되 넓어진 기준으로 더 담았다 — 현대 전형 절차는 `procStep1Nm`
          하나가 아니라 일곱 자리를 모으고, 삼성 자격요건은 공고 전체(`result.qlfctKr`)와
          직무별(`items.*.qlfctKr`) 둘 다 읽는다. 삼성 조직 소개(`introKr`)는 본문에 넣었다
        - 필수 조건과 우대 조건을 갈랐다. 현대 `prefReq` 와 삼성 `favorKr` 이 `requirements`
          에 함께 들어가 있었다 — 사이트가 이미 나눠서 주는 것을 도로 합치고 있었다
        - 갈 칸이 없는 값은 기타로 모았다 — 한화 `rtRctPrd`·`ruInqr`, LG `submitMethodInfo`·
          `recruitTypeName`, 현대 `posCodeNm1`·`jdRecuCateNm`·`hashTag`, 삼성 `processKr`·
          `docInfoKr`·`attachmentKr`·`memoKr`·첨부 파일명·연락처
        - 카카오는 상세 문서의 본문이 한 덩어리라 갈라낼 수 없고 같은 값이 목록 API 에 항목마다
          별도 필드로 있다. 목록 `fields` 가 상세 칸 이름을 받게 하고 `ListItem.extra` 로
          나른다. **상세가 이기고 목록은 상세가 비었을 때만 쓴다** (`_record`)
        - 매핑을 고칠 길이 없어 `PUT /api/crawlers/{id}/api-config` 를 더했다.
          `update_selectors` 와 같은 모양이고 저장 전에 `validate_api_config` 를 지난다
        - 설정은 `seeds/site-configs-20260826.json` 에 열한 곳을 다 적었다. 옛
          `site-configs-20260825.json` 은 이 파일로 대체됐다
        - [x] 2.3.V 검증: `tests/test_split_body_mapping.py` 55개 통과. 사이트마다 칸별로
          값이 나오는지와 **주지 않는 칸이 실제로 비는지** 를 둘 다 단언한다.
          `tests/test_site_configs.py` 15개, `tests/test_list_carries_detail_fields.py` 6개,
          `tests/test_api_config_update.py` 5개 통과
    - [x] 2.4 HTML 사이트의 셀렉터를 다시 쓴다
        - SK·롯데·두산·네이버, 그리고 카카오·우아한형제들·토스의 상세
        - **덩어리인 칸은 비운다.** 이름표가 붙은 요소만 칸으로 보내고 나머지는 본문에 남는다.
          본문 안에 남는 값은 사라지지 않으므로 글자를 잘라 채우지 않았다
        - 자리(nth-child)로 잡던 것을 이름표로 바꾸면서 세 곳의 잘못된 칸이 드러났다
            - SK `department` 가 직무(`IT - IT 기획`)를 담고 있었다 → `job_category`
            - 네이버 `department` 가 모집 분야(`Tech`)를, `company` 가 모집 부서(`NAVER`)를
              담고 있었다 → 분야는 `job_category`, `NAVER` 는 계열사라 `company`
            - 두산 `deadline` 이 `tbody > tr:nth-child(4) > td` 라 `지원자 개별일정` 을
              마감일로 읽고 있었다 → `th:-soup-contains("채용공고") + td`
        - 우아한형제들 `deadline` 이 `.flag-type` 전체를 잡아 `기간제 영입 종료시` 로
          들어오고 있었다. 고용형태와 마감일을 span 두 개로 갈랐다
        - 토스 `body` 가 `.p-container__inner` 라 상단 내비게이션을 먼저 잡고 있었다.
          `:not(.p-navbar__inner-container)` 를 붙였다
        - 두산 `body` 를 `div.content` 로 넓혔다. `div.view-list-wrap` 은 dt/dd 블록만이라
          접수방법·문의처·전형 일정이 통째로 사라진다. 끝에 이전글/다음글이 딸려 온다
        - HTML 상세는 칸 하나에 셀렉터 하나다(`field_text` 가 첫 매칭만 읽는다). API 처럼
          여러 자리를 모을 수 없어, SK 마감 시간(`23:59`)처럼 본문 밖에 있는 값 몇 개는
          어느 칸에도 안 들어간다 — 레시피에 적었다
        - [x] 2.4.V 검증: 2.3.V 와 같은 파일이 HTML 사이트도 함께 본다
    - [ ] 2.6 새 칸도 손보정할 수 있게 한다
        - `job_field_overrides.field_name` 의 CHECK 가 옛 여섯 칸에 묶여 있어 **새 칸 열 개는
          검수 화면에서 고칠 수 없다.** 자동으로 뽑은 값이 틀렸을 때 사람이 고칠 길이 없다
        - 그 컬럼이 `UNIQUE (raw_job_id, field_name)` 자동 인덱스에 걸려 있어 0009·0010 이 쓴
          방법(컬럼 추가 → 값 이동 → 옛 컬럼 삭제)이 통하지 않는다. SQLite 는 인덱스가 걸린
          컬럼을 지우지 못한다
        - **표를 다시 만든다.** 2026-08-26 확인 결과 이 표는 **0행**이라 옮길 데이터가 없다.
          마이그레이션 0012 로 새 CHECK 를 단 표를 만들고 인덱스를 다시 건다
        - 되돌리는 법을 파일 주석에 적는다
        - [ ] 2.6.V 검증: 마이그레이션 적용·역적용. 적용 뒤 새 칸 하나를 화면에서 고쳐 저장하고
              재정규화해도 그 값이 살아남는지 확인 (보정은 규칙 다음에 덧씌워진다)

    - [ ] 2.5 레시피에 매핑을 적는다
        - `.claude/site-recipes/` 열한 파일에 칸별 필드를 적는다
        - **문서에 적는 필드명은 설정에서 복사한다.** 기억으로 다시 쓰지 않는다
        - [ ] 2.5.V 검증: 문서의 필드명과 DB 설정값을 대조

## 하지 않는 것

- 비우고 재수집. Push 3 다
- LLM 분류
