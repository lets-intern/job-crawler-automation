# 마이그레이션

스키마는 이 디렉터리의 파일로만 바뀐다. 라이브 테이블을 손으로 고치거나 DB 파일을 지워서 새
스키마를 얻지 않는다 (`../.claude/rules/data-safety.md`).

## 파일 형식

파일명은 `NNNN_snake_case_이름.sql` 이고 `NNNN` 이 적용 순서다. 한 파일에 up 과 down 을 모두
쓴다. 러너는 두 마커로 잘라 읽는다.

```sql
-- migrate:up
CREATE TABLE ...;

-- migrate:down
DROP TABLE ...;
```

`down` 은 `up` 이 만든 것만 정확히 되돌린다.

## 실행

```bash
python -m app.cli migrate status
python -m app.cli migrate up
python -m app.cli migrate down --steps 1
```

적용된 버전은 `schema_migrations` 테이블에 남는다. 이미 적용된 버전은 다시 적용되지 않고,
적용과 기록은 트랜잭션 하나로 묶인다.
