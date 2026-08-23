---
name: task-runner
description: "todo 의 task 파일을 읽고 에이전트에 위임하여 자동 실행합니다. 사용자가 '작업 실행', '태스크 실행', '다음 작업', '작업 계속', '이어서 진행' 등을 요청할 때 사용합니다."
argument-hint: "[task-file-path]"
disable-model-invocation: true
allowed-tools: Read, Write, Bash, Glob, Grep, Agent
---

# Task Runner — 오케스트레이터

`.claude/tasks/todo/` 의 task 파일을 읽고 에이전트에 실행을 위임한다.
실제 구현·검증·커밋은 리드와 워커가 한다. **이 스킬은 직접 구현하지 않는다.**

## 시작 절차

```bash
# 1. 브랜치 확인. main 이면 여기서 브랜치부터 만든다 (rules/git-safety.md)
git branch --show-current

# 2. sentinel 생성. Stop 훅이 이걸 보고 미완료 작업이 남은 세션을 이어간다
touch .claude/.task-running

# 3. done 디렉토리 확인
mkdir -p .claude/tasks/done
```

파일이 지정되지 않았으면 `.claude/tasks/todo/tasks-*.md` 목록을 보여주고 선택을 요청한다.
**이 경우에만 질문이 허용되고, 이후는 자율 실행이다.**

선택된 파일의 "선행 조건" 항목을 먼저 읽는다. 앞 Push 가 미완료거나 PRD 미결정 사항에 막혀
있으면 시작하지 않고 사용자에게 보고한다.

## 실행 모드 선택

이 판정은 여기서만 한다. push-lead 나 워커가 다시 정하지 않는다.

```
task 파일의 하위 작업을 본다
   │
   ▼
1. 파일 3개 미만 + 단일 영역(셀렉터만 / 화면만 등)?
   ├─ YES → 모드 B (task-executor 단독)
   └─ NO  → 2번
   │
   ▼
2. 서로 다른 파이프라인 단계가 섞여 있고, 그중 병렬 가능한 것이 있는가?
   ├─ NO  → 모드 B
   └─ YES → 모드 A (push-lead 가 워커 스폰)
```

한 Push 가 대부분 한 단계에 속하도록 `task-maker` 가 나누므로, **모드 B 가 기본이다.**
모드 A 는 기반 Push(스키마 + 설정 + fetch 클라이언트)처럼 실제로 영역이 갈릴 때만 쓴다.

### 모드 A: push-lead 위임

```
push-lead 에이전트로 다음 task 파일을 실행하세요.

파일: .claude/tasks/todo/tasks-<name>-push<N>.md
내용: <파일 전체 내용>

지시사항:
- 항목을 파이프라인 단계로 분류해 워커에 배정 (분류표는 push-lead 안에 있음)
- app/crawler/fetcher.py 는 crawler-worker 단독 소유
- 스키마 → 파서 → 스케줄러 순서 의존은 항상 순차
- 각 하위 작업 완료 시 즉시 커밋, 완료 항목은 [x] 로 체크
- 실사이트 실행이 필요한 검증은 push 당 1회로 모을 것
- git push 금지. 사용자에게 보고 후 대기
- 오류 시 새 번호의 수정 하위 작업을 파일에 추가한 뒤 해결

참조:
- 상황별 스킬 표: 루트 `CLAUDE.md`
- 파이프라인 구조: `.claude/docs/architecture.md`
- 제약: `.claude/rules/core.md` 및 그 표가 가리키는 파일
```

### 모드 B: task-executor 위임

```
task-executor 에이전트로 다음 task 파일을 실행하세요.

파일: .claude/tasks/todo/tasks-<name>-push<N>.md
내용: <파일 전체 내용>

지시사항:
- 미완료([ ]) 작업을 순서대로 실행
- 하위 작업 하나 = 커밋 하나. 묶지 말 것
- task 파일에 적힌 검증 작업을 실제로 수행한 뒤에만 체크
- 오류 시 새 번호의 수정 하위 작업을 추가한 뒤 해결
- git push 금지
```

## 실행 중

체크박스 진행 상황만 확인한다. 워커가 보고한 "완료" 를 그대로 믿지 않고, task 파일의 검증 항목이
실제로 체크됐는지 본다.

상위 항목은 하위가 전부 `[x]` 일 때만 `[x]` 다.

## Push 완료 처리

모든 항목이 `[x]` 가 된 후, 결과보고서를 만든다.

```bash
# 파일은 여기서 옮기지 않는다. done/ 정리는 task-cleaner 가 한다
```

결과보고서 `.claude/tasks/todo/result-<name>-push<N>.md`:

```markdown
# 결과보고서: <파일명>

> 완료일: <날짜>
> Push 범위: <기능 요약>

## 구현 요약

| 작업 | 상태 | 커밋 |
|---|---|---|
| 1.1 <작업명> | 완료 | `해시` |

## 생성·수정 파일

- `app/...` - <변경 내용>

## 검증 결과

| 대상 | 검증 | 결과 |
|---|---|---|
| 파서 | 픽스처 pytest | 통과 N건 |
| 실행 | 실사이트 1회 | `crawl_runs` 행 확인, 신규 K건 |

## 이슈 및 특이사항

- <발생한 오류와 해결법>
- <사이트에 대해 알아낸 것이 있으면 site-recipe 파일 경로>
```

보고서를 다 쓰면 정리는 `task-cleaner` 가 맡는다. 여기서 `done/` 으로 옮기지 않는다 —
한 기능의 PRD·task·보고서를 한 폴더로 묶는 것이 그 스킬의 일이다.

## 종료 처리

```bash
rm -f .claude/.task-running
```

sentinel 을 지워야 Stop 훅이 중단을 허용한다. 최종 보고 후 종료한다.

## 하지 않는 것

- 검증하지 않은 항목 체크하기
- 푸시. 사용자가 한다
- 범위 확대. 할 만한 일이 보이면 diff 가 아니라 보고서에 쓴다
- 선행 조건이 막힌 Push 를 그냥 시작하기
