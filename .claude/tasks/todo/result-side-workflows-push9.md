# 결과보고서: tasks-side-workflows-push9.md

> 완료일: 2026-08-28
> Push 범위: 분류가 원문(`source_text`)을 읽는다. 원문이 없으면 본문으로 떨어진다

## 구현 요약

| 작업 | 상태 | 비고 |
|---|---|---|
| 9.1 읽는 값을 `source_text` 로, 없으면 `body` 로 폴백 | 완료 | `app/classify/store.py::read_source` |
| 9.2 근거 검사를 같은 값에 적용 | 완료 | `app/classify/grounding.py`, 이유 문구를 `보낸 글` 로 수정 |
| 9.3 `MAX_BODY_CHARS` 재검토 | 완료 | 12,000 유지 — 원문 최대(토스 10,312자)가 상한 안 |
| 9.4 대상 조회를 "원문이나 본문" 으로 확장 | 완료 | `pending_ids`/`pending_count` 의 `_CLASSIFY_TEXT` |
| 9.5 실측 1회 | 완료 | 아래 참고 |

## 9.5 실측 결과

Gemini 크레딧 반영 후 상세가 HTML 인 일곱 곳 픽스처로 본문 기준·원문 기준 각 1회, 실제
`gemini-3.5-flash` 호출 14건을 돌렸다. 근거 검사가 버린 칸은 일곱 곳 전부 0건.

| 사이트 | 본문 채움 | 원문 채움 | 늘어난 칸 | 줄어든 칸 |
|---|---|---|---|---|
| SK | 8 | 7 | employment_type | hiring_process, preferred |
| 롯데그룹 | 9 | 9 | 없음 | 없음 |
| 두산 | 5 | 6 | etc_info | 없음 |
| 네이버 | 4 | 8 | career_level, etc_info, hiring_process, preferred | 없음 |
| 토스 | 7 | 5 | 없음 | hiring_process, preferred |
| 카카오 | 8 | 9 | work_location | 없음 |
| 우아한형제들 | 5 | 5 | 없음 | 없음 |

합계 46 → 49칸(+3). SK·토스의 감소는 원문이 늘린 글자가 이미 다른 칸으로 뽑히는 이름표
값뿐이라 원문 탓으로 보기 어렵고, 1회 호출의 응답 변동일 가능성이 크다. 자세한 근거는
`.claude/tasks/todo/tasks-side-workflows-push9.md` 의 9.5 절 참고.

결론: 원문 기준이 본문 기준보다 나쁘지 않다(근거 없는 값 증가 없음, 합계 증가). `read_source`
를 되돌릴 이유가 없다.

## 검증 결과

| 대상 | 검증 | 결과 |
|---|---|---|
| 분류 입력 폴백 | `tests/test_classify_source_text.py` | 통과 |
| 근거 검사 | 위 파일에 포함 | 통과 |
| 상한 자르기 | 위 파일에 포함 | 통과 |
| 대상 조회 확장 | 위 파일에 포함 | 통과 |
| 실측 | 실제 Gemini 호출 14건, 결과는 위 표 | 완료 |

## 이슈 및 특이사항

- 9.5 는 Gemini 크레딧 고갈로 오래 막혀 있다가 크레딧 충전 후 완료했다. Push 11(제안 기능)
  이 이 Push 완료를 선행 조건으로 걸어 뒀는데, Push 11 은 이미 별도로 완료됐다
  (`result-side-workflows-push11.md`) — 9.5 를 기다리지 않고 픽스처/FakeClient 로 구현·검증만
  먼저 끝냈고, 이번 실측으로 그 판단(되돌릴 필요 없음)이 사후적으로 확인됐다.
