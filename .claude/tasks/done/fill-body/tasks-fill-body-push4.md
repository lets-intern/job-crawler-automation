# Tasks: 본문 채우기 - Push 4

> PRD: `.claude/tasks/done/fill-body/prd-fill-body.md`
> Push 범위: 여섯 사이트를 목록 API 로 돌리고 빠진 값을 채운다 (사이트 설정)
> 상태: 완료 (2026-08-25)

## 배경 (PRD 를 안 봐도 되도록)

2026-08-24~25 에 여섯 사이트를 전부 측정했다. **매 실행에 브라우저가 필요한 사이트는 없다.**
아래 요청은 모두 `curl` 로 200 을 받은 것이다.

### 목록

| 사이트 | 요청 |
|---|---|
| LG | `POST https://api.careers.lg.com/rmk/job/retrieveJobNoticesList` |
| 한화 | `POST https://hwadm.hanwhain.com/new-backend/portal/api/rcRecruit/search-rcrt` |
| 삼성 | `POST https://www.samsungcareers.com/hr/list.data` |
| SK | `POST https://www.skcareers.com/Recruit/GetRecruitList` |
| 현대 | `GET https://talent.hyundai.com/api/rec/AP-HM-FO-02730?hgrCd=1&lang=ko&...` |
| 롯데 | 정적 HTML 로 이미 잡힌다 (`https://recruit.lotte.co.kr/apply/announcement`) |

본문 형식은 이렇다.

```
LG   content-type: application/json
     {"lnbSearch":"","hashTagText":"","recDate":"POST_START_DATE","order":"DESC",
      "careerList":[],"companyCodeList":[],"desireLocList":[],"jobGroupList":[]}
     -> data.jobNoticeList 83건. jobNoticeId / jobNoticeName / companyName / recEndDateTime

한화  content-type: application/json
     {"langCd":"ko","searchText":"","sdSeqList":null,"rtNrcrtYn":"","rtCarrYn":""}
     -> data.list 20건. rtSeq / rtNm / sdNm / rtAcptStrtDttm / rtAcptEndDttm

삼성  content-type: application/x-www-form-urlencoded;charset=utf-8
     currentPageNo=1&intNo=0&strVal=&strTxt=&strKey=&strCompany=&strType=&strOrderBy=&strEntity=
     -> HTML 조각 17,935B. 항목의 a[data-value="22,878"] 이 공고 번호다 (쉼표를 뺀다)
     파라미터가 하나라도 빠지면 {"code":500} 이 온다. 여덟 개를 다 보낸다

SK   content-type: application/x-www-form-urlencoded
     sort=2&searchText=&corpCode=&jobRole=0&recruitType=&workingType=&workingRegion=
     -> JSON. totalCount 104, list 104건.
        jobNoticeNo / noticeID("R261752") / title / corpName / start / end
        end 형식은 "August 25, 2026(Tue)" 다 (영어 월 이름)
```

### 상세

| 사이트 | 요청 |
|---|---|
| LG | `POST https://api.careers.lg.com/rmk/job/retrieveJobNoticesDetail` body `{"jobNoticeId":1002029}` |
| 한화 | `POST https://hwadm.hanwhain.com/new-backend/portal/api/rcRecruit/get-rcrt` body `{"rtSeq":19463}` |
| 삼성 | `GET https://www.samsungcareers.com/recruit/detail.data?seqno=22878&strCode=` |
| SK | 상세 HTML 페이지 `https://www.skcareers.com/Recruit/Detail/R261752` |
| 현대 | 상세 HTML 페이지 `https://talent.hyundai.com/apply/applyView.hc?recuYy=2026&recuType=N2&recuCls=296` |
| 롯데 | 상세 HTML 페이지 `https://recruit.lotte.co.kr/apply/announcement/detail/21931885` |

현대의 세 파라미터는 항목의 `data-recuyy`·`data-recutype`·`data-recucls` 다.

### robots

- LG 두 호스트: `User-agent: *` 에 `Allow: /`
- 한화 두 호스트: **robots.txt 가 없다.** 200 을 주지만 내용이 SPA 셸 HTML 이다.
  제한이 명시되지 않은 것이지 넉넉히 다녀도 된다는 뜻이 아니다. 딜레이를 그대로 지킨다
- 나머지는 등록할 때 공용 fetch 클라이언트가 호스트별로 확인한다

## 2026-08-25 추가 측정 — 이미 확인된 것 (다시 재지 마세요)

### 총 건수와 페이지네이션

