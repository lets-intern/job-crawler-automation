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
| limit | 기본 100, 상한 500 |
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

## 전달 확인

```
POST /api/jobs/delivered
{ "ids": [1, 2, 3] }
```

`delivered_at` 을 지금 시각으로 찍는다. 이미 찍힌 건은 덮어쓰지 않는다.

이 엔드포인트만 `delivered_at` 을 쓴다. 크롤링·재정규화·수동 수정은 건드리지 않는다
(`.claude/rules/data-safety.md`).

## 계약을 바꿀 때

필드 추가는 안전하다. 필드 삭제·이름 변경·타입 변경은 소비 측을 깨뜨린다.
바꾸기 전에 사용자에게 소비 측 대응 여부를 확인한다.

`normalized_at` 의 의미를 바꾸면 안 된다. 소비 측의 폴링 커서가 이 값에 걸려 있다.
