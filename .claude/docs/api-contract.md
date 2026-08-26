# 제공 API 계약

채용공고 사이트(별도 서비스)가 정규화된 데이터를 가져가는 경계면이다.
이 문서와 구현이 어긋나면 소비 측이 조용히 데이터를 못 받는다. **한 커밋에서 같이 고친다.**

## 방식

1차는 폴링이다. 소비 측이 주기적으로 조회하고, 받은 만큼 표시를 남긴다.
웹훅은 재시도·중복·실패 처리가 전부 추가 구현이라 1차 범위 밖이다.

## 이 API 는 잠겨 있다

`/api/jobs` 와 `/api/jobs/delivered` 는 운영 화면과 같은 자물쇠 뒤에 있다. 쿠키 없이 부르면
`401` 이고 본문은 `{"detail": "인증이 필요하다"}` 다 (`app/api/auth.py`).

소비 측인 채용공고 사이트는 아직 붙지 않았다. 그때까지 열어 두면 정규화된 공고가 주소를 아는
누구에게나 그대로 나가므로, 붙지 않은 동안은 잠가 둔다.

**소비 측에 자격증명을 어떻게 줄지는 아직 정하지 않았다.** 붙일 때 정한다. 지금의 비밀번호
하나짜리 자물쇠는 운영자가 화면에 들어가라고 만든 것이라, 서버끼리 부르는 데 그대로 쓰기에는
맞지 않는다. 정할 때 이 절을 고치고 같은 커밋에서 구현도 고친다.

후보만 적어 둔다. 고르지 않았다.

| 방식 | 성질 |
|---|---|
| 소비 측 전용 토큰을 헤더로 | 화면 잠금과 분리된다. 토큰을 어디에 두고 어떻게 바꿀지 정해야 한다 |
| 같은 비밀번호로 로그인해 쿠키를 들고 폴링 | 새로 만들 것이 없다. 운영자 비밀번호를 서버에 심게 된다 |
| 네트워크로만 가른다 | 서버가 같은 망에 있을 때만 쓴다. 지금 배포는 공개 URL 이라 해당되지 않는다 |

## 조회

```
GET /api/jobs?updated_after=<ISO8601>&limit=100&cursor=<opaque>
```

| 파라미터 | 설명 |
|---|---|
| updated_after | 이 시각 이후 `normalized_at` 인 건만 |
| limit | 기본 100, 상한 500. 상한을 넘긴 값은 거절하지 않고 500 으로 절삭한다. 1 미만도 1 로 올린다 |
| cursor | 이전 응답의 `next_cursor`. 없으면 처음부터 |

응답:

```json
{
  "items": [
    {
      "id": 1,
      "company": "회사명",
      "title": "공고 제목",
      "department": "부서",
      "deadline": "2026-09-30",
      "body": "본문",
      "requirements": "자격요건",
      "start_date": "2026-09-01",
      "job_category": "연구/개발",
      "employment_type": "정규직",
      "career_level": "신입",
      "work_location": "경기 수원시",
      "headcount": "0명",
      "duties": "주요 업무",
      "preferred": "우대 조건",
      "hiring_process": "전형 절차",
      "etc_info": "기타",
      "source_url": "https://...",
      "normalized_at": "2026-08-21T10:00:00Z"
    }
  ],
  "next_cursor": "...",
  "has_more": true
}
```

`start_date` 부터 `etc_info` 까지 열 개는 나중에 더한 필드다. **더하는 방향이고 기존 필드는
그대로 둔다** — 소비 측이 읽던 것이 사라지지 않는다. 특히 `deadline` 은 모집 마감일 그대로이고
`start_date` 가 그 짝이다. `deadline` 의 뜻은 바뀌지 않았다.

| 필드 | 뜻 |
|---|---|
| start_date | 모집 시작일 |
| job_category | 직군 |
| employment_type | 고용형태. 정규직 / 인턴 / 기간제 |
| career_level | 경력 구분. 신입 / 경력 |
| work_location | 근무지 |
| headcount | 모집인원 |
| duties | 주요 업무 |
| preferred | 우대 조건 |
| hiring_process | 전형 절차 |
| etc_info | 기타 |

