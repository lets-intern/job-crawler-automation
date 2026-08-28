# Tasks: side-workflows - Push 8

> PRD: `.claude/tasks/todo/prd-side-workflows.md`
> Push 범위: 상세 원문을 가공 없이 저장한다. 분류는 아직 그것을 읽지 않는다
> 상태: 완료 (2026-08-28)

## 관련 파일

- `app/crawler/parser.py` - `BLOCK_TAGS`, 상세 파싱
- `app/crawler/runner.py` - `raw_data_json` 을 만드는 자리
- `app/crawler/hashing.py` - `HASH_FIELDS`. 원문은 여기 들어가지 않는다
- `app/selector/schema.py` - `SPLIT_DETAIL_FIELDS`, 선택 필드 취급
- `tests/fixtures/` - 열한 사이트의 저장된 상세 HTML
- `.claude/rules/data-safety.md` - 원본 HTML 은 저장하지 않는다

## 선행 조건

- 없음. Push 1~7 과 서로 기다리지 않는다
- 결정 필요: **상세 컨테이너를 무엇으로 잡을 것인가.** 셀렉터를 하나 더 두는 방법(사이트마다
  판단이 는다)과 본문 셀렉터의 조상 요소를 쓰는 방법 중 8.1 에서 픽스처로 재 보고 정한다.
  이 결정 없이 8.2 를 시작하지 못한다

## 작업

- [x] 8.0 원문 수집
    - [x] 8.1 픽스처 열한 개에 두 방법을 다 돌려 글자 수와 들어간 내용을 잰다. GNB·푸터·
          추천공고가 섞이는지, 본문 밖의 자격요건이 잡히는지 표로 적고 방법을 고른다.
          결과를 `.claude/site-recipes/` 에 남긴다
        - [x] 8.1.V 검증(파서): 사이트별 글자 수와 섞인 내용을 표로 남기고 방법을 정한다
              — `.claude/site-recipes/source-text-container.md`. 고른 것은 본문 셀렉터의
              조상 1단계에서 페이지 부속을 뺀 것이다. 별도 셀렉터는 두지 않고, API 상세는
              원문을 뽑지 않는다
    - [x] 8.2 고른 방법으로 상세 원문을 뽑아 `raw_data_json.source_text` 에 넣는다.
          태그는 없고 줄바꿈은 살아 있는 텍스트다. **원본 HTML 은 저장하지 않는다**
        - [x] 8.2.V 검증(파서): 픽스처로 `source_text` 가 들어가고 태그가 없는지 pytest
              — `tests/test_source_text.py` 33건, `tests/test_source_text_run.py` 2건
    - [x] 8.3 `content_hash` 는 그대로 둔다. `HASH_FIELDS` 에 `source_text` 를 넣지 않는다
        - [x] 8.3.V 검증(파서): 같은 픽스처를 두 번 넣어 원문이 있어도 해시가 같고 두 번째가
              신규로 쌓이지 않는지 pytest — `tests/test_hashing.py` 와
              `tests/test_source_text_run.py` 의 두 실행 테스트. 적재된 해시가 원문을 뺀
              네 필드의 해시와 같다는 것까지 단언한다
    - [x] 8.4 원문을 못 뽑아도 수집은 실패하지 않는다. `source_text` 가 없는 건은 지금과 같이
          `body` 만 가진 채로 적재된다 — 원문이 없다고 공고를 버리면 이미 되는 것을 잃는다
        - [x] 8.4.V 검증(크롤링 실행): 원문을 못 뽑는 픽스처로 적재가 그대로 되는지 pytest
              — `tests/test_source_text_run.py`. 저장된 한화 상세 응답(상세가 API 라 원문이
              없다)으로 실행해 적재·정규화가 되고 키 묶음이 원문 이전과 같은지 본다
