# Tasks: fields-and-logo - Push 5

> PRD: `.claude/tasks/todo/prd-fields-and-logo.md`
> Push 범위: MinIO 를 붙이고 어드민에서 엔드포인트를 바꿀 수 있게 한다
> 상태: 진행 중

## 관련 파일

- `docker-compose.yml`, `docker-compose.override.yml` - 로컬 구성
- `app/notify/settings.py` - `app_settings` 에 키로 넣는 저장소의 본보기
- `app/api/ui_notify.py` - 저장한 값으로 테스트하는 순서의 본보기
- `app/api/import_data.py` 의 `_merge_llm_settings` - 키가 스냅샷에 딸려 나가는 방식
- `app/api/settings.py`, `app/templates/pages/settings_export.html` - 내보내기 경고
- `.claude/rules/core.md`, `.claude/rules/crawling.md` - 이 Push 가 고치는 규칙

## 선행 조건

- 없음. Push 1~4 와 서로 기다리지 않는다
- 결정 필요: 로고 파일 형식과 크기 상한. 5.4 에서 정한다

## 작업

- [ ] 5.0 저장소
    - [x] 5.1 **규칙 파일 두 개를 먼저 고친다.** `.claude/rules/core.md` 는 두 번째 컨테이너를
          들이지 말라고 하고, `.claude/rules/crawling.md` 는 우리가 운영하는 서비스가
          `app/notify/` 하나뿐이라고 한다. 둘 다 이 Push 로 거짓이 된다. 예외와 근거를 적는다.
          규칙을 어기고 지나가는 것이 아니라 고치고 지나간다
        - [x] 5.1.V 검증(화면 아님): 두 파일에 예외와 날짜와 근거가 적혀 있는지 읽어 확인
    - [x] 5.2 `docker-compose.yml` 에 MinIO 서비스와 볼륨을 더한다. 운영
          (`docker-compose.coolify.yml`)은 이 Push 에서 건드리지 않는다 — 로컬이 도는 것을
          본 뒤에 정한다
        - [x] 5.2.V 검증(로컬): `local-env` 로 띄워 MinIO 콘솔에 닿는지 확인.
              `docker compose up -d minio` 후 콘솔(:9001) 200, S3 헬스(:9000) 200,
              api 컨테이너에서 `http://minio:9000` 200
    - [x] 5.3 설정 저장소. `s3_endpoint`·`s3_region`·`s3_bucket`·`s3_access_key`·
          `s3_secret_key`·`s3_public_base` 를 `app_settings` 에 넣는다. 새 표를 만들지 않는다.
          주소는 `http`/`https` 여야 하고 버킷은 비어 있을 수 없다
        - [x] 5.3.V 검증(스키마): 저장하고 다시 읽어 값이 그대로인지, 범위 밖 값이 사유와 함께
              거절되는지 pytest. `tests/test_storage_settings.py` 15개 통과
    - [ ] 5.4 업로드 클라이언트. S3 호환 SDK 하나를 쓰고 `endpoint_url` 이 비면 SDK 가 지역으로
          주소를 만들게 둔다 — 주소 형식을 운영자가 고르게 하지 않는다. 받는 것은 이미지뿐이고
          크기 상한을 둔다. 형식과 상한을 여기서 정해 화면에 적는다
        - [ ] 5.4.V 검증(로컬): 로컬 MinIO 에 올리고 `s3_public_base` 주소로 열리는지 확인
    - [ ] 5.5 연결 확인. 작은 객체를 넣고, 읽고, 지운다. 어디서 실패했는지 문장으로 적는다 —
          키가 틀린 것과 버킷이 없는 것과 주소에 못 닿는 것은 고치는 방법이 다르다.
          **저장된 값으로 확인한다.** 순서는 저장하고 나서 확인이다
        - [ ] 5.5.V 검증(로컬): 키를 일부러 틀리고 버킷을 일부러 지워, 사유가 갈려 나오는지 확인
    - [ ] 5.6 설정 화면. 운영 설정의 하위 메뉴에 저장소 구역을 더한다
          (`app/api/ui.py` 의 `SETTINGS_NAV`)
        - [ ] 5.6.V 검증(화면): 저장하고 새로 고쳐 값이 남고, 연결 확인이 도는지 확인
    - [ ] 5.7 내보내기 화면의 경고에 저장소 키를 더한다. LLM 키가 이미 스냅샷에 실려 나가고
          화면이 그것을 알린다. 경고에 없는 비밀은 없는 것으로 읽힌다
        - [ ] 5.7.V 검증(화면): 내보내기 화면에 저장소 키가 경고에 적혀 있는지 확인
