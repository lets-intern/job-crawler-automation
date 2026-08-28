# Tasks: side-workflows - Push 7

> PRD: `.claude/tasks/todo/prd-side-workflows.md`
> Push 범위: 스프링 전달 설정과 화면. **아무것도 보내지 않는다**
> 상태: 완료 (2026-08-29)

## 관련 파일

- `app/notify/settings.py` - `app_settings` 에 키로 넣는 저장소의 본보기
- `app/api/ui_notify.py` - 설정 화면 조각 라우트의 본보기. 주소를 `/ui/settings/` 아래 두지
  않는 이유가 그 파일 머리말에 있다
- `app/templates/fragments/notify_form.html` - 폼의 본보기
- `.claude/docs/api-contract.md` - 지금 계약은 폴링이다. 자격증명은 아직 정하지 않았다

## 선행 조건

- Push 1 완료 (`kind='deliver'` 행을 만들 수 있어야 한다)
- Push 5 완료 (화면에 붙일 자리)
- 결정 필요: 스프링이 받는 본문 형식. **정해지지 않아도 이 Push 는 진행한다** — 주소·메서드·
  인증·건수를 넣어 둘 자리만 만들고 형식은 다루지 않는다

## 작업

- [x] 7.0 전달 설정
    - [x] 7.1 `app/deliver/settings.py`. `deliver_url`, `deliver_method`,
          `deliver_auth_header`, `deliver_batch_size` 를 `app_settings` 에 넣는다.
          새 표를 만들지 않는다
        - [x] 7.1.V 검증(스키마): `tests/test_deliver_settings.py` — 저장·재조회 왕복 pytest 통과
    - [x] 7.2 값 검증. 주소는 `http`/`https` 여야 하고, 메서드는 `POST`/`PUT` 둘뿐이며,
          건수는 1 이상이다. 거절 사유를 문장으로 돌려준다
        - [x] 7.2.V 검증(스키마): `tests/test_deliver_settings.py` — 주소·메서드·건수 범위 밖 값이
              `DeliverSettingError` 로 거절되고, 거절 시 기존 저장값이 그대로인지 pytest 통과
    - [x] 7.3 설정 화면. `/side` 안의 한 구역으로 둔다. **"아직 보내지 않는다" 를 화면에
          낱말로 적는다.** 연결 테스트 단추도 두지 않는다 — 없는 기능을 있는 것처럼 보이게 하는
          단추가 가장 나쁘다
        - [x] 7.3.V 검증(화면): `tests/test_ui_deliver.py` pytest 4건 통과 (문구 노출, 테스트 전송
              단추 부재, 저장 후 재조회 시 값 유지, 잘못된 값 거절) + 실컨테이너 curl 로 PUT 저장 후
              GET 재조회에서 `value="https://board.example.com/ingest"` 등 확인
    - [x] 7.4 `kind='deliver'` 워크플로우를 만들고 실행 시점·대상 범위를 저장할 수 있게 한다.
          실행 단추는 비활성이고 그 이유를 옆에 적는다
        - [x] 7.4.V 검증(화면): `tests/test_ui_side.py` 의 두 테스트로 확인 — 전달 카드는
              `hx-post=".../run"` 대신 "지금 실행 (아직 보낼 수 없음)" 문구만 나오고, 분류 카드는
              실행 단추가 그대로 있음. 실컨테이너에서 `kind=deliver` 워크플로우 생성 후 동일하게 확인
    - [x] 7.5 `delivered_at` 을 이 Push 의 어느 경로도 쓰지 않는다는 것을 테스트로 못박는다
          (`.claude/rules/data-safety.md`)
        - [x] 7.5.V 검증(제공 API): 기존 `tests/test_delivered_isolation.py::
              test_only_the_delivery_endpoint_writes_delivered_at` 가 `app/` 전체를 정적으로
              스캔해 `delivered_at` 에 쓰는 파일이 `app/api/jobs.py` 하나뿐임을 확인 — 이번 Push 가
              추가한 `app/deliver/settings.py`, `app/api/ui_deliver.py` 도 포함해 재실행, 통과
