# 현대자동차 (talent.hyundai.com)

- 리스트 URL: https://talent.hyundai.com/theme/hall.hc
- 상세 URL 패턴: `/apply/applyView.hc?recuYy=<연도>&recuType=<구분>&recuCls=<번호>`
- 수집 방식: 목록·상세 둘 다 `api` (2026-08-25 전환). 브라우저를 띄우지 않는다.
  아래 "2026-08-25: 목록도 상세도 API 다" 에 두 요청과 필요한 헤더가 있다
- 페이지네이션: 확인하지 않았다. 목록 API 가 한 번에 20건을 준다
- 날짜 포맷: API 의 마감일은 `20260830` 이다. **지금 `date_parse` 규칙이 읽지 못한다** —
  아래 "마감일 형식이 지금 규칙으로는 읽히지 않는다" 참고. 렌더 경로가 주던 값은
  `2026-08-15 09:00 ~ 2026-08-30 17:00` 이었다
- robots.txt: 공용 fetch 클라이언트의 robots 확인을 통과했다
- 권장 주기: 30분으로 등록돼 있다 (workflow 6)

렌더 경로의 기록은 아래에 그대로 둔다. API 가 막히면 돌아갈 곳이다. 그때의 근거는 리스트 URL 의
정적 응답이 65,185자인데 본문이 13자, 반복 항목 0개라는 것이었다.

## 상세 링크는 속성값으로 만든다

목록 항목 안에 `a` 는 있지만 `href` 가 전부 `javascript:` 다. 상세로 가는 값은 링크가 아니라
`li` 의 데이터 속성에 있다.

```
<li class="K0035" data-recuyy="2026" data-recutype="N2" data-recucls="296">
```

이 세 값이 상세 URL 의 세 파라미터다. 그래서 `list.link` 를 비우고 `list.link_template` 에
`{data-recuyy}`, `{data-recutype}`, `{data-recucls}` 자리를 둔 URL 을 넣는다. 셀렉터가 비어
있으면 항목 노드 자신의 속성을 읽는다 (`app/selector/link.py`). 템플릿 전문은 DB 에 있다.

## 간헐적으로 목록이 빈 채로 렌더된다

2026-08-22 실행 3회 중 1회가 그랬다. 같은 URL, 같은 렌더 경로인데 run 5 는
`#applyList .apply__list > li` 0건으로 `selector_miss` 실패였고, 1분 뒤의 run 6 과 run 7 은
같은 셀렉터로 20건을 잡았다. 실패한 실행과 성공한 실행 사이에 셀렉터도 사이트도 바뀌지 않았다.

셀렉터를 넓혀서 고칠 문제가 아니다. 목록이 XHR 로 채워지는데 렌더가 그 전에 끝난 것으로 보이고,
`selector_miss` 는 재시도 대상이 아니므로 (`.claude/rules/crawling.md`) 다음 주기가 다시 가져온다.
빈도가 올라가면 렌더 대기 시간(`app/crawler/playwright.py` 의 정착 대기)을 재는 것이 먼저다.

## 셀렉터 특이사항

`list.company` 는 빈 문자열이 맞다. 이 사이트는 현대자동차 공고만 올라오고 항목에 회사명이
없다. 회사명이 필요하면 `crawlers.default_company` 에 적는다 — 2026-08-22 기준 비어 있고,
그래서 `normalized_jobs.company` 가 NULL 로 들어간다.

항목 안의 `a` 가 항목당 6개다(공유 버튼 등). `#applyList .apply__list > li a` 는 120개를
잡는다. 링크를 다시 잡을 일이 생기면 첫 `a` 를 그대로 쓰지 않는다. 어차피 여섯 개 다
`javascript:` 라 `href` 방식으로는 풀리지 않는다.

## 이력

| 날짜 | 일 | 원인 | 조치 |
|---|---|---|---|
| 2026-08-22 | 렌더 모드로 등록 시도 (crawler 3) | 상세 링크가 `javascript:void(0)` 이고 파라미터가 data 속성에 있다 | 등록만 남기고 중단. 스키마가 data 속성 기반 링크를 받아야 한다 |
| 2026-08-22 | 속성 + URL 템플릿으로 등록 (Push 14) | | 테스트 실행 run 6 성공(매칭 20, 상세 3건), 워크플로우 1 의 run 7 성공(신규 3건 적재) |
| 2026-08-22 | run 5 가 `selector_miss` 로 실패 | 렌더는 됐는데 목록이 비어 있었다. 1분 뒤 같은 셀렉터로 20건 | 재시도하지 않는다. 위의 "간헐적으로 목록이 빈 채로 렌더된다" 참고 |

## 2026-08-25: 클릭할 필요가 없다. 항목 속성에 상세 주소가 들어 있다

항목이 세 값을 가지고 있고, 그것이 상세 URL 의 세 파라미터다.

```
<li class="K0035" data-recuyy="2026" data-recutype="N2" data-recucls="296">
  -> https://talent.hyundai.com/apply/applyView.hc?recuYy=2026&recuType=N2&recuCls=296
```

