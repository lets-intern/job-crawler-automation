---
name: quality-check
description: "변경된 파이썬 파일에 포맷(ruff format)·린트(ruff check)·타입체크(mypy)·테스트(pytest)를 실행하고 결과를 보고한다. 사용자가 '품질 검사', '커밋 전 검사', '린트 돌려줘', '테스트 돌려줘', 'lint typecheck' 등을 말할 때 사용한다."
argument-hint: "[변경 기준 브랜치(기본: main) 또는 파일 경로]"
allowed-tools: Bash, Read, Glob
---

# 코드 품질 검사

변경 파일에 **ruff format → ruff check → mypy → pytest** 를 순서대로 돌리고, "내가 바꾼 코드"가
깨끗한지 판정한다. 커밋 전에 쓴다.

판정은 **"전체 0"이 아니라 "변경 파일에 새 에러 0"** 이다. 기존 에러는 보고만 한다.

## 0. 변경 범위 산정

```bash
BASE="${1:-$(git merge-base HEAD main 2>/dev/null || echo main)}"
{ git diff --name-only "$BASE"...HEAD -- '*.py'
  git diff --name-only -- '*.py'
  git ls-files --others --exclude-standard -- '*.py'
} | sort -u > /tmp/qc_changed.txt
wc -l < /tmp/qc_changed.txt
```

0개면 "검사할 변경 없음" 으로 보고하고 끝낸다.
셸은 zsh 다. `mapfile` 이 없으므로 파일 목록은 `xargs` 로 넘긴다.

## 1. 포맷

```bash
xargs ruff format < /tmp/qc_changed.txt
```

재포맷된 파일이 있으면 목록과 함께 "포맷 수정됨, 커밋 필요" 로 보고한다.

## 2. 린트

```bash
xargs ruff check < /tmp/qc_changed.txt
```

변경 파일 error 0 이 통과 조건이다.

## 3. 타입체크

```bash
xargs mypy < /tmp/qc_changed.txt 2>&1 | tail -20
```

기존 파일 전체 에러는 참고로만 적는다. 차단 사유는 변경 파일에 걸린 에러뿐이다.

## 4. 테스트

```bash
pytest -q -m "not live"
```

`live` 마커가 붙은 테스트는 실서버를 때린다. 기본 실행에서 제외하고, 사용자가 명시적으로 요청할
때만 따로 돌린다 (`rules/crawling.md`).

파서를 건드렸으면 픽스처 테스트가 반드시 포함되어야 한다. 없으면 없다고 보고한다.

## 판정 기준

| 단계 | 통과 조건 |
|---|---|
| 포맷 | ruff format 후 재포맷 없음. 재포맷 시 커밋 필요 안내 |
| 린트 | 변경 파일에 ruff error 0 |
| 타입 | 변경 파일에 mypy error 0 (전체 기존 error 는 참고) |
| 테스트 | `-m "not live"` 전체 통과 |

## 출력 형식

```
## 품질 검사 결과 (기준 <BASE>, 변경 N파일)
- 포맷: 정상 / M개 재포맷됨(커밋 필요)
- 린트: 변경 파일 error 0
- 타입: 변경 파일 error 0 (전체 기존 error J)
- 테스트: K passed, 0 failed
[불통과 시] 고친 파일과 남은 에러
```

## 하지 않는 것

- 신규 파일 생성. 수정은 "변경 파일의 새 에러 해결" 목적에 한한다
- 기존 warning/error 임의 수정. 보고만 한다
- 테스트를 통과시키려고 단언을 약화시키기
- 커밋·푸시. 포맷으로 파일이 바뀌면 커밋 필요하다고 안내만 한다
