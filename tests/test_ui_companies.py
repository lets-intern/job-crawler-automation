"""회사 화면 (6.1.V ~ 6.8.V).

보는 것은 넷이다. 네비게이션에 자리가 생겼는지, 그 주소가 열리면서 목록 조각을 부르는지,
행이 없을 때 화면이 "없음" 으로 끝내지 않고 언제 생기는지 말하는지, 그리고 공고 수가
많은 회사가 앞에 서는지.

조회 조건 둘(`로고 없음`, `공고 N건 이상`)을 함께 걸면 등록할 목록이 나온다. 걸린 회사 수와
공고 합계가 실제와 같은지가 그 조건이 쓸모 있는지를 정한다.

로고를 저장하면 그 회사명을 가진 공고 전부에 붙는다. 붙는 건수를 문장으로 알리는지, 그리고
그 숫자가 실제 공고 수와 같은지를 본다 — 공고마다 넣는 자리가 없으므로 그 문장이 운영자가
방금 한 일의 크기를 아는 유일한 자리다.

저장소 공개 주소를 바꾸면 이미 올린 파일은 따라가지 않는다. 그 사실이 행에 `옛 저장소` 로
보이는지도 본다.

파일 올리기는 저장소를 부르는 자리를 바꿔치기한다. 화면 테스트가 컨테이너가 떠 있는지에
매달리게 두지 않는다 (`tests/test_ui_storage.py` 와 같다). 실제 왕복은 로컬 MinIO 로 따로
확인한다.

공고는 정규화를 지나 넣는다. 화면이 세는 값과 로고가 실제로 붙는 경로가 같은 이름이라야
숫자가 뜻을 갖는다.
"""

from __future__ import annotations

import json
import pathlib
import re
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import companies, db
from app.api.settings import get_connection
from app.api.ui import NAV
from app.main import app
from app.normalize.engine import insert_normalized
from app.storage import s3
from app.storage import settings as store


def add_job(conn: sqlite3.Connection, company: str, seq: int, parent: str = "") -> None:
    """공고 한 건을 정규화까지 넣는다. 없던 회사면 행이 함께 생긴다."""
    record = {"title": f"공고 {seq}", "body": "본문", "company": company}
    if parent:
        record["parent_company"] = parent
    cursor = conn.execute(
        """
        INSERT INTO raw_jobs (workflow_id, source_url, raw_data_json, content_hash)
        VALUES (1, ?, ?, ?)
        """,
        (f"https://x/{seq}", json.dumps(record, ensure_ascii=False), f"hash-{seq}"),
    )
    insert_normalized(conn, int(cursor.lastrowid or 0), [])


def names_in_order(body: str) -> list[str]:
    """표에 그려진 회사명을 나온 순서대로. 정렬을 보는 유일한 방법이다."""
    return re.findall(r'<td class="cell-text font-medium text-slate-900">([^<]+)</td>', body)


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    # `raw_jobs.workflow_id` 가 외래키다. 공고를 넣는 테스트가 여기에 매달린다
    connection.execute(
        "INSERT INTO crawlers (id, name, list_url, status)"
        " VALUES (1, '테스트', 'https://x', 'draft')"
    )
    connection.execute("INSERT INTO workflows (id, crawler_id, name) VALUES (1, 1, '테스트')")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def client(tmp_path: pathlib.Path, conn: sqlite3.Connection) -> Iterator[TestClient]:
    def request_connection() -> Iterator[sqlite3.Connection]:
        connection = db.connect(tmp_path / "jobs.db")
        try:
            yield connection
        finally:
            connection.close()

    app.dependency_overrides[get_connection] = request_connection
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_네비게이션에_회사가_있다() -> None:
    assert ("/companies", "회사") in NAV


def test_회사_화면이_열리고_네비게이션이_켜진다(client: TestClient) -> None:
    response = client.get("/companies")

    assert response.status_code == 200
    assert '<a href="/companies" aria-current="page"' in response.text


def test_회사_화면이_목록_조각을_부른다(client: TestClient) -> None:
    assert 'hx-get="/ui/companies"' in client.get("/companies").text


