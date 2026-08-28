# Tasks: fields-and-logo - Push 2

> PRD: `.claude/tasks/todo/prd-fields-and-logo.md`
> Push 범위: 직무를 더한다. 제목에서 뽑는 자유 텍스트다
> 상태: 완료 (2026-08-28)

## 관련 파일

- `app/classify/schema.py` - `EXTRACT_FIELDS`, `Classification`
- `app/classify/classifier.py` - 프롬프트의 "뽑는 칸" 목록
- `app/classify/grounding.py` - 근거를 무엇에 돌려 보는가
- `app/classify/store.py` - 모델에 보내는 값
- `tests/fixtures/` - 열한 사이트의 상세

## 선행 조건

- Push 1 완료 (`job_category` 가 빠진 자리에 들어간다)
- 결정 필요: 제목에 없고 본문에만 직무가 있는 공고가 얼마나 되는지. 2.1 에서 재고 정한다.
  **쟀다.** 아래 표를 보라 — 제목에만 있는 것이 아홉 중 여섯이라 근거 검사에 제목을 넣었다
- 마이그레이션 번호는 `0017` 이다. 실행 시점의 마지막이
  `0016_drop_department_category_headcount.sql` 이었다

## 작업

- [x] 2.0 직무
    - [x] 2.1 픽스처로 잰다. 제목만으로 직무를 알 수 있는 공고가 몇 건인지, 제목에 없고
          본문에만 있는 것이 몇 건인지 표로 남긴다. 근거 검사에 본문까지 넣을지가 이 숫자로
          갈린다
        - [x] 2.1.V 검증(파서): 사이트별 건수를 표로 남긴다.
              `tests/test_job_role_source.py` 21건 통과. 표는 아래와 그 파일 첫머리에 있다
    - [x] 2.2 마이그레이션으로 `normalized_jobs.job_role` 을 더한다.
          `job_classifications.job_role` 과 `job_field_overrides.field_name` 의 CHECK 도
          같은 마이그레이션이 넓힌다 — 앞은 분류가 낸 값이 앉는 자리이고, 뒤가 없으면
          자유 텍스트인 이 칸을 사람이 고칠 수 없다
        - [x] 2.2.V 검증(스키마): 적용·역적용. `pytest tests/test_migrations.py` 74건 통과
    - [x] 2.3 `EXTRACT_FIELDS` 와 응답 스키마에 `job_role` 을 더하고 프롬프트에 칸 설명을
          적는다. 뽑는 칸이므로 있는 글자를 그대로 옮기고 없으면 빈 문자열이다.
          **제목을 프롬프트에 함께 보낸다** — 값이 제목에서 오는데 본문만 보내면 모델에게
          옮길 것이 없다. `store.read_title` 이 그 값을 읽고 실행이 넘긴다
        - [x] 2.3.V 검증(정규화): 픽스처로 값이 채워지는지, 없는 공고는 비는지 pytest.
              `tests/test_classify_body.py` 30건, `tests/test_classify_run.py` 18건 통과
    - [x] 2.4 **근거 검사의 대상에 제목을 더한다.** 지금은 본문에만 돌려 보는데, 직무는
          제목에서 오는 값이라 본문에만 돌리면 맞게 뽑은 값이 통째로 버려진다.
          2.1 이 잰 여섯 건이 그 근거다. 칸마다 볼 곳을 가르지 않고 제목과 본문을 한
          덩어리로 본다 — 가르면 그 표가 프롬프트의 칸 설명과 갈린다. 버린 이유의 문장도
          `제목에도 본문에도 없다` 로 바꿨다
        - [x] 2.4.V 검증(정규화): 제목에만 있는 직무가 버려지지 않고, 어디에도 없는 값은
              버려지는지 pytest. `tests/test_classify_body.py` 34건,
              `tests/test_classify_run.py` 19건 통과
    - [x] 2.5 화면 라벨과 계약 문서에 직무를 더한다. `NORMALIZED_FIELDS` 가 여기서 넓어진다
          — 그 상수가 곧 `OVERRIDABLE_FIELDS` 이고, 라벨 없이 넓히면 검수 화면이
          `KeyError` 로 선다. 그래서 2.3 이 아니라 이 커밋이다
        - [x] 2.5.V 검증(화면): 검수 표에 `직무` 열과 `review-cell-7-job_role` 이,
              모달에 `name="job_role"` 이 나오는 것을 렌더된 HTML 로 확인
              (`tests/test_ui_review_modal.py`). 제공 API 응답 키도
              `tests/test_api_jobs.py` 가 계약과 대조한다
    - [x] 2.6 (실행 중 추가) 검수 화면이 `normalized_jobs` 를 손으로 적은 컬럼 목록으로
          읽고 있어서(`app/api/review.py` 의 `_COLUMNS`) 새 칸이 그 행에 없었다. 저장을
          누르면 `job[field]` 가 `IndexError` 로 터진다 — 열이 안 보이는 것이 아니라
          모달 저장 경로 전체가 선다. 그 목록에 `job_role` 을 더했다
        - [x] 2.6.V 검증(화면): `pytest tests/test_ui_review_modal.py` 15건 통과.
              2.5 없이는 스위트가 통과하지 않아 같은 커밋에 들어간다

## 2.1 이 잰 것 (2026-08-28)

`tests/fixtures/` 의 상세 열한 건. 판정은 눈이 아니라 `missing_lines` 가 했다
(`app/classify/grounding.py`) — 근거 검사가 실제로 통과시키는 것과 표가 어긋나면 셈이 뜻을
잃는다.

| 사이트 | 제목이 말하는 직무 | 제목 | 본문 |
|---|---|---|---|
| 한화 | LIFEPLUS TV 마케팅 기획 및 운영 | 있다 | 있다 |
| 롯데그룹 | 전기 | 있다 | 있다 |
| 두산 | 광고영업 | 있다 | 있다 |
| 삼성 | R&D분야 | 있다 | 없다 |
| 현대자동차 | 항공용 전기추진시스템 고장진단 SW 개발 | 있다 | 없다 |
| SK | Global IT 통합 및 기획 | 있다 | 없다 |
| 네이버 | 의료 도메인에서의 Agentic RAG 연구 및 개발 | 있다 | 없다 |
| 카카오 | 카카오비즈니스 파트너 플랫폼 PM | 있다 | 없다 |
| 우아한형제들 | 파트너 영업 Specialist | 있다 | 없다 |
| LG | 없다 | 해당없음 | 해당없음 |
| 토스 | 없다 | 해당없음 | 해당없음 |

제목이 직무를 말하는 곳 아홉, 그중 본문이 같은 글자를 되풀이하는 곳 셋, **제목에만 있는 곳
여섯.** 나머지 둘(LG·토스)은 여러 직무를 한 공고에 묶은 통합 공고라 제목이 직무를 말하지
않는다 — 그 둘의 직무는 빈 칸이 맞다.

SK 는 경계다. 본문에 `Global IT통합` 은 있고 `Global IT 통합 및 기획` 은 없다. 제목이 말하는
직무를 그대로 옮기면 버려지고 짧게 잘라 옮기면 남는데, 어디까지 자르라고 시킬 수 있는 일이
아니라 제목에만 있는 쪽으로 셌다.

**이 숫자가 2.4 를 정했다.** 근거 검사를 본문에만 돌리면 아홉 중 여섯, 셋 중 둘이 버려진다.
제목을 근거 검사 대상에 반드시 넣는다.
