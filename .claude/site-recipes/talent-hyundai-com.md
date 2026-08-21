# 현대자동차 (talent.hyundai.com)

- 리스트 URL: https://talent.hyundai.com/theme/hall.hc
- 상세 URL 패턴: `/apply/applyView.hc?recuYy=<연도>&recuType=<구분>&recuCls=<번호>`
- 렌더링: Playwright 필요. 근거는 리스트 URL 의 정적 응답이 65,185자인데 본문이 13자,
  반복 항목 0개라는 것이다. 렌더 후에는 1,331,820자에 `#applyList .apply__list > li` 가 20건 잡힌다
- 페이지네이션: 확인하지 않았다
- 날짜 포맷: 목록은 `D-8` 형태의 남은 일수만 보여 준다. 마감일 자체는 상세에 있다
- robots.txt: 공용 fetch 클라이언트의 robots 확인을 통과했다
- 권장 주기: 등록하지 못했으므로 정하지 않았다

## 지금은 등록할 수 없다

목록 항목 안에 `a` 는 있지만 `href` 가 전부 `javascript:void(0)` 다. 상세로 가는 값은 링크가
아니라 `li` 의 데이터 속성에 있다.

```
<li class="K0035" data-recuyy="2026" data-recutype="N2" data-recucls="296">
```

이 세 값이 상세 URL 의 세 파라미터다. `list.link` 는 `href` 만 읽으므로 지금 스키마로는
이 URL 을 만들 수 없다.

2026-08-22 실행(run 4) 결과: `status=failed`, `error_class=transport`, `matched=20`,
`fail_count=3`, 사유 `가져올 수 없는 URL 이다: javascript:;`. 항목별 실패 3건은 상세를
따라가려다 난 것이고, 공용 fetch 클라이언트가 http(s) 가 아닌 URL 을 거절해 실제 요청은
밖으로 나가지 않았다.

## 셀렉터 특이사항

`list.company` 는 빈 문자열이 맞다. 이 사이트는 현대자동차 공고만 올라오고 항목에 회사명이
없다. 회사명이 필요하면 `crawlers.default_company` 에 적는다.

항목 안의 `a` 가 항목당 6개다(공유 버튼 등). `#applyList .apply__list > li a` 는 120개를
잡는다. 링크를 다시 잡을 일이 생기면 첫 `a` 를 그대로 쓰지 않는다.

## 이력

| 날짜 | 일 | 원인 | 조치 |
|---|---|---|---|
| 2026-08-22 | 렌더 모드로 등록 시도 (crawler 3) | 상세 링크가 `javascript:void(0)` 이고 파라미터가 data 속성에 있다 | 등록만 남기고 중단. 스키마가 data 속성 기반 링크를 받아야 한다 |
