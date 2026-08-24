# Tasks: 본문 채우기 - Push 4

> PRD: `.claude/tasks/todo/prd-fill-body.md`
> Push 범위: 여섯 사이트를 목록 API 로 돌리고 빠진 값을 채운다 (사이트 설정)
> 상태: 대기

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

- [ ] 4.0 여섯 사이트를 목록 API 로 돌린다
    - [ ] 4.1 응답 픽스처를 저장한다
        - 여섯 사이트의 목록 응답과 상세 응답을 `tests/fixtures/` 에 넣는다
        - 파일명에 날짜를 넣는다 (`sk-list-api-20260825.json` 형식). 사이트가 바뀌면 언제 받은
          것인지가 유일한 단서다
        - **실사이트 요청은 여기서 한 번씩만 한다.** 이후 작업은 전부 이 픽스처로 한다
        - [ ] 4.1.V 검증: 픽스처마다 항목 수와 필수 키가 있는지 pytest 로 확인
    - [ ] 4.2 현대 목록 API 의 파라미터를 확인한다
        - 엔드포인트는 `GET https://talent.hyundai.com/api/rec/AP-HM-FO-02730` 이다.
          `hgrCd=1&lang=ko&secCode=&jdR...` 까지만 관측됐고 전체 형식은 확인하지 않았다
        - 렌더하면서 나가는 요청을 관찰해 전체 주소를 얻고 `httpx` 로 재현한다
        - 재현되지 않으면 현대는 목록을 렌더로 두고 상세는 항목 속성으로 간다. 그것도 된다
        - [ ] 4.2.V 검증: `httpx` 로 호출해 렌더된 목록과 같은 건수가 나오는지
    - [ ] 4.3 목록 API 가 첫 장만 주는지 확인한다
        - SK 는 렌더된 화면에 20건이었는데 API 는 104건을 준다. 다른 곳도 같을 수 있다
        - LG 88, 한화 20, 삼성 9 가 전체인지 첫 장인지 본다. 페이지 파라미터가 있으면 끝까지
          받는다
        - **한 번에 다 받는 것과 나눠 받는 것 중 사이트에 가벼운 쪽을 고른다**
        - [ ] 4.3.V 검증: 사이트별 총 건수를 표로 남기고 렌더된 화면의 건수와 비교
    - [ ] 4.4 여섯 크롤러를 새 경로로 등록한다
        - 기존 크롤러는 셀렉터 중심이라 구성이 다르다. 지우고 다시 만든다
        - 각 크롤러에 목록 API 설정과 상세 경로(API 또는 링크 또는 항목 속성)를 넣는다
        - **삼성 공고 번호는 `a[data-value]` 값에서 쉼표를 뺀 것이다.** 숫자 포맷에 기대는
          자리이므로 그 사실을 설정 주석이나 레시피에 적는다
        - [ ] 4.4.V 검증: 크롤러마다 테스트 실행 1회. 필드별 매칭 개수를 확인하고 본문이
              채워지는지 본다
    - [ ] 4.5 롯데 자격요건을 채운다
        - `detail.requirements` 셀렉터가 빈 값이라 8건 중 7건이 비어 있다
        - 상세 페이지에서 자격요건이 있는 자리를 찾아 채운다
        - HTML 태그가 섞이면 정규화의 `html_text` 규칙이 편다. 셀렉터에서 태그를 지우지 않는다
        - [ ] 4.5.V 검증: 저장된 롯데 상세 픽스처로 자격요건이 뽑히는지 pytest
    - [ ] 4.6 한화를 등록한다
        - 위 배경의 목록·상세 API 를 쓴다. 20건이 새로 들어온다
        - 계열사 11곳이 `sdNm` 에 들어 있다 — (주)한화 글로벌부문, (주)한화 전략부문,
          한화모멘텀, 한화생명, 한화솔루션/큐셀, 한화에어로스페이스, 한화엔진, 한화오션,
          한화오션에코텍, 한화첨단소재, 한화투자증권
        - [ ] 4.6.V 검증: 실사이트 1회 실행. `crawl_runs` 행과 카운트 확인, 본문이 채워진
              20건이 들어오는지
    - [ ] 4.7 사이트 레시피를 갱신한다
        - `.claude/site-recipes/` 의 여섯 파일에 최종 경로와 확인 날짜를 적는다
        - 문서에 적는 주소·본문 형식은 **코드나 설정에서 복사한다.** 기억으로 다시 쓰지 않는다
        - [ ] 4.7.V 검증: 문서에 적힌 엔드포인트와 DB 의 설정값을 대조

## 하지 않는 것

- 화면 표시. Push 5 다
- 데이터 비우기. Push 6 다
