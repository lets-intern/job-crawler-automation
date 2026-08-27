# Tasks: job-crawler - Push 7

> PRD: `.claude/tasks/done/job-crawler/prd-job-crawler.md`
> Push 범위: 회사명 해결 — 운영자 입력값과 파싱값을 따로 저장하고 정규화 단계에서 하나로 정한다
> 상태: 진행 중

## 왜 필요한가

`normalized_jobs.company` 가 지금 항상 NULL 이다. 셀렉터 스키마에 `company` 가 없어 아무도 뽑지
않고, 정규화 규칙만으로는 없는 값을 만들 수 없다. 그런데 `.claude/docs/api-contract.md` 의 응답에는
`company` 가 있으므로 Push 8 이 빈 회사명을 내보내게 된다.

"사이트 하나 = 회사 하나" 로 두면 안 된다. 삼성 채용 사이트 하나에 삼성SDS, 삼성전기처럼
계열사 공고가 섞여 들어온다. 공고마다 다른 값이 필요하다.

## 결정된 구조

**두 출처를 따로 저장하고, 합치는 것은 정규화 단계에서만 한다.**

| 출처 | 저장 위치 | 단위 |
|---|---|---|
| 운영자 입력 | `crawlers.default_company` | 크롤러 하나 |
| 파싱값 | `raw_jobs.raw_data_json` 의 `company` 필드 | 공고 하나 |
| 확정값 | `normalized_jobs.company` | 공고 하나 |

파싱값이 있으면 파싱값이 이긴다. 공고 단위가 사이트 단위보다 구체적이다. 계열사가 섞인
사이트는 파싱값이 구분하고, 회사명이 페이지에 없는 사이트는 운영자 입력이 받는다.

이 구조가 되는 이유는 운영자 입력이 추출 결과가 아니기 때문이다. `raw_jobs` 는 추출한 것만
담는 append-only 테이블이므로 운영자가 타이핑한 값이 거기 들어가면 안 된다
(`.claude/rules/data-safety.md`). 반대로 파싱값은 다른 필드와 똑같은 추출 결과라
`raw_data_json` 에 그대로 들어간다.

부수 효과 하나가 이 분리의 값이다. 운영자가 회사명을 잘못 넣었으면 `default_company` 를 고치고
재정규화하면 끝이다. `raw_jobs` 는 건드릴 일이 없다.

## 관련 파일

- `migrations/0004_company.sql` - `crawlers.default_company`, `normalized_jobs.company_source`
- `app/selector/schema.py` - `company` 를 선택 필드로 추가
- `app/normalize/engine.py` - 회사명 해결
- `app/api/crawlers.py` - 등록·수정 시 `default_company` 입력
- `app/templates/` - 등록 화면의 회사명 입력, 조회 화면의 회사명 표시

## 선행 조건

- Push 5 완료 (정규화 엔진이 있어야 해결 단계를 붙인다)
- Push 6 완료 (7.5 가 기존 화면에 붙는다). 7.1~7.4 는 Push 6 없이도 진행할 수 있다
- 이 Push 가 끝나야 Push 8 의 제공 API 가 의미 있는 `company` 를 내보낸다

## 작업

- [x] 7.0 회사명 해결 (Push 범위)

    - [x] 7.1 스키마와 운영자 입력
        - `migrations/0004_company.sql`. `crawlers.default_company` (NULL 허용),
          `normalized_jobs.company_source` (`parsed` / `operator`, NULL 허용)
        - 기존 마이그레이션 파일을 편집하지 않는다 (`.claude/rules/data-safety.md`)
        - 등록·수정 API 에서 `default_company` 를 받는다. 필수가 아니다
        - `.claude/docs/data-model.md` 의 해당 표를 같은 커밋에서 고친다
        - [x] 7.1.V 검증: 마이그레이션 적용·역적용 확인. 기존 행이 NULL 로 남고 역적용 후 두 컬럼이 사라지는지,
          `default_company` 를 넣은 크롤러가 저장·조회되는지 확인

    - [x] 7.2 셀렉터 스키마의 company 선택 필드
        - `list` 와 `detail` 양쪽에 `company` 를 **선택 필드**로 더한다. 없어도 검증을 통과해야 한다
        - 이미 저장된 셀렉터 JSON 이 깨지지 않아야 한다. 기존 필드는 그대로 필수다
        - 생성 프롬프트에도 넣되, 페이지에 회사명이 없으면 빈 값을 내도록 한다.
          없는 것을 지어내면 잘못된 회사명이 공고마다 붙는다 (`.claude/rules/llm.md`)
        - [x] 7.2.V 검증: 픽스처 기반 pytest 작성 및 통과 — `company` 없는 기존 셀렉터 JSON 이 그대로 통과하고,
          `company` 있는 JSON 도 통과하며, 파싱 시 `raw_data_json` 에 값이 들어가는지 단언

    - [x] 7.3 정규화 단계의 회사명 해결
        - `raw_data_json.company` 가 비어 있지 않으면 그 값을 쓰고 `company_source='parsed'`
        - 비어 있으면 `crawlers.default_company` 를 쓰고 `company_source='operator'`
        - 둘 다 없으면 `company` 와 `company_source` 모두 NULL. 빈 문자열로 채우지 않는다
        - 확정된 값에는 다른 필드와 똑같이 `normalization_rules` 가 적용된다.
          `mapping` 으로 "삼성전기(주)" 를 "삼성전기" 로 맞추는 것이 이 규칙의 일이다
        - [x] 7.3.V 검증: 픽스처 기반 pytest 작성 및 통과 — 파싱값 우선, 파싱값 없을 때 운영자값,
          둘 다 없을 때 NULL, 그리고 계열사 두 건이 섞인 픽스처에서 서로 다른 회사명이 나오는지 단언

    - [x] 7.4 재정규화가 회사명 변경을 반영
        - `default_company` 를 고치고 재정규화하면 `company_source='operator'` 인 행만 바뀐다
        - `parsed` 인 행은 운영자값을 고쳐도 바뀌지 않는다
        - `raw_jobs` 와 `delivered_at` 은 건드리지 않는다
        - [x] 7.4.V 검증: 픽스처 기반 pytest 작성 및 통과 — 운영자값 변경 후 재정규화에서 `operator` 행만 갱신되고
          `parsed` 행과 `raw_jobs` 해시와 `delivered_at` 이 불변인지 단언

    - [x] 7.5 화면 반영
        - 등록 화면에 회사명 입력란(선택). 조회 화면 테이블에 회사명 열과 회사명 필터
        - 회사명이 어디서 왔는지 `company_source` 를 단어로 표시한다 (`파싱` / `입력`)
        - CSS 를 만들지 않는다. Push 6 과 같은 조건이다
        - [x] 7.5.V 검증: 로컬에서 화면을 열고 회사명을 입력해 저장한 뒤 조회 화면에 반영되는지,
          회사명 필터가 테이블 영역만 갱신하는지 확인
