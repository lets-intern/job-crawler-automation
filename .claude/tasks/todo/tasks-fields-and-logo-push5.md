# Tasks: fields-and-logo - Push 5

> PRD: `.claude/tasks/todo/prd-fields-and-logo.md`
> Push 범위: MinIO 를 붙이고 어드민에서 엔드포인트를 바꿀 수 있게 한다
> 상태: 완료 (2026-08-28)

## 관련 파일

- `docker-compose.yml`, `docker-compose.override.yml` - 로컬 구성
- `app/notify/settings.py` - `app_settings` 에 키로 넣는 저장소의 본보기
- `app/api/ui_notify.py` - 저장한 값으로 테스트하는 순서의 본보기
- `app/api/import_data.py` 의 `_merge_llm_settings` - 키가 스냅샷에 딸려 나가는 방식
- `app/api/settings.py`, `app/templates/pages/settings_export.html` - 내보내기 경고
- `.claude/rules/core.md`, `.claude/rules/crawling.md` - 이 Push 가 고치는 규칙

## 선행 조건

- 없음. Push 1~4 와 서로 기다리지 않는다
- 결정 완료(2026-08-28, 5.4): 받는 형식은 **PNG, JPEG, WebP** 이고 상한은 **2MB**
  (`app/storage/s3.py` 의 `ACCEPTED`, `MAX_IMAGE_BYTES`)
    - SVG 는 받지 않는다. 텍스트라 앞 바이트로 형식을 가릴 수 없고, 스크립트를 품은 SVG 가
      우리 공개 주소에서 열리면 그것이 곧 XSS 다
    - 형식은 파일 이름이 아니라 앞 바이트로 정하고, 올라가는 확장자도 거기서 나온다
    - 2MB 는 로고 한 장(200px 안팎 PNG 는 수십 KB)에 넉넉하면서 사진을 잘못 고른 것은 막는
      선이다

## 작업

- [x] 5.0 저장소
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
    - [x] 5.4 업로드 클라이언트. S3 호환 SDK 하나를 쓰고 `endpoint_url` 이 비면 SDK 가 지역으로
          주소를 만들게 둔다 — 주소 형식을 운영자가 고르게 하지 않는다. 받는 것은 이미지뿐이고
          크기 상한을 둔다. 형식과 상한을 여기서 정해 화면에 적는다
        - [x] 5.4.V 검증(로컬): 로컬 MinIO 에 올리고 `s3_public_base` 주소로 열리는지 확인.
              `logos` 버킷에 PNG 를 올려 `http://localhost:9000/logos/live-check.png` 가
              200 `image/png` 로 열렸다. 공개 주소로 열리려면 버킷에 익명 읽기 정책이
              있어야 한다 — 콘솔에서 운영자가 준다.
              픽스처 몫은 `tests/test_storage_upload.py` 16개 통과
    - [x] 5.5 연결 확인. 작은 객체를 넣고, 읽고, 지운다. 어디서 실패했는지 문장으로 적는다 —
          키가 틀린 것과 버킷이 없는 것과 주소에 못 닿는 것은 고치는 방법이 다르다.
          **저장된 값으로 확인한다.** 순서는 저장하고 나서 확인이다
        - [x] 5.5.V 검증(로컬): 키를 일부러 틀리고 버킷을 일부러 지워, 사유가 갈려 나오는지 확인.
              로컬 MinIO 로 여섯 경우를 돌려 사유가 전부 갈렸다 — 정상 `ok`,
              비밀 키 틀림 `bad_credentials`(SignatureDoesNotMatch), 접근 키 틀림
              `bad_credentials`(InvalidAccessKeyId), 없는 버킷 `no_bucket`, 닫힌 포트
              `unreachable`, 저장 전 `not_configured`.
              버킷은 지우는 대신 없는 이름을 줬다 — 저장소가 주는 응답이 같은
              `NoSuchBucket` 이고, 이미 올린 객체를 잃지 않는다.
              확인이 만든 객체는 남지 않았다(버킷 목록에 `_check/` 없음).
              픽스처 몫은 `tests/test_storage_check.py` 10개 통과
    - [x] 5.6 설정 화면. 운영 설정의 하위 메뉴에 저장소 구역을 더한다
          (`app/api/ui.py` 의 `SETTINGS_NAV`)
        - [x] 5.6.V 검증(화면): 저장하고 새로 고쳐 값이 남고, 연결 확인이 도는지 확인.
              로컬 도커로 띄운 화면에서 저장 → 새로 고침에 여섯 값이 그대로 남았고,
              연결 확인이 `버킷 logos 에 넣고 읽고 지웠다 (http://minio:9000)` 로 성공했다.
              없는 버킷으로 바꾸고 확인하면 `넣기에서 멈췄다 — 버킷 gone 이 저장소에 없다`
              가 나온다. 엔드포인트를 `minio:9000` 으로 저장하면 사유와 함께 거절된다.
              픽스처 몫은 `tests/test_ui_storage.py` 8개 통과
    - [x] 5.7 내보내기 화면의 경고에 저장소 키를 더한다. LLM 키가 이미 스냅샷에 실려 나가고
          화면이 그것을 알린다. 경고에 없는 비밀은 없는 것으로 읽힌다
        - [x] 5.7.V 검증(화면): 내보내기 화면에 저장소 키가 경고에 적혀 있는지 확인.
              `/settings/export` 경고에 `s3_access_key`, `s3_secret_key` 가 이름으로
              적혔다. 로컬 화면과 `tests/test_settings_export.py` 양쪽에서 확인
    - [x] 5.8 (수정) 하위 메뉴가 여섯이 되면서 `tests/test_settings_menu.py` 의
          `다섯이다` 단언이 깨졌다. 여섯으로 고치고 `/settings/storage` 를 목록에 넣는다.
          5.6 과 같은 커밋에 담는다 — 나누면 5.6 커밋 하나가 빨간 채로 남는다
        - [x] 5.8.V 검증(테스트): `pytest -q -m "not live"` 1626개 통과
    - [x] 5.9 (수정) 경고 첫 줄을 고치면서 `tests/test_settings_menu.py` 의
          `이 파일에 API 키가 들어 있습니다` 단언이 깨졌다. 새 문구로 고친다.
          5.7 과 같은 커밋에 담는다
        - [x] 5.9.V 검증(테스트): `pytest -q -m "not live"` 1631개 통과