| 사이트 | 지금 수집 | API 총 건수 | 페이지 |
|---|---|---|---|
| LG | 88 | **88** (`data.listCount`) | 한 번에 전부 |
| 한화 | 미등록 | **68** (`data.totalCount`) | **20건씩 4쪽** |
| 삼성 | 3 | **16** (`divCnt data-max="2"`) | **2쪽 (9 + 7)** |
| SK | 20 | **104** (`totalCount`) | 한 번에 전부 |
| 현대 | 20 | 20 (`data.applyList`) | 확인 못 함 |
| 롯데 | 8 | 8 | 정적 한 장 |

**한화와 삼성은 페이지를 넘겨야 한다.**

한화는 본문에 `page` 를 더한다. `page=0,1,2,3` 에서 각각 20/20/20/8건이고 `hasNext` 가
마지막에 `false` 가 된다. `totalCount` 는 첫 쪽에만 온다.

```
{"langCd":"ko","searchText":"","sdSeqList":null,"rtNrcrtYn":"","rtCarrYn":"","page":0}
```

삼성은 `currentPageNo` 를 올린다. 1쪽 9건, 2쪽 7건. 총 수와 쪽 수는 응답 안의
`<input class="divCnt" data-value="16" data-max="2">` 에 있다.

### 현대 목록 API 는 헤더가 필요하다

헤더 없이 부르면 **400** 이 온다. 이 두 개를 넣으면 200 이고 58,300바이트다.

```
GET https://talent.hyundai.com/api/rec/AP-HM-FO-02730?hgrCd=1&lang=ko&secCode=&jdRecuCate=01&secLoad=Y
  accept: application/json, text/plain, */*
  referer: https://talent.hyundai.com/theme/hall.hc
  x-hkmc-service: HM
  x-hkmc-token: null
```

공고는 `data.applyList` 20건이다. 쿠키는 필요 없다(쿠키 없이 200 을 받았다).
`api/rec/AP-HM-FO-02720` 은 `themaInfo` 만 주므로 목록이 아니다.

**`x-hkmc-service` 같은 사이트 전용 헤더를 API 설정에 담을 수 있어야 한다.**
`app/selector/api_schema.py` 의 `ApiListConfig`·`ApiDetailConfig` 에 헤더 자리가 없으면 더한다.
이것이 4.2 의 실제 작업이다.

### 예상 수집량

여섯 사이트 합계 약 **304건**이다 (지금 233건). 상세 요청이 300번 넘고 호스트별 딜레이가
붙으므로 **한 워크플로우가 30분 안에 끝나는지 확인해야 한다.** SK 104건이 가장 오래 걸린다.

### 응답 픽스처가 이미 받아져 있다

`/private/tmp/claude-501/-Users-a-workspace-job-crawler-automation/8c8655d7-40a5-4f35-ba2c-60ccf81bdc49/scratchpad/fixtures/`
에 여섯 사이트의 목록·상세 응답 16개와 `README.md` 가 있다. 전부 `curl` 로 브라우저 없이 받은
것이다. **`tests/fixtures/` 로 옮겨 쓰고 실사이트 요청은 최종 확인 때만 한다.**

`README.md` 에 요청 형식·필요한 헤더·페이지 넘기는 법·필드 매핑이 정리돼 있다.

### 현대 상세도 API 로 된다

`GET https://talent.hyundai.com/api/rec/AP-HM-FO-02800?hgrCd=1&lang=ko&recuYy=2026&recuType=N2&recuCls=296`
가 200 이고 `data.applyInfo` 에 157개 필드가 **평문으로** 들어 있다. HTML 을 파싱할 이유가 없다.

| 뜻 | 필드 |
|---|---|
| 제목 | `recuNoticeNm` |
| 주요 업무 | `privJdDtl` |
| 필수 조건 | `privMustReq` |
| 우대 조건 | `prefReq` |
| 조직 소개 | `aboutTeamNtc` |
| 기타 | `etc` |

**`/apply/applyView.hc` 상세 HTML 은 쓰지 마라.** 텍스트가 1,098자뿐인 JS 껍데기다.

현대 상세 요청에도 `x-hkmc-service: HM` 헤더가 필요하다. `referer` 는 `applyView.hc` 다.

### 이제 여섯 사이트 모두 브라우저 없이 목록과 상세를 받는다

SK·롯데는 상세가 서버 렌더 HTML 이고(각 4,496자·6,621자) 나머지 넷은 API 다. 어느 쪽이든
`httpx` 로 받는다. **정규 실행에 브라우저가 필요한 사이트는 없다.**

## 관련 파일