def test_목록이_저장된_회사를_그린다(client: TestClient, conn: sqlite3.Connection) -> None:
    companies.ensure(conn, "삼성SDS", "삼성전자")
    companies.set_logo_url(conn, "삼성SDS", "https://cdn.test/sds.png")
    conn.commit()

    body = client.get("/ui/companies").text

    assert "삼성SDS" in body
    assert "삼성전자" in body
    assert "https://cdn.test/sds.png" in body


def test_로고가_없으면_빈_칸으로_두지_않는다(client: TestClient, conn: sqlite3.Connection) -> None:
    companies.ensure(conn, "토스")
    conn.commit()

    assert "로고 없음" in client.get("/ui/companies").text


def test_행이_없으면_언제_생기는지_말한다(client: TestClient) -> None:
    body = client.get("/ui/companies").text

    assert "정규화되면 그 회사명으로 행이 생긴다" in body


def test_공고_수가_그_회사의_공고와_같다(client: TestClient, conn: sqlite3.Connection) -> None:
    add_job(conn, "토스", 1)
    add_job(conn, "토스", 2)
    add_job(conn, "당근", 3)
    conn.commit()

    body = client.get("/ui/companies").text

    assert "2건" in body
    assert "1건" in body


def test_공고가_많은_회사가_앞에_선다(client: TestClient, conn: sqlite3.Connection) -> None:
    """이름 순이면 로고 하나가 몇 건에 붙는지를 화면에서 알 수 없다."""
    for seq in range(1, 4):
        add_job(conn, "카카오", seq)
    add_job(conn, "가나다", 10)
    companies.ensure(conn, "공고없는회사")
    conn.commit()

    assert names_in_order(client.get("/ui/companies").text) == [
        "카카오",
        "가나다",
        "공고없는회사",
    ]


def test_공고가_하나도_없는_회사도_0건으로_남는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """빠지면 로고를 지울 회사를 화면에서 찾을 수 없다."""
    companies.ensure(conn, "폐업한회사")
    conn.commit()

    body = client.get("/ui/companies").text

    assert "폐업한회사" in body
    assert "0건" in body


def test_로고_없음_조건이_로고를_넣은_회사를_뺀다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    add_job(conn, "토스", 1)
    add_job(conn, "당근", 2)
    companies.set_logo_url(conn, "토스", "https://cdn.test/toss.png")
    conn.commit()

    body = client.get("/ui/companies", params={"no_logo": "on"}).text

    assert names_in_order(body) == ["당근"]


def test_공고_N건_이상_조건이_적은_회사를_뺀다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    for seq in range(1, 4):
        add_job(conn, "카카오", seq)
    add_job(conn, "당근", 10)
    conn.commit()

    body = client.get("/ui/companies", params={"min_jobs": "3"}).text

    assert names_in_order(body) == ["카카오"]


def test_둘을_걸면_등록할_목록만_남는다(client: TestClient, conn: sqlite3.Connection) -> None:
    """로고가 없으면서 공고가 여러 개인 회사. 이것이 먼저 등록할 목록이다."""
    for seq in range(1, 4):
        add_job(conn, "로고없는큰회사", seq)
    for seq in range(4, 7):
        add_job(conn, "로고있는큰회사", seq)
    add_job(conn, "로고없는작은회사", 7)
    companies.set_logo_url(conn, "로고있는큰회사", "https://cdn.test/x.png")
    conn.commit()

    body = client.get("/ui/companies", params={"no_logo": "on", "min_jobs": "2"}).text

    assert names_in_order(body) == ["로고없는큰회사"]


def test_걸린_회사_수와_공고_합계를_적는다(client: TestClient, conn: sqlite3.Connection) -> None:
    """숫자가 실제와 다르면 무엇을 먼저 등록할지를 이 화면으로 정할 수 없다."""
    for seq in range(1, 4):
        add_job(conn, "카카오", seq)
    for seq in range(4, 6):
        add_job(conn, "당근", seq)
    add_job(conn, "작은회사", 6)
    conn.commit()

    body = client.get("/ui/companies", params={"min_jobs": "2"}).text

    assert "조건에 걸린 회사" in body
    assert "2곳, 공고 합계 5건" in body


