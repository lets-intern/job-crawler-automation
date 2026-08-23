# 현대자동차 (talent.hyundai.com)

- 리스트 URL: https://talent.hyundai.com/theme/hall.hc
- 상세 URL 패턴: `/apply/applyView.hc?recuYy=<연도>&recuType=<구분>&recuCls=<번호>`
- 렌더링: Playwright 필요. 근거는 리스트 URL 의 정적 응답이 65,185자인데 본문이 13자,
  반복 항목 0개라는 것이다. 렌더 후에는 1,331,820자에 `#applyList .apply__list > li` 가 20건 잡힌다
- 페이지네이션: 확인하지 않았다
- 날짜 포맷: 목록은 `D-8` 형태의 남은 일수만 보여 준다. 상세의 마감일은
  `2026-08-15 09:00 ~ 2026-08-30 17:00` 처럼 시작과 마감이 한 문자열에 있다. 정규화 규칙은 아직 없다
- robots.txt: 공용 fetch 클라이언트의 robots 확인을 통과했다
- 권장 주기: 1440분으로 등록했다. 목록이 하루 단위로 바뀌는 사이트라 더 짧게 둘 이유를 찾지 못했다

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
