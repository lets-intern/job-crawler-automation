---
description: 새 채용 사이트를 등록한다. 셀렉터 생성 → 테스트 실행 → 레시피 기록까지 한 번에.
argument-hint: <리스트 URL> <상세 URL>
---

# 새 사이트 등록

## 입력

$ARGUMENTS

## 절차

1. `.claude/site-recipes/` 에 같은 도메인 레시피가 있는지 먼저 본다. 있으면 그것부터 읽는다
2. `selector-generate` 스킬대로 셀렉터를 만들고 같은 HTML 에서 검증한다
3. `crawl-test` 스킬로 `--limit 3` 실행해 필드별 추출 결과를 낸다
4. 결과와 실패 필드를 사용자에게 보고한다. **워크플로우 등록은 사용자가 결정한다**
5. 새로 알아낸 사실이 있으면 `site-recipe` 로 기록한다

셀렉터가 두 번 실패하면 계속 돌리지 말고 사용자에게 넘긴다 (`rules/llm.md`).
robots.txt 가 막고 있으면 1번에서 멈추고 보고한다 (`rules/crawling.md`).