- `app/selector/api_schema.py:85` - `ApiListConfig` / `ApiDetailConfig` 형식
- `app/crawler/api_source.py:64` - `fetch_list()`, `fetch_detail()`
- `app/crawler/api_source.py:80` - `build_items()`, `build_detail()`
- `app/api/crawlers.py`, `app/api/ui_crawlers.py` - 크롤러 등록
- `.claude/site-recipes/` - 사이트별 기록. 알아낸 것은 여기에 적는다
- `tests/fixtures/` - `lg-list-api-20260824.json`, `lg-detail-api-20260824.json` 이 이미 있다

## 선행 조건

- Push 2, 3 완료

## 작업

- [x] 4.0 여섯 사이트를 목록 API 로 돌린다
    - [x] 4.1 받아 둔 픽스처를 `tests/fixtures/` 로 옮긴다
        - 위 스크래치패드 경로에서 16개를 옮긴다. 이름은 그대로 둔다 (날짜가 들어 있다)
        - `hyundai-detail-20260825.html` 은 JS 껍데기라 **옮기지 않는다**
        - **실사이트 요청을 새로 하지 않는다.** 이미 받아 둔 것으로 충분하다
        - [x] 4.1.V 검증: 픽스처마다 항목 수와 필수 키가 있는지 pytest 로 확인.
              한화 4쪽 합 68, 삼성 2쪽 합 16, LG 88, SK 104 를 숫자로 확인한다
    - [x] 4.2 API 설정에 헤더 자리를 만든다
        - 현대는 `x-hkmc-service: HM` 헤더가 없으면 400 이다. 위 측정에 전체 주소와 헤더가 있다
        - `app/selector/api_schema.py` 의 `ApiListConfig`·`ApiDetailConfig` 에 헤더를 담는
          자리를 더하고 `app/crawler/api_source.py:189` 의 `_fetch_json()` 이 그것을 보낸다
        - **브라우저 위장은 하지 않는다.** User-Agent 는 공용 fetch 클라이언트 것을 그대로 쓰고,
          사이트가 요구하는 기능성 헤더만 담는다 (`.claude/rules/crawling.md`)
        - [x] 4.2.V 검증: 픽스처 기반 pytest — 설정에 담은 헤더가 요청에 실려 나가는지.
              실사이트 확인은 4.4 에서 한 번에 한다
    - [x] 4.3 페이지를 끝까지 받는다
        - 한화(68건, 20씩 4쪽)와 삼성(16건, 2쪽)이 대상이다. 위 측정에 파라미터가 있다
        - 마지막 쪽인지 판정하는 법이 사이트마다 다르다 — 한화는 `hasNext`, 삼성은
          `divCnt data-max`. 둘 다 담을 수 있게 만든다
        - **쪽 사이에도 호스트 딜레이를 지킨다.** 페이지를 연달아 때리지 않는다
        - 무한 반복을 막는 상한을 둔다. `hasNext` 가 끝나지 않는 응답에 걸리면 안 된다
        - [x] 4.3.V 검증: 저장한 쪽별 픽스처로 한화 68건, 삼성 16건이 모이는지 pytest
    - [x] 4.4 여섯 크롤러를 새 경로로 등록한다
        - 기존 크롤러는 셀렉터 중심이라 구성이 다르다. 지우고 다시 만든다
          (실제로는 **이름이 같은 크롤러를 제자리에서 갱신했다.** 지우려면 워크플로우를 먼저
          지워야 하고, 그러면 그 워크플로우에 매달린 `raw_jobs` 가 어느 사이트에서 온 것인지
          설명을 잃는다. 데이터 정리는 Push 6 이다)
        - 각 크롤러에 목록 API 설정과 상세 경로(API 또는 링크 또는 항목 속성)를 넣는다
        - **삼성 공고 번호는 `a[data-value]` 값에서 쉼표를 뺀 것이다.** 숫자 포맷에 기대는
          자리이므로 그 사실을 설정 주석이나 레시피에 적는다
        - [x] 4.4.V 검증: 크롤러마다 테스트 실행 1회. 필드별 매칭 개수를 확인하고 본문이
              채워지는지 본다
    - [x] 4.5 롯데 자격요건을 채운다
        - `detail.requirements` 셀렉터가 빈 값이라 8건 중 7건이 비어 있다
        - 상세 페이지에서 자격요건이 있는 자리를 찾아 채운다
        - HTML 태그가 섞이면 정규화의 `html_text` 규칙이 편다. 셀렉터에서 태그를 지우지 않는다
        - [x] 4.5.V 검증: 저장된 롯데 상세 픽스처로 자격요건이 뽑히는지 pytest
    - [x] 4.6 한화를 등록한다
        - 위 배경의 목록·상세 API 를 쓴다. 20건이 새로 들어온다
        - 계열사 11곳이 `sdNm` 에 들어 있다 — (주)한화 글로벌부문, (주)한화 전략부문,
          한화모멘텀, 한화생명, 한화솔루션/큐셀, 한화에어로스페이스, 한화엔진, 한화오션,
          한화오션에코텍, 한화첨단소재, 한화투자증권
        - [x] 4.6.V 검증: 실사이트 1회 실행. `crawl_runs` 행과 카운트 확인, 본문이 채워진
              20건이 들어오는지
    - [x] 4.7 사이트 레시피를 갱신한다
        - `.claude/site-recipes/` 의 여섯 파일에 최종 경로와 확인 날짜를 적는다
        - 문서에 적는 주소·본문 형식은 **코드나 설정에서 복사한다.** 기억으로 다시 쓰지 않는다
        - [x] 4.7.V 검증: 문서에 적힌 엔드포인트와 DB 의 설정값을 대조

    - [x] 4.8 폼 본문과 HTML 목록 응답을 설정에 담는다 (작업 중 추가)
        - 삼성 목록은 `application/x-www-form-urlencoded` 로 물어야 하고 응답이 JSON 이 아니라
          HTML 조각이다. SK 목록도 폼 본문이다. 지금 `_fetch_json()` 은 JSON 본문만 보내고
          JSON 응답만 읽으므로 두 사이트가 이 경로로 들어오지 못한다
        - `ApiListConfig` 에 `body_format`(json|form)과 `response`(json|html)를 더한다.
          `response: html` 이면 `items_path`·`fields` 는 CSS 셀렉터이고 `id_field` 는
          `<셀렉터>@<속성>` 이다
        - **삼성 공고 번호에는 천 단위 쉼표가 있다.** `|digits` 를 붙여 숫자만 남긴다
        - [x] 4.8.V 검증: 픽스처 기반 pytest — 삼성 1쪽에서 9건과 공고 번호가 나오는지,
              폼 본문이 실제로 폼으로 나가는지
    - [x] 4.9 항목 여러 값으로 상세 주소를 만든다 (작업 중 추가)
        - 현대 상세는 `recuYy`·`recuType`·`recuCls` 세 값이 있어야 열린다. 지금 `id_field` 는
          키 하나만 받는다
        - `id_field` 에 `{키}` 자리가 있으면 그 자리를 항목 값으로 채운 것이 id 다
        - [x] 4.9.V 검증: 픽스처 기반 pytest — 현대 20건의 상세 주소가 세 값으로 만들어지는지
    - [x] 4.10 한 필드를 여러 자리에서 모은다 (작업 중 추가)
        - LG 는 모집 부문마다(`recList`), 삼성은 모집 직무마다(`data.items`) 본문이 따로 있다.
          첫 칸만 읽으면 나머지 부문의 본문이 사라진다. 현대는 주요 업무와 우대 조건이 다른
          필드에 나뉘어 있다
        - 경로에 `*` 를 쓰면 배열 전체를, 경로를 배열로 적으면 여러 자리를 모아 빈 줄로 잇는다
        - [x] 4.10.V 검증: 픽스처 기반 pytest — LG 6부문, 삼성 12직무가 본문에 다 들어오는지

    - [x] 4.11 목록 날짜가 마감일인지 사이트마다 적는다 (작업 중 추가)
        - Push 2 는 상세에 마감일 셀렉터가 없는 크롤러에서만 목록 날짜로 마감을 판정한다.
          목록이 API 인 크롤러는 그 판정이 아예 돌지 않아 마감 건너뜀이 동작하지 않는다
        - `list.date_is_deadline` 을 설정에 더한다. 여섯 사이트의 목록 응답에는 마감일이 다
          들어 있고, **그 값이 마감일인지 게시일인지는 사이트만 안다**
        - 삼성 목록 날짜는 `2026.08.20 ~ 2026.09.02` 인 기간이다. 정규화가 뒤쪽만 남기므로
          마감일로 읽힌다. 기간의 앞쪽이 남는 사이트가 나오면 그 사이트는 적지 않는다
        - [x] 4.11.V 검증: pytest — 마감이 지난 공고에 상세 요청이 나가지 않고 건너뜀으로
              세어지는지, 적지 않은 크롤러는 예전 그대로인지

## 하지 않는 것

- 화면 표시. Push 5 다
- 데이터 비우기. Push 6 다
