# Tasks

```
todo/    PRD, 진행 중 task 파일, 결과보고서
done/    완료된 기능 단위 폴더
  <기능명>/  prd + tasks-push*.md + result-push*.md
memos/   그 외 메모
```

## 흐름

| 단계 | 담당 |
|---|---|
| PRD 를 Push 단위 파일로 분해 | `task-maker` |
| task 파일 실행, 모드 선택, 결과보고서 작성 | `task-runner` |
| 여러 영역이 섞인 Push 를 워커에 배분 | `push-lead` (모드 A) |
| 단일 영역 Push 를 혼자 실행 | `task-executor` (모드 B) |
| 완료된 기능을 done/ 으로 아카이브 | `task-cleaner` |

모드 판정은 `task-runner` 한 곳에서만 한다. 대부분은 모드 B 다.

상태 표시는 체크박스와 단어만 쓴다. 이모지·아이콘은 쓰지 않는다 (`.claude/rules/writing.md`).
