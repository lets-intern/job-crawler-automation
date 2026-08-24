-- 수집 방식을 목록과 상세로 나눠 저장한다.
--
-- 지금까지는 `render_mode` 하나가 크롤러 전체의 경로를 정했다. LG 처럼 목록은 JSON API 로
-- 오고 상세는 다른 방식이어야 하는 사이트가 나오면서 그 하나로는 표현할 수 없게 됐다.
-- 목록과 상세는 각각 `static` / `api` / `playwright` 중 하나를 고른다. 섞어 쓰는 것이
-- 정상적인 선택지다 — 목록은 `api`, 상세는 `playwright` 같은 조합이 있다.
--
-- `api_config_json` 은 `api` 모드가 쓸 endpoint·본문·응답 경로다. 형식은
-- `app/selector/api_schema.py` 가 강제한다. `api` 를 쓰지 않는 크롤러에서는 NULL 이다.
--
-- 기존 값은 두 열에 그대로 복사한다. `render_mode` 는 남기지 않고 지운다 — 같은 것을
-- 말하는 열이 둘이면 한쪽만 바뀌는 날이 오고, 그때 어느 쪽이 진실인지 아무도 모른다.
--
-- 되돌리기: `migrate down` 이 `render_mode` 를 다시 만들고 `list_mode` 를 그 값으로 옮긴다.
-- `api` 였던 크롤러는 `static` 으로 내려온다 — 0007 이전 스키마에 `api` 를 담을 자리가
-- 없기 때문이다. 그 크롤러는 되돌린 뒤 실행하면 JSON 을 HTML 로 파싱해 실패하므로, 역적용
-- 전에 어느 크롤러가 `api` 였는지 적어 두고 되돌린 뒤 멈춰야 한다.
-- `api_config_json` 의 내용은 역적용으로 사라진다. 되돌리기 전에 값을 따로 남긴다.

-- migrate:up
ALTER TABLE crawlers ADD COLUMN list_mode TEXT NOT NULL DEFAULT 'static'
    CHECK (list_mode IN ('static', 'api', 'playwright'));
ALTER TABLE crawlers ADD COLUMN detail_mode TEXT NOT NULL DEFAULT 'static'
    CHECK (detail_mode IN ('static', 'api', 'playwright'));
ALTER TABLE crawlers ADD COLUMN api_config_json TEXT;

UPDATE crawlers SET list_mode = render_mode, detail_mode = render_mode;

ALTER TABLE crawlers DROP COLUMN render_mode;

-- migrate:down
ALTER TABLE crawlers ADD COLUMN render_mode TEXT NOT NULL DEFAULT 'static'
    CHECK (render_mode IN ('static', 'playwright'));

UPDATE crawlers
   SET render_mode = CASE WHEN list_mode = 'playwright' THEN 'playwright' ELSE 'static' END;

ALTER TABLE crawlers DROP COLUMN api_config_json;
ALTER TABLE crawlers DROP COLUMN detail_mode;
ALTER TABLE crawlers DROP COLUMN list_mode;
