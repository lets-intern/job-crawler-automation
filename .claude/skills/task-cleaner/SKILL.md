---
name: task-cleaner
description: "완료된 task 파일과 관련 자료(PRD, 결과보고서, 스크린샷)를 기능명 폴더로 done/ 에 아카이브합니다. 사용자가 'task 정리', '작업 정리', '태스크 정리', '파일 정리해줘', 'clean tasks' 등을 요청할 때 사용합니다."
argument-hint: "[branch-name 또는 feature-name]"
disable-model-invocation: true
allowed-tools: Read, Bash, Glob, Grep
---

# Task Cleaner — 작업 파일 정리

완료된 task 파일, PRD, 결과보고서를 `.claude/tasks/done/` 하위의 **기능명 폴더**로 묶는다.

한 기능에 관한 것이 한 폴더에 모여 있어야 나중에 "그때 뭘 했더라" 를 한 번에 읽을 수 있다.

## 폴더 구조

```
.claude/tasks/
├── todo/                        진행 중인 task 파일만 남는다
├── done/
│   ├── <기능명>/
│   │   ├── prd-*.md
│   │   ├── tasks-*-push1.md
│   │   ├── result-*-push1.md
│   │   └── <스크린샷 등>
│   └── <다른 기능>/
└── memos/
```

## 정리 프로세스

### 1. 폴더 이름 결정

우선순위:

1. 사용자가 인자로 지정한 이름 → 그대로 쓴다
2. 현재 Git 브랜치명 → `git branch --show-current`
   - 티켓 prefix 는 떼도 된다. 단, 사용자에게 확인 후 결정한다
3. task/PRD 파일명에서 추출 → `prd-job-crawler.md` → `job-crawler`

### 2. 정리 대상 식별

```bash
ls -1 .claude/tasks/todo/*.md 2>/dev/null
```

| 파일 종류 | 정리 조건 |
|---|---|
| `tasks-*.md` | **모든 체크박스가 `[x]`** 인 경우 |
| `result-*.md` | 짝이 되는 task 파일이 완료된 경우 |
| `prd*.md` | 관련 task 파일이 **전부** 완료된 경우 |
| 스크린샷·CSV·PDF | 관련 task/PRD 와 함께 이동 |

미완료 판정은 눈으로 하지 않는다.

```bash
grep -c "\[ \]" .claude/tasks/todo/tasks-<name>-push<N>.md
```

0 이 아니면 이동하지 않는다.

**PRD 는 Push 파일이 하나라도 남아 있으면 옮기지 않는다.** PRD 를 먼저 치우면 남은 Push 가
근거 문서를 잃는다.

### 3. 이동

```bash
mkdir -p .claude/tasks/done/<폴더명>
git mv .claude/tasks/todo/<대상파일> .claude/tasks/done/<폴더명>/ 2>/dev/null \
  || mv .claude/tasks/todo/<대상파일> .claude/tasks/done/<폴더명>/
```

git 이 추적 중인 파일은 `git mv` 를 쓴다. 그냥 `mv` 하면 삭제 + 신규로 잡혀 이력이 끊긴다.

### 4. 사이트 레시피 확인

이 프로젝트 전용 단계다. 결과보고서에 사이트에 대해 알아낸 것이 적혀 있는데
`.claude/site-recipes/` 에 반영되지 않았으면, 아카이브하기 전에 알린다.

```bash
grep -l "site-recipe\|레시피" .claude/tasks/todo/result-*.md 2>/dev/null
ls .claude/site-recipes/
```

task 는 아카이브되면 잘 안 읽힌다. 사이트에 대한 지식은 레시피에 남아야 다음에 쓰인다.
옮기는 것을 막지는 않되, 반영이 안 됐으면 반드시 보고한다.

### 5. 보고

```
정리 완료: done/<폴더명>/

이동:
- prd-job-crawler.md
- tasks-job-crawler-push1.md (완료)
- result-job-crawler-push1.md

남김:
- tasks-job-crawler-push2.md (미완료 3건)

주의:
- result-push1.md 에 사이트 관련 발견이 있으나 site-recipes/ 에 없음
```

## 규칙

- `[ ]` 가 남은 파일은 이동하지 않는다
- `done/` 에 같은 이름의 파일이 이미 있으면 덮어쓰지 않고 사용자에게 확인한다
- `todo/`, `done/` 디렉토리 자체는 삭제하지 않는다
- 파일 내용을 고치지 않는다. 이동만 한다
- 이동 후 커밋은 하지 않는다. 사용자가 한다
