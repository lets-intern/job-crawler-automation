# Tasks: fields-and-logo - Push 7

> PRD: `.claude/tasks/todo/prd-fields-and-logo.md`
> Push 범위: 남은 화면과 문서를 새 칸 구성에 맞춘다
> 상태: 진행 중

## 관련 파일

- `app/templates/fragments/review_table.html`, `review_modal.html` - 검수 화면
- `app/api/review_filter.py` - `FIELD_LABELS`, `EMPTY_NOTES`, 중복 기준
- `app/templates/fragments/rule_list.html` - 정규화 규칙 화면
- `.claude/docs/data-model.md` - 칸 목록
- `.claude/docs/api-contract.md` - 필드 표

## 선행 조건

- Push 1, 2, 3 완료

## 작업

- [ ] 7.0 마무리
    - [x] 7.1 검수 표의 열을 정리한다. 셋이 빠지고 둘이 늘어 **스물셋**이다. `empty_row` 의
          colspan 도 같이 맞춘다 — 안 맞으면 빈 표의 안내 문구가 칸 하나에 갇힌다
        - 열 자체는 Push 1~3 이 이미 옮겼다(`a81ae5f`, `1f8c009`, `c586125`). 남아 있던 것은
          colspan 하나고, 그 값은 15/16 이었다. 스물둘이 아니라 스물셋인 것은 머리글을 세어
          확인했다 — 고르기·번호·고치기·전달·보정·모회사 여섯에 값 칸 열넷과
          워크플로우·수집 시각·원문 셋이다. task 파일이 적어 둔 스물둘은 고르기 칸을 빼고
          센 수다
        - [x] 7.1.V 검증(화면): 0건일 때와 여러 건일 때를 열어 열 수와 안내가 맞는지 확인
            - `docker compose up -d --build api` 후 `/ui/review` 실사. 행이 있을 때 머리글
              23개, 0건일 때 머리글 23개에 안내 행 `colspan="23"`
            - `tests/test_ui_review_columns.py` 가 colspan 을 상수로 적지 않고 머리글에서
              세어 맞춘다. 중복 조건일 때 둘이 함께 하나씩 느는 것도 본다
    - [x] 7.2 빈 값 메모를 새 칸에 맞춘다. 직무와 자회사는 비어 있는 것이 정상일 수 있는지를
          적는다 — 적지 않으면 비어 있는 것이 전부 셀렉터가 놓친 것으로 읽힌다
        - 두 칸의 메모는 Push 2·3 이 이미 넣었다. 남아 있던 것은 `아무 필드나` 줄이다.
          메모가 `여섯 필드 중 하나라도` 라고 적힌 채였고, 실제로 보는 것은 열넷이다.
          칸 수를 세어 적게 바꿨다 — 다음에 칸이 바뀌어도 이 문장은 따라간다
        - 같은 줄의 `비어 있는 것이 정상일 수 있나` 칸이 비어 `—` 로 그려지고 있었다.
          낱말로 답할 자리라 `칸마다 다름` 을 적는다 (`.claude/rules/writing.md`)
        - [x] 7.2.V 검증(화면): 필드별 빈 건수 표에 새 칸이 나오고 메모가 붙는지 확인
            - `/ui/review` 실사. 열다섯 줄에 자회사(0건, 있을 수 있음)와 직무(728건, 있을 수
              있음)가 각각 메모와 함께 나온다. 마지막 줄은
              `아무 필드나 | 728건 | 칸마다 다름 | 위 14칸 중 하나라도 빈 공고...`
    - [x] 7.3 정규화 규칙 화면에서 고를 수 있는 필드 목록을 맞춘다. 지운 칸이 목록에 남으면
          운영자가 저장할 수 없는 규칙을 만들게 된다
        - 화면은 이미 맞다. `app/api/ui_rules.py` 가 목록을 손으로 적지 않고
          `NORMALIZED_FIELDS` 를 그대로 넘긴다. 그런데 그 사실을 잡아 두는 테스트가 없었고,
          `/ui/rules` 를 보는 테스트 자체가 하나도 없었다. 목록을 손으로 적는 순간 조용히
          어긋나는 자리라 `tests/test_ui_rules_fields.py` 를 더한다
        - [x] 7.3.V 검증(화면): 규칙을 새로 만들 때 지운 칸이 목록에 없는지 확인
            - `/ui/rules` 실사. 새 규칙 필드 목록이 열넷이고 순서까지 `NORMALIZED_FIELDS` 와
              같다. `department`·`job_category`·`headcount` 는 없고 `job_role` 은 있다
            - 화면만 막고 경로가 열려 있으면 뜻이 없어서, 지운 칸으로 `POST /api/rules` 하면
              422 로 거절되는 것도 함께 고정했다
    - [ ] 7.4 `.claude/docs/data-model.md` 의 칸 목록을 실제와 맞춘다
        - [ ] 7.4.V 검증(제공 API): 문서의 칸 이름과 `normalized_jobs` 컬럼이 같은지 확인
