# Tasks: side-workflows - Push 11

> PRD: `.claude/tasks/todo/prd-side-workflows.md`
> Push 범위: 빈 칸을 채우고 값이 다른 칸은 제안으로 남긴다. 자동으로 덮지 않는다
> 상태: 진행 중

## 관련 파일

- `app/classify/classifier.py` - 프롬프트와 응답 스키마
- `app/classify/grounding.py` - 근거 없는 값은 버린다
- `app/classify/store.py` - 무엇을 모델에 보내는가
- `app/normalize/engine.py` - 규칙 -> 분류 -> 사람 보정 순서
- `migrations/0005_job_field_overrides.sql` - 보정 표. 제안이 수락되면 여기로 간다
- `app/api/review.py`, `app/templates/fragments/review_cell_macro.html` - 검수 화면의 칸
- `.claude/rules/llm.md` - 모델은 제안자이지 권위가 아니다

## 선행 조건

- Push 9 완료 (원문을 읽고 있어야 채울 값이 늘어난다)
- Push 10 완료 (검수 화면에서 원문을 보며 제안을 판단한다)

## 작업

- [ ] 11.0 채우기와 제안
    - [x] 11.1 마이그레이션. `job_field_suggestions (id, raw_job_id, field_name, value,
          reason, created_at)`. `(raw_job_id, field_name)` 이 유일하고 새 제안이 옛 제안을
          덮는다 — 같은 칸에 제안이 둘이면 어느 것을 보고 있는지 알 수 없다
        - [x] 11.1.V 검증(스키마): 적용·역적용, 같은 칸에 두 번 넣으면 하나로 덮이는지
    - [x] 11.2 호출에 **지금 값을 함께 보낸다.** 무엇이 이미 채워져 있는지 모르면 "다르다" 를
          말할 수 없다. 프롬프트에 두 가지를 적는다 — 빈 칸은 원문에서 찾아 채우고, 값이 있는
          칸은 원문과 다를 때만 다른 값을 내고 왜 다른지 적는다
        - [x] 11.2.V 검증(정규화): 값이 있는 칸과 빈 칸을 섞은 픽스처로 응답이 갈리는지 pytest
    - [x] 11.3 응답을 두 갈래로 보낸다. 비어 있던 칸을 채운 것은 지금 경로 그대로
          `job_classifications` 로, 값이 있는데 달라진 것은 `job_field_suggestions` 로 간다.
          **호출은 하나다** — 두 번 부르면 토큰이 두 배다
        - [x] 11.3.V 검증(정규화): 한 번의 호출에서 두 표에 각각 들어가는지 pytest
    - [x] 11.4 제안에도 근거 검사를 그대로 건다. 원문에서 찾지 못한 값은 제안이 되지 않는다.
          제안이라고 검사를 느슨하게 하면, 사람이 수락 단추를 누르는 순간 지어낸 값이 확정 값이
          된다. `app/classify/classifier.py` 의 `_extract_suggestions` 가 `grounding.py` 의
          `missing_lines` 를 그대로 불러 쓴다 — 재구현하지 않는다. 11.2 에서 이미 배선했고
          `tests/test_classify_suggestions.py` 가 검증한다
        - [x] 11.4.V 검증(정규화): 원문에 없는 값이 제안으로 남지 않는지 pytest
              (`test_a_suggestion_without_evidence_in_the_source_is_thrown_away`,
              `test_a_reflowed_suggestion_still_counts_as_grounded`)
    - [ ] 11.5 **수집이 채우는 여섯 칸도 제안 대상에 넣되 자동으로 덮지 않는다.**
          `deadline` 은 마감 지난 공고를 거르는 데 쓰이고 `company` 는 계열사를 가르는 값이라,
          모델 판단 하나로 바뀌면 안 된다. 정규화의 어느 경로도 제안을 읽지 않는다는 것을
          테스트로 못박는다
        - [ ] 11.5.V 검증(정규화): 제안이 있는 건을 재정규화해도 확정 값이 그대로인지 pytest
    - [ ] 11.6 검수 화면의 칸에 `제안 있음` 을 낱말로 적고, 제안 값과 이유를 보인다.
          수락하면 `job_field_overrides` 로 들어가고 거절하면 제안 행만 지운다. 어느 쪽이든
          `raw_jobs` 와 `normalized_jobs` 는 건드리지 않는다
        - [ ] 11.6.V 검증(화면): 수락·거절을 각각 눌러 칸과 보정 개수가 갈리는지 확인
    - [ ] 11.7 조회 조건에 `제안이 있는 건` 을 더한다. 640건에서 제안이 붙은 것을 눈으로 찾게
          두면 아무도 수락하지 않는다
        - [ ] 11.7.V 검증(화면): 조건을 걸어 제안 있는 건만 나오는지, 건수가 맞는지 확인
