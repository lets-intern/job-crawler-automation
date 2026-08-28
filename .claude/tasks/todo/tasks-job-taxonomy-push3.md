# Tasks: job-taxonomy - Push 3

> PRD: `.claude/tasks/todo/prd-job-taxonomy.md`
> Push 범위: 프롬프트가 트리 전체를 한 번에 보내고, 근거 검사와 "대분류만 정해짐"을 다룬다
> 상태: 완료 (2026-08-29)

## 관련 파일

- `app/classify/classifier.py` - `build_prompt`, `classify_body`. 판정 칸 목록을 프롬프트에
  적는 지금 방식(`JUDGE_CHOICES`)의 본보기
- `app/classify/grounding.py` - `JUDGE_FIELDS` 근거 검사(근거 문장이 원문에 없으면 버림)
- `tests/fixtures/` - SK·롯데그룹·두산·네이버·토스·카카오·우아한형제들 상세 픽스처와
  `seeds/site-configs-20260826.json`의 셀렉터
- `.claude/rules/llm.md` - 근거 없는 값은 빈 칸이다

## 선행 조건

- Push 2 완료 (동적 스키마와 저장 칸이 있어야 프롬프트에 넣고 결과를 받을 수 있다)

## 작업

- [x] 3.0 프롬프트·근거·대분류만 정해진 경우
    - [x] 3.1 `build_prompt`가 켜진 대분류·소분류 전체 트리를 한 번에 프롬프트에 적는다
          (`_taxonomy_block`). 두 단계로 나눠 부르지 않는다. 트리는 `대분류: 소분류1,
          소분류2, ...` 형태다
        - [x] 3.1.V 검증(정규화): `tests/test_classify_taxonomy_run.py` — `FakeClient`로
              대분류·소분류를 고른 응답을 주고 `classify_body`가 채우는지, 프롬프트에 트리
              전체가 한 번에 들어가는지 pytest 통과
    - [x] 3.2 근거 검사. `_ground_judged_field`를 `JUDGE_FIELDS`와 공유해 `job_major_evidence`/
          `job_minor_evidence`가 원문에 없으면 그 판정을 버린다
        - [x] 3.2.V 검증(정규화): 근거 문장이 원문에 없는 응답이 `dropped`/`reasons`에
              남는지 pytest 통과
    - [x] 3.3 소분류만 못 고른 경우. `job_major`는 정했는데 `job_minor`가 `판단불가`거나
          근거가 없으면 대분류만 남는다. 대분류가 버려지면(`판단불가`거나 근거 없음) 소분류도
          함께 비운다
        - [x] 3.3.V 검증(정규화): 대분류만 있는 응답, 소분류만 근거 검사 실패, 대분류
              `판단불가` 세 가지를 각각 pytest로 확인 — 규칙대로 동작
    - [x] 3.4 실측 1회. 상세가 HTML인 일곱 곳 픽스처를 실제 Gemini(`gemini-3.5-flash`)로
          돌렸다. 결과는 아래 표

| 사이트 | job_major | job_minor | 버림 | 비고 |
|---|---|---|---|---|
| SK | 기획·전략 | 기술기획 | 없음 | 정상 채움 |
| 롯데그룹 | (빈값) | (빈값) | job_major, job_minor | 근거 문장이 원문에 없어 버려짐 |
| 두산 | 영업 | B2B영업 | etc_info(직무 분류 아님) | 정상 채움 |
| 네이버 | AI·데이터 | RAG | 없음 | 정상 채움 |
| 토스 | (빈값) | (빈값) | 없음 | 모델이 판단불가로 답함(버림 아님) |
| 카카오 | 기획·전략 | PM·PO | 없음 | 정상 채움 |
| 우아한형제들 | 영업 | 일반영업 | 없음 | 정상 채움 |

        - [x] 3.4.V 검증(셀렉터 생성): 일곱 곳 전부 `job_major`가 표 안의 이름이었고
              (`major_in_table=true`), 채워진 다섯 곳 모두 `job_minor`가 그 `job_major`
              소속이 맞았다(`minor_matches_major=true`). "모델이 296개 중에서 실제로
              고르는가" — **고른다.** 일곱 중 다섯이 표 안에서 유효한 대분류·소분류 조합을
              냈고, 하나(토스)는 스스로 판단불가로 답했고, 하나(롯데그룹)는 근거 검사가
              버렸다 — 지어낸 값을 그대로 통과시키는 사례는 없었다
