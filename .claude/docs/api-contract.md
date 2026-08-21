# 제공 API 계약

채용공고 사이트(별도 서비스)가 정규화된 데이터를 가져가는 경계면이다.
이 문서와 구현이 어긋나면 소비 측이 조용히 데이터를 못 받는다. **한 커밋에서 같이 고친다.**

## 방식

1차는 폴링이다. 소비 측이 주기적으로 조회하고, 받은 만큼 표시를 남긴다.
웹훅은 재시도·중복·실패 처리가 전부 추가 구현이라 1차 범위 밖이다.

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
      "source_url": "https://...",
      "normalized_at": "2026-08-21T10:00:00Z"
    }
  ],
  "next_cursor": "...",
  "has_more": true
}
```

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
| 400 | `invalid_cursor` | `cursor` 를 읽을 수 없다 |
| 422 | `invalid_updated_after` | `updated_after` 가 ISO8601 시각이 아니다 |

본문 모양:

```json
{ "detail": { "reason": "invalid_cursor", "message": "cursor 를 읽을 수 없다" } }
```

`updated_after` 에 타임존이 없으면 UTC 로 본다. 저장된 값이 UTC 라, 로컬 시각으로 해석하면
소비 측이 시차만큼 받지 못한 구간이 생긴다.

## 계약을 바꿀 때

필드 추가는 안전하다. 필드 삭제·이름 변경·타입 변경은 소비 측을 깨뜨린다.
바꾸기 전에 사용자에게 소비 측 대응 여부를 확인한다.

`normalized_at` 의 의미를 바꾸면 안 된다. 소비 측의 폴링 커서가 이 값에 걸려 있다.
