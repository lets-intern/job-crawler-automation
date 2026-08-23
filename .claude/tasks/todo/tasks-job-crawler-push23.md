# Tasks: job-crawler - Push 23

> PRD: `.claude/tasks/todo/prd-job-crawler.md`
> Push 범위: 수집 방식을 목록·상세 각각 `static` / `api` / `playwright` 로 고를 수 있게 한다
> 상태: 완료 (2026-08-24)

## 배경

LG 는 렌더된 목록 HTML 에 공고 id 가 0개라 상세로 갈 길이 없었다
(`.claude/site-recipes/careers-lg-com.md`). 2026-08-24 에 목록이 JSON API 로 채워지는 것을
확인했고, 그 API 는 브라우저 없이 `POST` 로 200 을 준다.

```
POST https://api.careers.lg.com/rmk/job/retrieveJobNoticesList
  body {"lnbSearch":"","hashTagText":"","recDate":"POST_START_DATE","order":"DESC",
        "careerList":[],"companyCodeList":[],"desireLocList":[],"jobGroupList":[]}
  -> data.jobNoticeList 83건, 각 항목에 jobNoticeId / jobNoticeName / companyName / recEndDateTime

POST https://api.careers.lg.com/rmk/job/retrieveJobNoticesDetail
  body {"jobNoticeId":1002029}
  -> data.jobNoticesDetail.jobNoticesDetail 에 recStartDate, qualForAppInfo 등
     data.jobNoticesDetail.recList[] 에 detailContext, requiredItem, preferredItem, locationName
```

`api.careers.lg.com` 은 별도 호스트다. robots 는 `User-agent: *` 에 `Allow: /` 이고, 공용
fetch 클라이언트가 호스트별로 robots 와 딜레이를 따로 잡으므로 그대로 통과한다.

## 관련 파일

- `app/crawler/fetcher.py` - 유일한 외부 요청 경로. `FetchPolicy` 로 렌더 경로에 정책을 넘긴다
- `app/crawler/playwright.py` - `open_source(render_mode, fetcher)` 가 유일한 갈림길
- `app/crawler/runner.py` - `_crawl` 이 목록을 얻고 `_collect` 가 상세로 간다
- `app/crawler/parser.py` - HTML 에서 `ListItem` 을 만든다
- `migrations/` - 0007 까지 있다

## 선행 조건

- Push 22 완료 (완료)
- 결정 완료: 전달된 행이 0건이라 `source_url` 이 바뀌어 기존 LG 공고가 다시 쌓여도 소비 측에
  중복이 가지 않는다. 마이그레이션으로 기존 행을 손대지 않는다

## 작업

