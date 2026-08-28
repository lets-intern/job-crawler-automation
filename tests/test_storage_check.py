"""연결 확인 테스트 (5.5.V 의 픽스처 몫).

실사 확인은 로컬 MinIO 로 한다. 여기서 보는 것은 사유가 갈려 나오는지와 어느 걸음에서
죽었는지가 결과에 남는지다 — 키가 틀린 것과 버킷이 없는 것과 주소에 못 닿는 것은 고치는
자리가 다르고, 화면에 같은 문구로 나오면 안 된다.

확인은 던지지 않는다. 부르는 자리가 화면이라 실패도 그려져야 한다.
"""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.storage import s3
from app.storage.settings import StorageConfig


def config() -> StorageConfig:
    return StorageConfig(
        endpoint="http://minio:9000",
        region="us-east-1",
        bucket="logos",
        access_key="minioadmin",
        secret_key="minioadmin",
        public_base="http://localhost:9000/logos",
    )


class Body:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self) -> bytes:
        return self.data


class FakeClient:
    """걸음마다 무엇을 할지 지정하는 클라이언트. 지정이 없으면 성공한다."""

    def __init__(
        self, fail_on: str = "", error: Exception | None = None, body: bytes = b""
    ) -> None:
        self.fail_on = fail_on
        self.error = error
        self.body = body or s3.CHECK_BODY
        self.steps: list[str] = []

    def _step(self, name: str) -> None:
        self.steps.append(name)
        if name == self.fail_on and self.error is not None:
            raise self.error

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self._step("put")
        return {}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self._step("get")
        return {"Body": Body(self.body)}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self._step("delete")
        return {}


def use(monkeypatch: pytest.MonkeyPatch, fake: FakeClient) -> FakeClient:
    monkeypatch.setattr(s3, "client", lambda _config: fake)
    return fake


def test_round_trip_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """넣고, 읽고, 지운다. 셋 다 부른다."""
    fake = use(monkeypatch, FakeClient())
    result = s3.check(config())

    assert result.ok is True
    assert result.reason == "ok"
    assert fake.steps == ["put", "get", "delete"]
    assert "logos" in result.message


def test_check_object_is_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    """확인이 만든 객체는 남지 않는다. 로고와 섞이지 않게 접두어도 붙는다."""
    fake = use(monkeypatch, FakeClient())
    captured: list[str] = []
    original_put = fake.put_object
    original_delete = fake.delete_object

    def put(**kwargs: Any) -> dict[str, Any]:
        captured.append(str(kwargs["Key"]))
        return original_put(**kwargs)

    def delete(**kwargs: Any) -> dict[str, Any]:
        captured.append(str(kwargs["Key"]))
        return original_delete(**kwargs)

    monkeypatch.setattr(fake, "put_object", put)
    monkeypatch.setattr(fake, "delete_object", delete)
    s3.check(config())

    assert captured[0].startswith(s3.CHECK_PREFIX)
    assert captured[0] == captured[1]


def test_not_configured_before_saving(monkeypatch: pytest.MonkeyPatch) -> None:
    """순서는 저장하고 나서 확인이다. 저장 전에는 저장소를 부르지도 않는다."""
    fake = use(monkeypatch, FakeClient())
    result = s3.check(StorageConfig())

    assert result.ok is False
    assert result.reason == "not_configured"
    assert result.step == "설정"
    assert fake.steps == []


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ClientError({"Error": {"Code": "InvalidAccessKeyId"}}, "PutObject"), "bad_credentials"),
        (ClientError({"Error": {"Code": "NoSuchBucket"}}, "PutObject"), "no_bucket"),
        (ClientError({"Error": {"Code": "AccessDenied"}}, "PutObject"), "denied"),
        (EndpointConnectionError(endpoint_url="http://minio:9000"), "unreachable"),
    ],
)
def test_reasons_are_distinct(
    monkeypatch: pytest.MonkeyPatch, error: Exception, reason: str
) -> None:
    """넷이 같은 실패로 뭉개지지 않는다."""
    use(monkeypatch, FakeClient(fail_on="put", error=error))
    result = s3.check(config())

    assert result.ok is False
    assert result.reason == reason
    assert result.step == "넣기"
    assert result.message


def test_step_says_where_it_died(monkeypatch: pytest.MonkeyPatch) -> None:
    """넣기는 됐는데 읽기에서 죽으면 읽기라고 적힌다. 고치는 자리가 다르다."""
    error = ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
    fake = use(monkeypatch, FakeClient(fail_on="get", error=error))
    result = s3.check(config())

    assert result.step == "읽기"
    assert result.reason == "denied"
    assert fake.steps == ["put", "get"]


def test_mismatch_is_its_own_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """넣은 것과 다른 것이 읽히면 성공이 아니다."""
    use(monkeypatch, FakeClient(body=b"someone else"))
    result = s3.check(config())

    assert result.ok is False
    assert result.reason == "mismatch"
    assert result.step == "읽기"


def test_unexpected_error_still_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK 예외가 아닌 것이 와도 화면에 문장이 간다. 확인은 던지지 않는다."""
    use(monkeypatch, FakeClient(fail_on="put", error=RuntimeError("무슨 일인가 났다")))
    result = s3.check(config())

    assert result.ok is False
    assert result.reason == "failed"
    assert "무슨 일인가 났다" in result.message
