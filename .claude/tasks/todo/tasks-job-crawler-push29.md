# Tasks: job-crawler - Push 29

> PRD: `.claude/tasks/todo/prd-job-crawler.md`
> Push 범위: HTML 조각으로 들어온 값을 정규화 단계에서 텍스트로 편다
> 상태: 완료

## 배경

LG 상세는 API 가 `detailContext`, `requiredItem`, `preferredItem` 을 HTML 조각으로 준다.
지금 `normalized_jobs.body` 에 태그가 그대로 남아 소비 측이 받는 값이 이렇다.

```
<p>정보보안운영팀에서는 ...</p><p>&nbsp;</p><p>■ 우리팀에서 하고 있는 일<br>1. 전사 보안 ...
```

**수집이 아니라 정규화가 다룰 문제다.** 셀렉터나 API 매핑에서 태그를 지우면 `raw_jobs` 가
원본이 아니게 되고, 규칙이 틀렸을 때 되돌릴 곳이 사라진다 (`CLAUDE.md`, `.claude/rules/data-safety.md`).

## 왜 `regex` 규칙으로 안 되는가

세 가지가 한꺼번에 필요하다.

- `<br>`, `</p>`, `</li>` 는 **줄바꿈이 되어야 한다.** 그냥 지우면 문장이 붙어버린다
- `&nbsp;`, `&amp;`, `&lt;` 는 원래 글자로 되돌려야 한다
- 남은 태그는 지우고 연속 공백·빈 줄은 정리해야 한다

정규식 규칙 여러 개를 순서대로 걸어 흉내낼 수는 있지만, 순서가 하나 어긋나면 조용히 깨진다.
같은 일을 하는 코드가 이미 `app/crawler/parser.py` 의 `_text()` 에 있다 — 블록 태그 앞뒤에
줄바꿈을 넣고 텍스트를 뽑는다. 그 규칙을 정규화에서도 쓸 수 있게 하는 것이 이 Push 다.

## 관련 파일

- `app/normalize/rules.py` - 규칙 종류가 `mapping` / `regex` / `trim` / `date_parse` 넷이다
- `app/normalize/engine.py` - 규칙을 순서대로 건다
- `app/crawler/parser.py` - `BLOCK_TAGS` 와 `_text()`. 줄바꿈을 넣는 방법이 여기 있다
- `seeds/normalization-rules.json` - 규칙 25개
- `app/normalize/backfill.py` - 재정규화

## 선행 조건

- 없음

## 작업

- [x] 29.0 HTML 조각을 텍스트로 펴는 규칙을 만든다
    - [x] 29.1 `html_text` 규칙 종류를 더한다
        - 블록 태그는 줄바꿈으로 바꾸고, 나머지 태그는 지우고, 엔티티는 원래 글자로 되돌리고,
          연속 빈 줄은 하나로 줄인다
        - 줄바꿈을 넣는 규칙은 `app/crawler/parser.py` 의 `BLOCK_TAGS` 를 쓴다. **같은 목록을
          두 벌 두지 않는다** (`.claude/rules/core.md`)
        - HTML 이 아닌 값이 들어와도 그대로 통과해야 한다. 규칙이 걸린 필드에 평문이 오는 것은
          정상이다
        - [x] 29.1.V 검증: 픽스처 기반 pytest. 아래 실제 값으로 확인한다
              - `<p>가</p><p>나</p>` -> 두 줄
              - `<br>` -> 줄바꿈
              - `&nbsp;`, `&amp;` -> 원래 글자
              - `<p>&nbsp;</p>` 만 있는 문단 -> 빈 줄로 뭉개지고 남지 않음
              - 평문 -> 그대로
              - 빈 값 -> 빈 값
    - [x] 29.2 LG 본문에 규칙을 건다
        - `seeds/normalization-rules.json` 에 더한다. 어느 필드에 걸지는 실제 값을 보고 정한다
        - 규칙 `note` 에 왜 필요한지 한 줄 적는다 — 다음 사람이 지우지 않도록
        - [x] 29.2.V 검증: 규칙 미리보기 화면에 실제 LG 본문을 넣어 결과를 눈으로 확인
    - [x] 29.3 이미 쌓인 값을 다시 정규화한다
        - `raw_jobs` 는 건드리지 않는다. `normalized_jobs` 만 다시 쓴다
        - **`job_field_overrides` 로 사람이 고친 값은 살아남아야 한다.** 규칙 다음에 덧씌우는
          지금 순서가 유지되는지 확인한다
        - `delivered_at` 을 지우거나 되돌리지 않는다 (`.claude/rules/data-safety.md`)
        - [x] 29.3.V 검증: 재정규화 후 태그가 남은 행이 0건인지 세고, 사람이 고친 2건이 그대로인지,
              `delivered_at` 이 변하지 않았는지 확인
    - [x] 29.4 다른 사이트도 태그가 섞였는지 본다
        - LG 만의 문제인지 확인한다. 섞인 곳이 더 있으면 같은 규칙을 건다
        - [x] 29.4.V 검증: 전체 `normalized_jobs` 에서 태그 형태 문자열이 남은 행 수를 워크플로우별로 센다

## 하지 않는 것

- `raw_jobs` 를 고쳐 쓰는 것. 원본은 HTML 그대로 남는다
- 수집 단계에서 태그를 지우는 것
