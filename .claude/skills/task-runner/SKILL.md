---
name: task-runner
description: "todo 에 있는 task 파일을 순서대로 실행하고 체크박스를 갱신한다. 사용자가 '작업 시작해줘', 'task 실행', '남은 작업 진행해줘', '이어서 해줘' 등을 요청할 때 사용한다."
argument-hint: "[task 파일 경로 (없으면 todo 최신)]"
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# Task 실행

task 파일 하나를 위에서 아래로 실행한다. 하위 작업 하나 = 커밋 하나.

## 시작 전

```bash
git branch --show-current
```

`main` 이면 브랜치부터 만든다 (`rules/git-safety.md`).

실행 중임을 표시하는 센티넬을 만든다. Stop 훅이 이걸 보고 미완료 작업이 남았을 때 세션을 이어간다.

```bash
touch .claude/.task-running
```

## 실행 루프

하위 작업 하나마다:

1. 구현한다
2. task 파일에 적힌 검증 작업을 실제로 수행한다
3. 커밋한다 (브랜치 확인 후)
4. 체크박스를 `[x]` 로 바꾼다
5. 다음으로 간다

여러 하위 작업을 한 커밋에 묶지 않는다. 묶으면 깨졌을 때 bisect 지점이 없다.

상위 항목은 하위가 전부 `[x]` 일 때만 `[x]` 로 바꾼다.

## 실패했을 때

고친 내용을 **새 번호의 하위 작업으로 파일에 추가하고** 고친 뒤 체크한다. task 파일은 무엇을
했는지의 기록이고, 여기에는 무엇이 잘못됐었는지도 포함된다.

## 위임 판단

파일 3개 미만 단일 영역이면 직접 한다. 그 이상이면 `task-executor` 에게 파일 단위로 넘긴다.
영역이 갈리면 (`selector-worker`, `crawler-worker`, `api-worker`, `ui-worker`) 해당 워커에게 준다.

## 끝났을 때

```bash
rm -f .claude/.task-running
```

파일을 `.claude/tasks/done/` 으로 옮기고 결과를 한 문단으로 남긴다.

## 하지 않는 것

- 검증하지 않은 항목 체크하기
- 푸시. 사용자가 한다
- 범위 확대. 할 만한 일이 보이면 diff 가 아니라 보고에 쓴다
