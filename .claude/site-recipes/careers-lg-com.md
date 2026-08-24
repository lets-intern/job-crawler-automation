# LG (careers.lg.com)

- 리스트 URL: https://careers.lg.com/apply
- 상세 URL 패턴: `/apply/detail?id=<번호>`. 번호는 목록 API 의 `jobNoticeId` 다
- 수집 방식: 목록·상세 둘 다 `api` (2026-08-24 전환). 브라우저를 띄우지 않는다
- 페이지네이션: 없다. 목록 API 한 번에 전부 들어온다 (2026-08-25 확인, 88건)
- 날짜 포맷: `2026.08.30 23:00`. 저장하는 것은 마감 일시다. 등록일은 목록에도 상세에도 없다
- robots.txt: 목록 페이지와 API 가 **다른 호스트**다. `api.careers.lg.com` 의 robots 는
  `User-agent: *` 에 `Allow: /` 이고, 공용 fetch 클라이언트가 호스트별로 robots 와 딜레이를
  따로 잡으므로 그대로 통과한다
- 권장 주기: 30분으로 등록돼 있다 (workflow 5)

## 목록도 상세도 JSON API 로 온다

브라우저 없이 `POST` 로 200 이 온다. 실제로 쓰는 설정은 DB(`crawlers.api_config_json`)가
진실이고, 같은 값을 `tests/fixtures/lg-api-config-20260824.json` 에 두어 시험이 쓴다.

```
POST https://api.careers.lg.com/rmk/job/retrieveJobNoticesList
  body {"lnbSearch":"","hashTagText":"","recDate":"POST_START_DATE","order":"DESC",
        "careerList":[],"companyCodeList":[],"desireLocList":[],"jobGroupList":[]}
  -> data.jobNoticeList 83건. 항목마다 jobNoticeId / jobNoticeName / companyName /
     recEndDateTime

POST https://api.careers.lg.com/rmk/job/retrieveJobNoticesDetail
  body {"jobNoticeId": 1002029}
  -> data.jobNoticesDetail.jobNoticesDetail 에 jobNoticeName, companyName, recEndDate
     data.jobNoticesDetail.recList[0] 에 detailContext, requiredItem, orgName
```

`jobNoticeId` 는 **숫자로 보내야 한다.** 문자열로 보내면 응답이 비어서 돌아온다
(`app/crawler/api_source.py` 의 `_with_id`).

`raw_jobs.source_url` 은 `link_template` 이 만든다 —
`https://careers.lg.com/apply/detail?id={id}`. 공고마다 다른 주소이고, 소비 측이 그대로 쓸 수
있는 사람용 주소다.

## 상세 본문은 HTML 조각이다

`detailContext`, `requiredItem`, `preferredItem`, `majorCodeName` 은 인라인 스타일이 잔뜩
붙은 HTML 이다. 수집은 그대로 적재한다 — 텍스트로 펴는 것은 정규화의 일이다 (`CLAUDE.md`).

펴는 것은 `html_text` 규칙이다. `body` 와 `requirements` 에 우선순위 5 로 걸려 있다
(`seeds/normalization-rules.json`). 2026-08-24 재정규화에서 본문 3,397자가 850자로,
자격요건 970자가 24자로 줄었다. 규칙을 지우면 태그가 그대로 소비 측으로 나간다.

여섯 사이트 중 값에 마크업이 섞이는 것은 LG 뿐이다. 나머지는 파서가 HTML 에서 텍스트를 뽑아
적재하므로 `raw_jobs` 단계에서 이미 평문이다.

| 워크플로우 | raw_jobs 건수 | 값에 태그·엔티티가 있는 건 |
|---|---|---|
| 롯데그룹 | 6 | 0 |
| 삼성 | 3 | 0 |
| SK | 20 | 0 |
| LG | 167 | 77 (`body` 76, `requirements` 74) |
| 현대자동차 | 20 | 0 |

`preferredItem` 과 `majorCodeName` 은 아직 어느 필드에도 매핑되어 있지 않다
(`crawlers.api_config_json`). 매핑하는 날에는 그 필드에도 같은 규칙을 걸어야 한다.

## 렌더된 HTML 로는 상세로 갈 길이 없었다 (2026-08-24 이전)

항목 안에 `a` 태그가 0개이고 공고 번호도 없었다. `data-` 속성도, `id` 도, JSON 블록도 없다.

