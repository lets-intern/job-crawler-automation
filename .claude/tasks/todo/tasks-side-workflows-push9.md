# Tasks: side-workflows - Push 9

> PRD: `.claude/tasks/todo/prd-side-workflows.md`
> Push 범위: 분류가 원문을 읽는다. 원문이 없으면 본문으로 떨어진다
> 상태: 진행 중

## 관련 파일

- `app/classify/store.py` - `_BODY`, `read_body`, 대상 조회
- `app/classify/classifier.py` - `MAX_BODY_CHARS`, 프롬프트
- `app/classify/grounding.py` - 근거를 무엇에 돌려 보는가
- `app/normalize/engine.py` - 분류가 열한 칸을 덮는 순서

## 선행 조건

- Push 8 완료 (`source_text` 가 있어야 한다)
- 결정 필요: **`MAX_BODY_CHARS` 를 얼마로 할 것인가.** Push 8.1 이 잰 사이트별 원문 길이가
  그 숫자다. 재기 전에는 9.3 을 시작하지 못한다

## 작업

- [ ] 9.0 분류 입력 교체
    - [x] 9.1 읽는 값을 `source_text` 로 바꾸고 없으면 `body` 로 떨어진다. **폴백이 필수다** —
          이미 쌓인 건에는 원문이 없고, 그것을 대상에서 빼면 기존 공고가 분류에서 사라진다
          — `app/classify/store.py` 의 `read_body` 를 `read_source` 로 바꾸고 SQL 에서
          `coalesce(nullif(source_text,''), body, '')` 로 떨어뜨린다
        - [x] 9.1.V 검증(정규화): 원문 있는 건과 없는 건을 같은 픽스처 DB 에 넣고 각각 어느
              값으로 갔는지 pytest — `tests/test_classify_source_text.py` 4건. 읽는 값과
              실행이 보내는 프롬프트를 둘 다 본다
    - [x] 9.2 근거 검사도 같은 값에 돌린다. 원문으로 분류했으면 원문에서 찾는다. 두 값이
          어긋나면 멀쩡한 칸이 통째로 버려진다 — `classify_body` 가 보낸 그 값을 `ground` 에
          그대로 넘기고 있어 코드 경로는 이미 하나였다. 버린 이유 문장이 `본문` 을 가리켜
          틀린 말이 되어 `보낸 글` 로 바꿨다 (`NOT_IN_SOURCE`, `NO_EVIDENCE`)
        - [x] 9.2.V 검증(정규화): 본문 밖에만 있는 문장을 뽑은 칸이 버려지지 않는지 pytest
              — `tests/test_classify_source_text.py` 에 4건 더했다. 뽑는 칸(근무지)과 판정
              칸의 근거 문장을 원문·본문 양쪽에 돌려 보고, 실행 경로로도 한 번 본다
    - [x] 9.3 `MAX_BODY_CHARS` 를 8.1 의 측정으로 다시 정한다. 자른 사실을 응답에 남기는
          지금 동작은 그대로 둔다 — **12,000 그대로 둔다.** 픽스처를 다시 재 보니 원문 최대는
          토스 10,312자, 그다음이 네이버 3,872자로 일곱 곳 전부 상한 안이다. 상한을 넘는
          것은 원문이 아니라 LG 의 본문 38,019자이고, LG 는 상세가 API 라 원문을 뽑지 않아
          Push 9 로 달라진 것이 없다. **올릴 근거가 측정에 없어 올리지 않았다.** 근거와
          다시 잰 숫자는 `app/classify/classifier.py` 의 상수 주석에 적었다
        - [x] 9.3.V 검증(정규화): 상한을 넘는 원문이 잘리고 그 사실이 기록되는지 pytest
              — `tests/test_classify_source_text.py` 2건. 자르는 동작 하나와, 잰 원문 일곱
              곳이 전부 상한 안이라는 결정 자체를 고정하는 것 하나
    - [x] 9.4 대상 조회의 "본문이 있다" 조건을 "원문이나 본문이 있다" 로 넓힌다.
          Push 2 의 네 범위 전부에 같이 적용한다 — **Push 2 는 아직 안 들어왔다.** 지금
          저장소에 있는 대상 조회는 `pending_ids` 와 `pending_count` 둘뿐이고 그 둘에
          적용했다. 조건은 `read_source` 와 같은 식(`_CLASSIFY_TEXT`) 하나를 쓴다 —
          범위 넷이 들어올 때 그 상수를 그대로 쓰면 조건이 갈리지 않는다
        - [x] 9.4.V 검증(정규화): 원문만 있고 본문이 빈 건이 대상에 들어오는지 pytest
              — `tests/test_classify_source_text.py` 2건. 원문만 있는 건이 들어오고,
              원문도 본문도 없는 건은 빠진다
    - [ ] 9.5 실측 1회. 원문이 있는 건 몇 개를 실제 제공자로 돌려 열한 칸이 전보다 더
          채워지는지 본다. 채워진 칸 수와 버린 칸 수를 결과보고서에 적는다
        - [ ] 9.5.V 검증(셀렉터 생성): 같은 공고를 본문 기준과 원문 기준으로 각각 분류해
              칸별 채움을 비교한 표를 남긴다