**클릭을 시도하면 안 된다.** 항목 안의 첫 `a` 들은 SNS 공유 버튼(`href="javascript:;"`,
`onclick="shareSns('facebook', ...)"`)이라 눌러도 이동하지 않는다. 2026-08-25 에 그것을 눌러
타임아웃이 났다.

상세는 서버가 렌더한 HTML 이다. 클릭 뒤 XHR 이 0건이고 나가는 것은 문서 요청 하나다.
구조화된 응답이 없으므로 13개 항목은 텍스트를 LLM 이 나눠야 한다
(`.claude/tasks/todo/prd-crawler-v2.md` 5번).

## 2026-08-25: 목록도 상세도 API 다. 브라우저를 띄우지 않는다

수집 방식을 `api`/`api` 로 바꿨다. 두 요청 모두 헤더가 있어야 하고, 없으면 400 이다.

```
GET https://talent.hyundai.com/api/rec/AP-HM-FO-02730?hgrCd=1&lang=ko&secCode=&jdRecuCate=01&secLoad=Y
  accept: application/json, text/plain, */*
  referer: https://talent.hyundai.com/theme/hall.hc
  x-hkmc-service: HM
  x-hkmc-token: null
  -> data.applyList 20건

GET https://talent.hyundai.com/api/rec/AP-HM-FO-02800?hgrCd=1&lang=ko&recuYy=2026&recuType=N2&recuCls=296
  referer 만 /apply/applyView.hc 로 바뀐다
  -> data.applyInfo 157필드. 전부 평문이다
```

쿠키는 필요 없다. 헤더는 `crawlers.api_config_json` 의 `headers` 에 담는다. User-Agent 는
담을 수 없다 — 이름은 공용 fetch 클라이언트가 정한다.

**`/apply/applyView.hc` 상세 HTML 은 쓰지 않는다.** 2026-08-25 에 받아 보니 텍스트가
1,098자뿐인 JS 껍데기였다. 위의 "상세는 서버가 렌더한 HTML 이다" 는 그 시점의 관찰이고,
`applyInfo` 를 확인한 지금은 HTML 을 파싱할 이유가 없다.

상세 주소는 한 값이 아니라 `recuYy`·`recuType`·`recuCls` 세 값으로 만든다. `id_field` 에
`{키}` 자리를 쓴 템플릿을 넣어 세 값을 이어 붙인 것이 id 가 된다
(`seeds/site-configs-20260826.json`).

본문은 `privJdDtl`(주요 업무)·`aboutTeamNtc`(조직 소개)·`etc`(기타)를 모으고, 자격요건은
`privMustReq`(필수)와 `prefReq`(우대)를 모은다.

### 마감일 형식이 지금 규칙으로는 읽히지 않는다

API 가 주는 마감일은 `applyEndDt = 20260830` 이다. `deadline` 의 `date_parse` 규칙에
`%Y%m%d` 가 없어서 이 값은 정규화에서 실패한다. 렌더 경로가 주던
`2026-08-15 09:00 ~ 2026-08-30 17:00` 과 형식이 다르고, 응답 157필드 어디에도 구분자가 들어간
날짜는 없다.

`raw_jobs` 에는 값이 그대로 남으므로 규칙에 `%Y%m%d` 를 더한 뒤 재정규화하면 복구된다.
2026-08-25 기준 20건이 전부 이미 아는 공고라 새로 적재된 행은 없고, **다음에 올라오는 새 공고가
이 문제를 처음 만난다.**

## 칸 매핑 (2026-08-26, 수집은 여섯 칸)

**이 사이트는 여섯 칸만 수집한다** — 제목·본문·모집 마감일·모집 시작일·모집 기업, 그리고 원본 주소. 나머지 열한 칸(직군·근무지·경력 구분·고용형태·모집인원·주요 업무·우대사항·전형 절차·자격요건·조직 부서·기타)은 본문을 읽어 나눈다.

`crawlers` 17번 행의 설정에서 그대로 옮겼다. 같은 값이 `seeds/site-configs-20260826.json` 에 있고 `tests/test_split_body_mapping.py` 가 픽스처에 돌려 본다. 문서와 저장된 설정이 갈리지 않는지는 `tests/test_site_recipe_mapping.py` 가 본다.

| 칸 | 어디서 | 자리 |
|---|---|---|
| 제목 | 상세 API | `data.applyInfo.recuNoticeNm` |
| 본문 | 상세 API | `data.applyInfo.privJdDtl`<br>`data.applyInfo.aboutTeamNtc`<br>`data.applyInfo.etc` |
| 모집 마감일 | 상세 API | `data.applyInfo.applyEndDt` |
| 모집 시작일 | 상세 API | `data.applyInfo.appDispStDt` |

여기 없는 칸은 이 사이트가 그 값을 주지 않는다는 사실이다. 이 사이트가 주지 않는 것: 모집 기업. 다른 값으로 채우지 않는다.

2026-08-26 이전에는 이 표에 열여섯 칸이 있었다. 그 매핑을 뺀 이유는 `seeds/site-configs-20260826.json` 의 `why_the_mappings_were_removed` 에 있다 — 사이트 11곳 x 칸 16개 = 176번의 판단이 640건에서 절반도 채우지 못했고, 그중 다섯 곳이 뜻이 다른 칸에 값을 넣고 있었다.
