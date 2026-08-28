# Tasks: fields-and-logo - Push 3

> PRD: `.claude/tasks/todo/prd-fields-and-logo.md`
> Push 범위: 회사명을 모회사와 자회사 두 칸으로 가른다
> 상태: 진행 중

## 관련 파일

- `app/normalize/engine.py` - "회사명은 두 출처에서 하나를 고른다" 절과 `COMPANY_SOURCE`
- `migrations/0004_company.sql` - `company_source` 와 `crawlers.default_company` 가 생긴 자리
- `app/api/review_filter.py` - 회사 조건
- `seeds/normalization-rules.json` - `company` 에 규칙 4개가 있다
- `tests/fixtures/samsung-list-p1-20260825.html` - 계열사가 섞여 들어오는 사이트

## 선행 조건

- Push 1 완료

## 작업

- [ ] 3.0 회사명 가르기
    - [ ] 3.1 마이그레이션. `parent_company` 를 더하고 `company_source` 를 지운다. 두 칸으로
          갈리면 출처가 칸 이름으로 드러나 그 열이 할 말이 없어진다
        - [ ] 3.1.V 검증(스키마): 적용·역적용
    - [ ] 3.2 정규화의 회사명 해결 단계를 바꾼다. **합치기를 그만둔다.** `parent_company` 는
          크롤러의 `default_company`, 없으면 크롤러 이름이다. `company` 는 파싱값이고 없으면
          NULL 이다 — 모회사 이름으로 채우지 않는다
        - [ ] 3.2.V 검증(정규화): 파싱값이 있는 건과 없는 건 둘 다 픽스처로. 자회사가 빈 건에
              모회사 이름이 새어 들어가지 않는지 pytest
    - [ ] 3.3 `company` 에 걸린 규칙 4개는 그대로 자회사에 걸린다. `parent_company` 에는
          규칙을 태우지 않는다 — 크롤러에 적힌 값을 그대로 옮기는 칸이다
        - [ ] 3.3.V 검증(정규화): 모회사 값이 규칙을 타지 않고 그대로 나오는지 pytest
    - [ ] 3.4 검수 화면의 회사 열을 둘로 늘리고, 회사 조회 조건이 어느 칸을 보는지 정한다
        - [ ] 3.4.V 검증(화면): 계열사가 섞인 워크플로우를 골라 두 칸이 다르게 나오는지 확인
    - [ ] 3.5 계약 문서에 두 칸과 그 뜻을 적는다. 자회사가 비어 있을 수 있다는 것도 적는다
        - [ ] 3.5.V 검증(제공 API): 응답에 두 키가 나오고 뜻이 문서와 같은지 확인