def test_조건에_걸린_회사가_없으면_조건_탓임을_말한다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    add_job(conn, "토스", 1)
    conn.commit()

    body = client.get("/ui/companies", params={"min_jobs": "9"}).text

    assert "이 조건에 걸린 회사가 없다" in body


def test_숫자_칸을_비워도_조건_없음으로_읽는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """정수로 받으면 빈 값이 422 가 되어 조건을 지우려던 조작이 오류로 돌아온다."""
    add_job(conn, "토스", 1)
    conn.commit()

    response = client.get("/ui/companies", params={"min_jobs": ""})

    assert response.status_code == 200
    assert names_in_order(response.text) == ["토스"]


def test_화면에_조회_조건_둘이_있다(client: TestClient) -> None:
    body = client.get("/companies").text

    assert 'name="no_logo"' in body
    assert 'name="min_jobs"' in body


def test_로고를_저장하면_붙는_건수를_문장으로_알린다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    for seq in range(1, 4):
        add_job(conn, "카카오", seq)
    conn.commit()

    response = client.put(
        "/ui/companies/logo",
        data={"name": "카카오", "logo_url": "https://cdn.test/kakao.png"},
    )

    assert response.status_code == 200
    assert "공고 3건에 붙는다" in response.text
    assert "공고마다 따로 넣지 않는다" in response.text
    stored = companies.read(conn, "카카오")
    assert stored is not None and stored.logo_url == "https://cdn.test/kakao.png"


def test_알린_건수가_그_회사의_공고_수와_같다(client: TestClient, conn: sqlite3.Connection) -> None:
    """다른 회사의 공고까지 세면 운영자는 붙지도 않은 건수를 붙었다고 읽는다."""
    for seq in range(1, 3):
        add_job(conn, "토스", seq)
    for seq in range(3, 8):
        add_job(conn, "당근", seq)
    conn.commit()

    body = client.put(
        "/ui/companies/logo", data={"name": "토스", "logo_url": "https://cdn.test/t.png"}
    ).text

    counted = conn.execute(
        "SELECT count(*) AS n FROM normalized_jobs WHERE company = '토스'"
    ).fetchone()["n"]
    assert counted == 2
    assert f"공고 {counted}건에 붙는다" in body


def test_공고가_없는_회사에_저장하면_다음부터_붙는다고_말한다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    companies.ensure(conn, "새회사")
    conn.commit()

    body = client.put(
        "/ui/companies/logo", data={"name": "새회사", "logo_url": "https://cdn.test/n.png"}
    ).text

    assert "지금은 이 회사명을 가진 공고가 없다" in body


def test_주소를_비우면_지우고_빠지는_건수를_말한다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """지우기 단추를 따로 두지 않는다. 비움이 곧 지움이다."""
    for seq in range(1, 3):
        add_job(conn, "토스", seq)
    companies.set_logo_url(conn, "토스", "https://cdn.test/t.png")
    conn.commit()

    body = client.put("/ui/companies/logo", data={"name": "토스", "logo_url": " "}).text

    assert "로고를 지웠다" in body
    assert "공고 2건에서 함께 빠진다" in body
    stored = companies.read(conn, "토스")
    assert stored is not None and stored.logo_url is None


def test_없는_회사에_저장하면_사유를_말한다(client: TestClient) -> None:
    """행을 만드는 것은 정규화다. 화면이 손으로 만들면 오타 하나로 로고가 안 붙는다."""
    response = client.put(
        "/ui/companies/logo", data={"name": "없는회사", "logo_url": "https://cdn.test/x.png"}
    )

    assert response.status_code == 200
    assert "회사 행이 없다" in response.text


def test_저장한_뒤에도_그_줄만_갈린다(client: TestClient, conn: sqlite3.Connection) -> None:
    """목록을 통째로 다시 부르면 방금 적은 문장이 사라진다."""
    add_job(conn, "토스", 1)
    add_job(conn, "당근", 2)
    conn.commit()

    body = client.put(
        "/ui/companies/logo", data={"name": "토스", "logo_url": "https://cdn.test/t.png"}
    ).text

    assert names_in_order(body) == ["토스"]


