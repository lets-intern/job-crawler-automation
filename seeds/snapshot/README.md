# 수집 데이터 스냅샷

2026-08-23 에 실제로 돌려 쌓은 데이터다. 새 환경에서 화면이 무엇을 보여 주는지, 정규화가
어떤 값을 만드는지 보려고 저장소에 넣어 둔다.

| 테이블 | 건수 |
|---|---|
| raw_jobs | 148 |
| normalized_jobs | 148 |
| crawl_runs | 여러 건 |
| crawlers | 6 |
| workflows | 5 |
| normalization_rules | 25 |
| job_field_overrides | 2 |

파일 크기 724KB. 공고 한 건당 4KB 쯤이므로 1만 건이면 40MB 수준이다.

2026-08-23 갱신. 이전 판(138건)에서는 SK 공고 30건이 `normalized_jobs` 에 없었다.
마감일이 `July 15, 2026(Wed) ~ August 23, 2026(Sun)` 인데 `date_parse` 규칙이 한국식 형식만
시도해 예외가 났고, 그 공고가 통째로 빠졌다. `%B %d, %Y` 를 더해 재정규화한 것이 지금 판이다.

## 어디서 온 것인가

| 워크플로우 | 사이트 | 방식 |
|---|---|---|
| LG | careers.lg.com | 렌더, 목록 전용 (상세 링크 없음) |
| SK | skcareers.com | 렌더 |
| 현대자동차 | talent.hyundai.com | 렌더, 속성 + URL 템플릿 |
| 롯데그룹 | recruit.lotte.co.kr | 정적 |
| 삼성 | samsungcareers.com | 렌더, 목록 전용 |

한화(hanwhain.com)는 들어 있지 않다. 렌더된 DOM 어디에도 상세 파라미터가 없어 셀렉터로
풀리지 않는다. `../.claude/site-recipes/www-hanwhain-com.md` 에 이유가 있다.

## 쓰는 법

운영 DB 를 이것으로 덮지 않는다. 보고 싶으면 사본을 뜬다.

```bash
cp seeds/snapshot/jobs.db /tmp/look.db
DATABASE_PATH=/tmp/look.db .venv/bin/python -m uvicorn app.main:app --port 8001
```

이 파일에 대고 크롤링을 돌리지 않는다. `raw_jobs` 는 append-only 이고 여기 쌓인 것은
그때의 기록이다 (`../.claude/rules/data-safety.md`).

## 갱신

기록으로 두는 것이라 자주 갱신하지 않는다. 갱신할 일이 있으면 운영 볼륨에서 복사한다.

```bash
docker compose cp api:/data/jobs.db seeds/snapshot/jobs.db
```

넣기 전에 API 키나 연락처가 섞이지 않았는지 본다. `crawlers.selectors_json` 은 셀렉터만
담지만, 확인하지 않고 올리는 습관이 한 번 사고를 만든다.
