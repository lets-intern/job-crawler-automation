# Tasks: side-workflows - Push 7

> PRD: `.claude/tasks/todo/prd-side-workflows.md`
> Push 범위: 스프링 전달 설정과 화면. **아무것도 보내지 않는다**
> 상태: 진행 중

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

- [ ] 7.0 전달 설정
    - [ ] 7.1 `app/deliver/settings.py`. `deliver_url`, `deliver_method`,
          `deliver_auth_header`, `deliver_batch_size` 를 `app_settings` 에 넣는다.
          새 표를 만들지 않는다
        - [ ] 7.1.V 검증(스키마): 저장하고 다시 읽어 값이 그대로인지 pytest
    - [ ] 7.2 값 검증. 주소는 `http`/`https` 여야 하고, 메서드는 `POST`/`PUT` 둘뿐이며,
          건수는 1 이상이다. 거절 사유를 문장으로 돌려준다
        - [ ] 7.2.V 검증(스키마): 범위 밖 값이 사유와 함께 거절되는지 pytest
    - [ ] 7.3 설정 화면. `/side` 안의 한 구역으로 둔다. **"아직 보내지 않는다" 를 화면에
          낱말로 적는다.** 연결 테스트 단추도 두지 않는다 — 없는 기능을 있는 것처럼 보이게 하는
          단추가 가장 나쁘다
        - [ ] 7.3.V 검증(화면): 저장하고 새로 고쳐 값이 남아 있는지, 보내지 않는다는 문장이
              보이는지 확인
    - [ ] 7.4 `kind='deliver'` 워크플로우를 만들고 실행 시점·대상 범위를 저장할 수 있게 한다.
          실행 단추는 비활성이고 그 이유를 옆에 적는다
        - [ ] 7.4.V 검증(화면): 만들고 저장한 뒤 목록에 나오고 실행이 눌리지 않는지 확인
    - [ ] 7.5 `delivered_at` 을 이 Push 의 어느 경로도 쓰지 않는다는 것을 테스트로 못박는다
          (`.claude/rules/data-safety.md`)
        - [ ] 7.5.V 검증(제공 API): 설정 저장 전후로 `delivered_at` 이 하나도 바뀌지 않는지 pytest