- [x] 23.0 목록·상세 수집 방식을 나눠 저장한다
    - [x] 23.1 마이그레이션 0008: `crawlers` 에 `list_mode`, `detail_mode`, `api_config_json` 추가
        - 기존 `render_mode` 값을 두 열에 그대로 복사한 뒤 `render_mode` 를 없앤다.
          두 곳이 같은 것을 말하면 곧 어긋난다
        - 값은 `static` / `api` / `playwright` 셋뿐이고 `CHECK` 로 막는다
        - 되돌리는 법을 마이그레이션 파일 주석에 적는다
        - [x] 23.1.V 검증: 마이그레이션 적용·역적용 확인. 적용 후 크롤러 6개의 두 열이 이전
              `render_mode` 와 같은지 확인
              (임시 DB 적용·역적용 pytest 3건 통과. 운영 DB 는 백업 후 적용했고 크롤러 6개가
              12:static, 13~17:playwright 로 이전 `render_mode` 와 같다. 커밋 ac3a84f)
    - [x] 23.2 `api_config_json` 의 형식을 정하고 검증한다
        - 목록: `url`, `method`, `body`, `items_path`, `fields`(공고 필드 -> JSON 키), `id_field`
        - 상세: `url`, `method`, `body`(항목 id 를 `{id}` 로 끼움), `fields`(점 표기 경로)
        - `link_template` 으로 사람이 볼 상세 주소를 만든다. `raw_jobs.source_url` 에 이 값이 들어간다
        - Pydantic 으로 형식을 강제한다. 셀렉터 스키마(`app/selector/schema.py`)와 같은 자리에 둔다
        - [x] 23.2.V 검증: 픽스처 기반 pytest — 형식에 맞는 설정은 통과하고, `items_path` 가
              없거나 `fields` 가 비면 이름을 대며 실패하는지
              (`tests/test_api_config_schema.py` 17건 통과. 설정 픽스처는
              `tests/fixtures/lg-api-config-20260824.json`. 커밋 dc112e1)
    - [x] 23.3 API 로 목록·상세를 가져오는 경로를 만든다
        - 공용 fetch 클라이언트를 통해 나간다. `httpx` 를 직접 부르지 않는다
          (`.claude/rules/crawling.md`). `POST` 와 본문을 보낼 수 있게 `Fetcher` 를 넓힌다
        - 응답이 JSON 이 아니거나 `items_path` 가 배열이 아니면 전송 실패가 아니라
          **파싱 실패**로 분류한다. 셋을 구분하라는 규칙이 그대로 적용된다
        - 매칭 0건은 성공이 아니라 실패다
        - [x] 23.3.V 검증: 저장한 LG 응답 픽스처로 pytest — 83건이 나오고 필드가 채워지는지.
              실서버를 때리지 않는다
              (`tests/test_api_source.py` 16건 통과. 목록 83건, 링크 83개가 전부 다르고,
              회사명에 계열사명이 들어간다. 실패 분류 셋도 각각 확인. 커밋 5c867f0)
    - [x] 23.4 실행이 모드에 따라 갈리게 한다
        - `open_source` 자리에서 목록·상세를 각각 판단한다. 섞어 쓸 수 있어야 한다
          (목록은 `api`, 상세는 `playwright` 같은 조합)
        - `playwright` 는 목록이나 상세 중 실제로 필요한 쪽에서만 브라우저를 띄운다.
          목록이 `api` 면 브라우저를 띄우지 않는다
        - [x] 23.4.V 검증: 픽스처로 조합 네 가지(static/api, api/api, api/playwright,
              playwright/playwright)가 각각 의도한 경로를 타는지
              (`tests/test_collect_modes.py` 7건 통과. 목록이 `api` 인 두 조합에서 렌더러가
              한 번도 만들어지지 않았고, 양쪽이 `playwright` 인 조합은 브라우저 하나를 나눠
              쓰고 닫혔다. 커밋 27fcc15)
    - [x] 23.5 LG 크롤러를 `api` 로 손수 설정하고 한 번 돌린다
        - 위 배경의 endpoint·body·경로를 그대로 쓴다
        - 상세 본문은 `recList[]` 의 `detailContext` 다. HTML 조각이라 텍스트로 펴는 것은
          정규화의 일이지 수집의 일이 아니다 (`CLAUDE.md`)
        - [x] 23.5.V 검증: 실사이트 1회 실행. `crawl_runs` 행과 카운트 확인, 새로 들어온 행의
              `source_url` 이 공고마다 다른지, `company` 에 계열사명이 들어갔는지
              (`crawl_runs` 152: status=success, success 83 / new 83 / fail 0.
              새 `raw_jobs` 83행의 `source_url` 이 83개 전부 다르다
              (`.../apply/detail?id=1002029` 같은 모양). `company` 는 LG CNS 25건,
              비즈테크아이 20건, LG유플러스 7건 등 계열사 14곳으로 갈렸다.
              정규화도 83건 전부 통과했고 `company_source` 는 `parsed` 다)

## 하지 않는 것

- 자동 판정. Push 24 다
- 화면에 모드를 보여주는 것과 AI 수정. Push 25 다
- 기존 LG 행 정리. 전달 0건이라 그냥 둔다