def test_목록에_로고_저장_폼이_있다(client: TestClient, conn: sqlite3.Connection) -> None:
    add_job(conn, "토스", 1)
    conn.commit()

    body = client.get("/ui/companies").text

    assert 'hx-put="/ui/companies/logo"' in body
    assert 'name="logo_url"' in body


def save_storage(conn: sqlite3.Connection, public_base: str) -> None:
    """저장소 설정 한 벌. 공개 주소만 이 테스트의 관심사다."""
    store.write_config(
        conn,
        store.StorageConfig(
            endpoint="http://minio:9000",
            region="us-east-1",
            bucket="logos",
            access_key="minioadmin",
            secret_key="minioadmin",
            public_base=public_base,
        ),
    )


def test_지금_저장소로_시작하는_주소에는_표시가_없다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    save_storage(conn, "http://localhost:9000/logos")
    companies.ensure(conn, "토스")
    companies.set_logo_url(conn, "토스", "http://localhost:9000/logos/toss.png")
    conn.commit()

    assert "옛 저장소" not in client.get("/ui/companies").text


def test_공개_주소를_바꾸면_기존_행에_옛_저장소가_뜬다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """엔드포인트를 바꿔도 이미 올린 파일은 따라가지 않는다. 무엇을 다시 올릴지가 보여야 한다."""
    save_storage(conn, "http://localhost:9000/logos")
    companies.ensure(conn, "토스")
    companies.set_logo_url(conn, "토스", "http://localhost:9000/logos/toss.png")
    conn.commit()
    assert "옛 저장소" not in client.get("/ui/companies").text

    save_storage(conn, "https://cdn.example.com/logos")
    conn.commit()

    assert "옛 저장소" in client.get("/ui/companies").text


def test_로고가_없는_행에는_표시가_붙지_않는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    save_storage(conn, "https://cdn.example.com/logos")
    companies.ensure(conn, "토스")
    conn.commit()

    assert "옛 저장소" not in client.get("/ui/companies").text


def test_저장_직후의_줄에도_같은_표시가_붙는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    save_storage(conn, "https://cdn.example.com/logos")
    companies.ensure(conn, "토스")
    conn.commit()

    body = client.put(
        "/ui/companies/logo", data={"name": "토스", "logo_url": "https://elsewhere.test/t.png"}
    ).text

    assert "옛 저장소" in body