**사이트가 그 값을 주지 않으면 `null` 이다.** 없는 값을 다른 값으로 채우지 않는다. 빈 값은
"이 사이트는 이 값을 주지 않는다" 는 사실이고, 소비 측은 그 필드를 그리지 않으면 된다.
어느 사이트가 어느 필드를 주는지는 `.claude/tasks/todo/tasks-split-body-push1.md` 의 표에 있다.

기존 여섯 필드 중에서도 `department` 는 대부분의 사이트가 주지 않아 `null` 인 경우가 많다.
`title`·`company`·`deadline`·`body`·`source_url` 은 채워진다.

커서 기반이다. 소비 측이 한 번 폴링을 걸러도 다음에 이어서 받는다. 오프셋 기반이면 그 사이 삽입된
행 때문에 건너뛰는 건이 생긴다.

`next_cursor` 는 항목이 하나라도 있으면 **마지막 페이지에서도 돌려준다.** 비워 보내면 소비 측이
읽은 위치를 잃고 다음 폴링에서 처음부터 다시 받는다. 더 받을 것이 있는지는 `has_more` 가 말한다.

항목이 없으면 `next_cursor` 는 요청에 실려 온 커서를 그대로 돌려준다. 위치가 뒤로 가지 않는다.

## 전달 확인

```
POST /api/jobs/delivered
{ "ids": [1, 2, 3] }
```

응답:

```json
{ "marked": 2, "already_delivered": 1, "missing": [99] }
```

| 필드 | 의미 |
|---|---|
| marked | 이번 요청으로 `delivered_at` 이 찍힌 건수 |
| already_delivered | 이미 찍혀 있어 건드리지 않은 건수 |
| missing | 존재하지 않는 id 목록 |

`delivered_at` 을 지금 시각으로 찍는다. 이미 찍힌 건은 덮어쓰지 않는다.

없는 id 가 섞여 있어도 배치 전체를 실패시키지 않는다. 실패시키면 소비 측이 나머지를 다시 받게
되고, 같은 데이터가 두 번 간다. 처리한 것은 처리하고 못 찾은 것만 `missing` 으로 보고한다.

이 엔드포인트만 `delivered_at` 을 쓴다. 크롤링·재정규화·수동 수정은 건드리지 않는다
(`.claude/rules/data-safety.md`).

## 오류 응답

조용히 처음부터 주지 않는다. 잘못된 요청을 빈 결과나 첫 페이지로 답하면 소비 측이 전량을 다시
받거나, 받지 못한 구간을 영영 모른다.

| 상태 | reason | 언제 |
|---|---|---|
| 401 | 없음 | 자격증명 없이 불렀다. 본문은 `{"detail": "인증이 필요하다"}` 다 |
| 400 | `invalid_cursor` | `cursor` 를 읽을 수 없다 |
| 422 | `invalid_updated_after` | `updated_after` 가 ISO8601 시각이 아니다 |

본문 모양:

```json
{ "detail": { "reason": "invalid_cursor", "message": "cursor 를 읽을 수 없다" } }
```

`updated_after` 에 타임존이 없으면 UTC 로 본다. 저장된 값이 UTC 라, 로컬 시각으로 해석하면
소비 측이 시차만큼 받지 못한 구간이 생긴다.

## 응답의 시각과 화면의 시각은 다르다

응답의 `normalized_at` 은 UTC 다. 운영 화면은 같은 행을 `DISPLAY_TIMEZONE`(기본 `Asia/Seoul`)
으로 옮겨 그리므로, 화면의 값이 응답보다 9시간 앞선다. 바뀌는 것은 화면에 그리는 순간뿐이고
저장된 값과 이 응답은 UTC 그대로다 (`app/api/ui.py` 의 `format_time`).

화면에서 본 시각을 `updated_after` 에 그대로 넣으면 그 시차만큼 건너뛴다. 커서에 넣을 값은
응답의 `normalized_at` 이다.

## 계약을 바꿀 때

필드 추가는 안전하다. 필드 삭제·이름 변경·타입 변경은 소비 측을 깨뜨린다.
바꾸기 전에 사용자에게 소비 측 대응 여부를 확인한다.

`normalized_at` 의 의미를 바꾸면 안 된다. 소비 측의 폴링 커서가 이 값에 걸려 있다.