| 무엇 | 렌더된 목록 HTML 안의 개수 |
|---|---|
| `href=` | 8 (전부 상단 네비게이션. 항목 안에는 0) |
| `apply/detail` 문자열 | 0 |
| 6자리 이상 숫자 id | 0 |

그래서 `list.link` 와 `list.link_template` 이 둘 다 비어 있었고, 상세를 아예 열지 않았다.
`raw_jobs.source_url` 에는 공고마다 목록 URL 이 들어갔다. **셀렉터로 고칠 수 있는 문제가
아니었다** — 항목을 클릭하면 JS 가 이동시키는 구조라 셀렉터가 잡을 것이 없었다.

API 로 옮기면서 이 문제가 통째로 사라졌다. id 가 응답에 있기 때문이다.

## 저장된 셀렉터는 쓰이지 않는다

목록·상세가 둘 다 `api` 라 `selectors_json` 은 실행에서 읽히지 않는다. 값은 남겨 두었다 —
API 가 막히면 렌더 경로로 되돌릴 때 출발점이 된다.

그 셀렉터는 emotion/MUI 의 자동 생성 클래스(`css-13xukit` 같은 해시)에 기대고 있어서
**스타일 배포 한 번에 전부 깨진다.** 되돌려 쓸 일이 생기면 AI 수정으로 지금 해시를 다시 찾는
것이 가장 빠르다 (2026-08-24 에 힌트 없이도 83건 매칭을 찾아냈다).

## 이력

| 날짜 | 일 | 원인 | 조치 |
|---|---|---|---|
| 2026-08-23 | `list.link` 실패 상태로 발견 | 항목 안에 `a` 도 id 도 없다 | 원인 확인. 셀렉터로는 풀리지 않는다 |
| 2026-08-24 | 힌트를 실어 AI 수정 2회 | 같음 | 모델이 빈 문자열로 답했다. 그대로 둔다 |
| 2026-08-24 | 실행 결과에서 `detail.body` 가 `실패` 로 표시됨 | 목록 전용인데 상세 필드를 실패로 판정했다 | 화면이 `해당 없음` 으로 적도록 고쳤다 (`app/api/ui_tests.py`) |
| 2026-08-24 | `list.date` 를 순서 기반에서 관계 기반으로 교체 | `nth-of-type` 이 형제 네 개 중 하나를 순서로 골랐다 | 힌트를 준 AI 수정으로 교체, 저장 후 재실행에서 3/3 확인 |
| 2026-08-24 | 목록·상세를 `api` 로 전환 | 목록 API 에 `jobNoticeId` 가 있다 | 수동 실행 1회(run 152)에서 83건 적재. `source_url` 83개가 전부 다르고 회사명에 계열사명이 들어왔다 |
| 2026-08-24 | 소비 측에 태그째 나가는 값 발견 | API 가 본문을 HTML 조각으로 준다 | `html_text` 규칙을 `body`·`requirements` 에 걸었다. 사본 재정규화에서 태그 남은 행 77건 -> 0건 |

## 2026-08-25: 본문을 모집 부문 전체에서 모은다

`data.jobNoticesDetail.recList` 는 모집 부문마다 한 칸이다. 2026-08-25 에 받은 상세
(`tests/fixtures/lg-detail-20260825.json`)는 6칸이었고, 그때까지의 설정은 첫 칸만 읽고 있었다.
나머지 다섯 부문의 본문·자격요건·조직명이 수집 단계에서 사라지고 있었다는 뜻이다.

경로에 `*` 를 써서 배열 전체를 모은다. 설정은 `seeds/site-configs-20260825.json` 의 LG 항목이고
DB 가 진실이다. 이미 적재된 행은 다시 쓰지 않는다 — `raw_jobs` 는 append-only 라 새 공고부터
온전한 본문이 들어온다.

목록 건수는 88건이다 (`data.listCount`). 2026-08-24 의 83건에서 늘었고 페이지네이션은 여전히 없다.

`list.date_is_deadline` 을 참으로 적었다. 목록의 `recEndDateTime` 이 그 공고의 마감일이므로,
마감이 지난 공고는 상세를 열지 않고 건너뛴다. 2026-08-25 실행(run 253)에서 88건 중 1건이
마감으로 걸렀고 나머지는 이미 아는 공고라 상세 요청이 한 번도 나가지 않았다.
