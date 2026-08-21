---
name: crawl-test
description: "저장된 셀렉터로 실제 크롤링을 1회 실행해 추출 결과를 미리보기하고 실패 원인을 분류한다. 사용자가 '테스트 실행', '크롤링 한번 돌려봐', '이 셀렉터 되는지 확인', '왜 안 긁히는지 봐줘' 등을 말할 때 사용한다."
argument-hint: "[crawler-id 또는 workflow-id]"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
---

# 테스트 실행

셀렉터가 실제로 동작하는지 1회 크롤링으로 확인한다. 워크플로우 승격 전 필수 관문이고,
운영 중 워크플로우가 깨졌을 때의 첫 진단 도구다.

`.claude/rules/crawling.md` 를 먼저 따른다. 특히 요청 간 딜레이와 재시도 정책.

## 실행

```bash
python -m app.cli test-run --crawler <id> --limit 3
```

`--limit` 은 상세 페이지를 몇 건까지 따라갈지다. 테스트는 3건이면 충분하다. 전체를 도는 것은
테스트가 아니라 그냥 크롤링이고, 사이트에 부하만 준다.

## 결과 판정

필드별로 값이 채워졌는지 본다.

| 증상 | 원인 | 다음 행동 |
|---|---|---|
| fetch 실패 (timeout, 5xx, connection reset) | 전송 문제 | 재시도 대상. 3회 후에도 실패면 사이트 상태 확인 |
| fetch 성공, item 매칭 0 | 사이트 구조 변경 또는 JS 렌더링 | 재시도 금지. 셀렉터 재작성 또는 Playwright 전환 판단 |
| item 매칭, 특정 필드만 빈 값 | 그 필드 셀렉터만 틀림 | 해당 필드만 수동 보정 |
| 값이 전부 같은 내용 | 리스트가 아니라 컨테이너를 item 으로 잡음 | item 셀렉터 재작성 |
| 상세 URL 이 404 | 상대경로 결합 오류 | 파서의 URL 결합 확인 |
| 값에 공백/개행/광고 텍스트 섞임 | 셀렉터는 정상 | 정규화 규칙 문제. 셀렉터를 건드리지 않는다 |

마지막 줄이 자주 헷갈린다. **지저분한 값은 셀렉터 실패가 아니다.** 정규화 규칙에서 처리한다.

## JS 렌더링 판별

정적 fetch 결과에 공고 제목이 하나도 없고, 브라우저에서는 보이면 JS 렌더링이다.

```bash
python -m app.cli fetch --url <list-url> --raw | grep -c "<공고에 있는 문자열>"
```

0이면 Playwright 전환 대상이다. 판단 근거와 함께 레시피에 적는다 (`site-recipe`).
Playwright 는 사이트마다 개별 승격이지 기본값이 아니다.

## 픽스처로 남기기

같은 사이트를 반복해서 디버깅하게 되면 그 시점 HTML 을 픽스처로 저장하고 파서 테스트를 만든다.
매번 실서버를 때리면서 디버깅하지 않는다.

```bash
python -m app.cli fetch --url <url> --save tests/fixtures/<site>-list-YYYYMMDD.html
```

## 보고 형식

```
## 테스트 실행 결과 (crawler <id>, limit N)
- 리스트: item M건 매칭
- 필드: title M/M, link M/M, posted_at 0/M (실패)
- 상세 N건 중 성공 K건
- 실패 사유: <분류> — <한 줄 원인>
```

## 하지 않는 것

- 매칭 0을 "신규 공고 없음" 으로 보고하기. 실패다
- 셀렉터 미스에 재시도 걸기
- 테스트라는 이유로 딜레이 무시하기