def test_화면이_옛_저장소가_무슨_뜻인지_적는다(client: TestClient) -> None:
    """붙여넣은 외부 주소도 같은 표시를 받는다. 그 사실을 적지 않으면 없는 문제를 고치게 된다."""
    body = client.get("/companies").text

    assert "밖에 올려 둔 주소를 붙여넣은 것이면 그대로 두어도 된다" in body


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def test_파일을_올리면_주소가_회사에_적히고_미리보기가_나온다(
    client: TestClient, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_storage(conn, "http://localhost:9000/logos")
    for seq in range(1, 3):
        add_job(conn, "토스", seq)
    conn.commit()
    uploaded: dict[str, object] = {}

    def fake_upload(config: store.StorageConfig, *, data: bytes, name: str) -> str:
        uploaded["data"] = data
        uploaded["name"] = name
        return f"{config.public_base}/{name}.png"

    monkeypatch.setattr(s3, "upload_image", fake_upload)

    response = client.post(
        "/ui/companies/logo/upload",
        data={"name": "토스"},
        files={"file": ("toss.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 200
    assert uploaded["data"] == PNG_BYTES
    stored = companies.read(conn, "토스")
    assert stored is not None and stored.logo_url is not None
    assert f'<img src="{stored.logo_url}"' in response.text
    assert "공고 2건에 붙는다" in response.text


def test_올린_객체_이름에_회사명을_넣지_않는다(
    client: TestClient, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """이름이 한글이라 공개 주소가 퍼센트 인코딩으로 덮이고, 회사명이 바뀌면 어긋난다."""
    save_storage(conn, "http://localhost:9000/logos")
    companies.ensure(conn, "토스")
    conn.commit()
    seen: dict[str, str] = {}

    def fake_upload(config: store.StorageConfig, *, data: bytes, name: str) -> str:
        seen["name"] = name
        return f"{config.public_base}/{name}.png"

    monkeypatch.setattr(s3, "upload_image", fake_upload)

    client.post(
        "/ui/companies/logo/upload",
        data={"name": "토스"},
        files={"file": ("toss.png", PNG_BYTES, "image/png")},
    )

    assert "토스" not in seen["name"]
    assert seen["name"].startswith("company/")


def test_저장소가_거절하면_사유가_그_줄에_남는다(
    client: TestClient, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """조용히 실패하면 운영자는 로고가 왜 안 붙는지 알 수 없다."""
    save_storage(conn, "http://localhost:9000/logos")
    companies.ensure(conn, "토스")
    conn.commit()

    def refuse(config: store.StorageConfig, *, data: bytes, name: str) -> str:
        raise s3.StorageError("not_an_image", "받는 형식이 아니다. PNG, JPEG, WebP 만 올릴 수 있다")

    monkeypatch.setattr(s3, "upload_image", refuse)

    body = client.post(
        "/ui/companies/logo/upload",
        data={"name": "토스"},
        files={"file": ("toss.svg", b"<svg/>", "image/svg+xml")},
    ).text

    assert "올리지 못했다" in body
    assert "받는 형식이 아니다" in body
    assert companies.read(conn, "토스") is not None
    stored = companies.read(conn, "토스")
    assert stored is not None and stored.logo_url is None


def test_저장소가_설정되지_않으면_파일_고르기_대신_할_일을_적는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    companies.ensure(conn, "토스")
    conn.commit()

    body = client.get("/ui/companies").text

    assert 'hx-post="/ui/companies/logo/upload"' not in body
    assert "파일 저장소가 아직 설정되지 않았다" in body


def test_저장소가_설정되면_파일_고르기가_나온다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    save_storage(conn, "http://localhost:9000/logos")
    companies.ensure(conn, "토스")
    conn.commit()

    body = client.get("/ui/companies").text

    assert 'hx-post="/ui/companies/logo/upload"' in body
    assert 'hx-encoding="multipart/form-data"' in body


def test_화면이_받는_형식과_상한을_적는다(client: TestClient) -> None:
    body = client.get("/companies").text

    assert s3.ACCEPTED in body
    assert s3.MAX_IMAGE_LABEL in body
    assert "SVG 는 받지 않는다" in body


def test_밖에_올려_둔_주소를_붙여넣으면_저장되고_미리보기가_뜬다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """우리 저장소를 거치지 않는 길이다. 파일은 남의 곳에 있고 우리는 주소만 갖는다."""
    save_storage(conn, "http://localhost:9000/logos")
    add_job(conn, "당근", 1)
    conn.commit()

    body = client.put(
        "/ui/companies/logo",
        data={"name": "당근", "logo_url": "https://cdn.elsewhere.test/daangn.png"},
    ).text

    stored = companies.read(conn, "당근")
    assert stored is not None and stored.logo_url == "https://cdn.elsewhere.test/daangn.png"
    assert '<img src="https://cdn.elsewhere.test/daangn.png"' in body


def test_http_로_시작하지_않는_주소는_받지_않는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """브라우저의 type=url 은 화면을 지나는 값만 막는다. 저장되면 그것이 곧 목록의 링크다."""
    companies.ensure(conn, "당근")
    conn.commit()

    body = client.put(
        "/ui/companies/logo",
        data={"name": "당근", "logo_url": "javascript:alert(1)"},
    ).text

    assert "주소를 받지 않았다" in body
    assert "http:// 나 https:// 로 시작해야 한다" in body
    stored = companies.read(conn, "당근")
    assert stored is not None and stored.logo_url is None


def test_거절해도_그_회사의_옛_주소는_그대로다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    companies.ensure(conn, "당근")
    companies.set_logo_url(conn, "당근", "https://cdn.elsewhere.test/old.png")
    conn.commit()

    client.put("/ui/companies/logo", data={"name": "당근", "logo_url": "ftp://x/y.png"})

    stored = companies.read(conn, "당근")
    assert stored is not None and stored.logo_url == "https://cdn.elsewhere.test/old.png"


def test_붙여넣기_길이_저장소를_거치지_않는다고_화면에_적힌다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    companies.ensure(conn, "당근")
    conn.commit()

    body = client.get("/ui/companies").text

    assert "우리 저장소를 거치지 않는다" in body


def test_모회사_이름을_사람이_고친다(client: TestClient, conn: sqlite3.Connection) -> None:
    add_job(conn, "삼성SDS", 1)
    conn.commit()

    body = client.put(
        "/ui/companies/parent", data={"name": "삼성SDS", "parent_name": " 삼성전자 "}
    ).text

    stored = companies.read(conn, "삼성SDS")
    assert stored is not None and stored.parent_name == "삼성전자"
    assert "모회사를 삼성전자 로 고쳤다" in body


def test_고친_모회사가_다음_정규화에_덮이지_않는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """6.8.V. 정규화는 공고마다 회사 행을 보장하는데, 있는 행을 덮으면 고친 값이 도로 돌아간다."""
    add_job(conn, "삼성SDS", 1)
    conn.commit()
    client.put("/ui/companies/parent", data={"name": "삼성SDS", "parent_name": "삼성전자"})

    add_job(conn, "삼성SDS", 2)
    conn.commit()

    stored = companies.read(conn, "삼성SDS")
    assert stored is not None and stored.parent_name == "삼성전자"


def test_모회사를_비우면_지운다(client: TestClient, conn: sqlite3.Connection) -> None:
    companies.ensure(conn, "토스", "비바리퍼블리카")
    conn.commit()

    body = client.put("/ui/companies/parent", data={"name": "토스", "parent_name": "  "}).text

    stored = companies.read(conn, "토스")
    assert stored is not None and stored.parent_name is None
    assert "모회사를 지웠다" in body


def test_자기_자신을_모회사로_적지_않는다(client: TestClient, conn: sqlite3.Connection) -> None:
    """자기 자신을 적으면 화면이 그 행을 모회사가 따로 있는 회사로 읽는다."""
    companies.ensure(conn, "토스")
    conn.commit()

    body = client.put("/ui/companies/parent", data={"name": "토스", "parent_name": "토스"}).text

    assert "이름을 받지 않았다" in body
    stored = companies.read(conn, "토스")
    assert stored is not None and stored.parent_name is None


def test_없는_회사의_모회사는_고치지_않는다(client: TestClient) -> None:
    response = client.put(
        "/ui/companies/parent", data={"name": "없는회사", "parent_name": "삼성전자"}
    )

    assert response.status_code == 200
    assert "회사 행이 없다" in response.text


def test_목록에_모회사_고치는_폼이_있다(client: TestClient, conn: sqlite3.Connection) -> None:
    add_job(conn, "토스", 1)
    conn.commit()

    body = client.get("/ui/companies").text

    assert 'hx-put="/ui/companies/parent"' in body
    assert 'name="parent_name"' in body


def test_이_화면의_모회사가_검수_화면의_것과_다른_값임을_적는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """두 화면에 같은 이름의 칸이 있고, 값은 다를 수 있다.

    이쪽은 사람이 적는 `companies.parent_name` 이고 검수 화면은 크롤러가 정한
    `normalized_jobs.parent_company` 다. 이름표가 둘 다 `모회사` 이기만 하면 같은 회사가
    두 화면에서 다르게 보이는 것이 고장으로 읽힌다 (`.claude/docs/data-model.md`).
    """
    add_job(conn, "토스", 1)
    conn.commit()

    body = client.get("/ui/companies").text

    assert ">모회사 (사람이 적음)</th>" in body
    assert "검수 화면의 모회사 열은 크롤러가 정한 값이라 여기와 다를 수 있다" in body
