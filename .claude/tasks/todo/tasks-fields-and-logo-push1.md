# Tasks: fields-and-logo - Push 1

> PRD: `.claude/tasks/todo/prd-fields-and-logo.md`
> Push 범위: 부서·직군·모집인원 세 칸을 지운다
> 상태: 진행 중

## 관련 파일

- `migrations/0004_company.sql` - `ALTER TABLE ... DROP COLUMN` 의 본보기
- `app/normalize/rules.py` - `NORMALIZED_FIELDS`, `build_rule`
- `app/normalize/engine.py` - `OVERRIDABLE_FIELDS`
- `app/classify/schema.py` - `JUDGE_FIELDS`, `EXTRACT_FIELDS`, `JUDGE_CHOICES`
- `app/classify/classifier.py` - 프롬프트의 칸 설명
- `app/api/review_filter.py` - `FIELD_LABELS`, `EMPTY_NOTES`
- `.claude/docs/api-contract.md` - 필드 표
- `seeds/normalization-rules.json` - `department` 에 규칙 2개가 있다

## 선행 조건

- 없음
- 마이그레이션 번호는 `0016` 이다. 실행 시점의 마지막이 `0015_classification_evidence.sql`
  이었다
- **destructive 마이그레이션이다.** 시작 전에 운영 DB 를 `VACUUM INTO` 로 뜬다
  (`.claude/rules/data-safety.md`). 로컬 `data/jobs.db` 는 0바이트라 뜰 것이 없어 건너뛰었다.
  **운영 DB(Coolify)에는 실제 수집 데이터가 있으므로 배포 전에 백업이 필요하다**

## 작업

- [ ] 1.0 칸 셋 삭제
    - [x] 1.1 **`department` 에 걸린 정규화 규칙 2개를 먼저 지운다.** 남겨 두면 `load_rules`
          가 `RuleConfigError` 를 던져 **정규화 전체가 실패한다** — 지운 칸의 규칙은 읽히지
          않는 것이 아니라 읽다가 터진다. 마이그레이션 안에서 세 필드의 규칙 행을 지우고,
          되돌리기에 그 행을 다시 넣는 SQL 을 적는다
        - [x] 1.1.V 검증(스키마): 마이그레이션 적용 후 `load_rules` 가 예외 없이 도는지 pytest
    - [ ] 1.2 마이그레이션 작성. `normalized_jobs` 에서 `department`·`job_category`·
          `headcount` 를 지운다. 주석에 무엇을 지우고 어떻게 되돌리는지, 되돌려도 값은
          돌아오지 않는다는 것을 적는다
        - [ ] 1.2.V 검증(스키마): 적용·역적용. up 후 세 컬럼이 없고 나머지 행 수가 그대로인지
    - [ ] 1.3 `NORMALIZED_FIELDS` 와 분류 스키마에서 세 칸을 뺀다. `job_category` 는
          판정 칸이라 `JUDGE_FIELDS`·`JUDGE_CHOICES`·근거 칸까지 같이 빠진다. 프롬프트의
          칸 설명도 같이 지운다 — 프롬프트에만 남으면 모델이 스키마에 없는 칸을 낸다
        - [ ] 1.3.V 검증(정규화): 픽스처로 분류를 돌려 응답에 세 칸이 없고, 남은 칸이 그대로
              채워지는지 pytest
    - [ ] 1.4 화면 라벨과 빈 값 메모에서 세 칸을 뺀다. 검수 표의 열이 셋 줄어든다
        - [ ] 1.4.V 검증(화면): 검수 화면을 열어 열이 사라지고 나머지가 밀리지 않았는지 확인
    - [ ] 1.5 지운 칸의 `job_field_overrides` 행은 **지우지 않는다.** `apply_overrides` 가
          `OVERRIDABLE_FIELDS` 밖의 필드를 건너뛰므로 읽히지 않는다. 되돌릴 때 필요하다.
          그 사실을 마이그레이션 주석에 적는다
        - [ ] 1.5.V 검증(스키마): 지운 칸의 보정이 있는 건을 재정규화해도 실패하지 않는지 pytest
    - [ ] 1.6 `.claude/docs/api-contract.md` 에서 세 필드를 빼고, 같은 문서가 두 번 적어
          어긋나 있는 `employment_type`·`career_level` 표를 한쪽으로 정리한다
        - [ ] 1.6.V 검증(제공 API): 문서에 적힌 필드 이름과 실제 응답의 키가 같은지 확인
    - [x] 1.7 (실행 중 추가) 0016 의 역적용이 `department` 규칙 둘을 되살리는 탓에,
          0009 를 지나 되돌리는 `tests/test_migrations.py` 의 검사 둘이 남의 행까지 세고
          있었다. 두 검사가 자기가 넣은 행(`note = '메모'`)만 보게 좁힌다
        - [x] 1.7.V 검증(스키마): `pytest tests/test_migrations.py`

    - [x] 1.8 (실행 중 추가) 스냅샷 가져오기가 지운 칸의 규칙을 그대로 들여온다.
          `seeds/snapshot/jobs.db` 는 0016 이전 파일이라 `department` 규칙 둘이 들어 있고,
          그것이 들어오면 `load_rules` 가 터져 **그 파일의 공고가 한 건도 정규화되지 않는다.**
          `_merge_rules` 가 `NORMALIZED_FIELDS` 밖의 칸을 건너뛴 것으로 세게 한다 —
          화면(`build_rule`)으로는 저장할 수 없는 규칙이라 파일로 들어오는 길만 열어 둘 이유가
          없다
        - [x] 1.8.V 검증(정규화): 스냅샷을 올려 `normalized_jobs` 가 0건이 아닌지 pytest

## 실행 순서를 바꾼 것

파일에 적힌 번호는 1.1 -> 1.6 이지만 커밋은 1.1 -> 1.3 -> 1.4 -> 1.6 -> 1.2 -> 1.5 순으로
했다. 1.2 가 컬럼을 지우는 순간 그 컬럼을 읽는 코드가 전부 깨지므로, 마이그레이션을 먼저
커밋하면 그 커밋에서 스위트가 통째로 실패해 bisect 지점이 되지 못한다. 코드가 그 칸을 놓은
뒤에 컬럼을 지우면 커밋마다 스위트가 통과한다. 번호와 내용은 그대로다.

`app/api/jobs.py` 는 1.6 에서 함께 고쳤다. 그 파일과 `.claude/docs/api-contract.md` 는 같은
커밋에서 바뀐다고 파일 첫머리가 정하고 있다.
