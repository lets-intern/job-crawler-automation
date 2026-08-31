"""S3 호환 저장소에 로고를 올린다. MinIO 도 실제 S3 도 이 코드 하나로 부른다.

주소 형식을 우리가 만들지 않는다. `endpoint_url` 이 있으면 `엔드포인트/버킷/키` 로,
비어 있으면 SDK 가 지역으로 `버킷.s3.지역.amazonaws.com/키` 를 만든다. 운영자가 고를 값이
아니다 (`../.claude/tasks/todo/prd-fields-and-logo.md` 5장).

공용 fetch 클라이언트를 지나지 않는 두 번째 자리다. 우리가 올린 객체만 만지므로 robots 를
물을 상대가 아니고 지킬 딜레이도 없다 (`../.claude/rules/crawling.md`, 2026-08-28).

받는 것은 이미지뿐이고 크기 상한이 있다. 어느 형식인지는 파일 이름이 아니라 앞 몇 바이트로
정한다 — `.png` 로 이름만 바꾼 실행 파일이 우리 도메인에서 서비스되게 두지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.storage.settings import StorageConfig

logger = logging.getLogger(__name__)

# 받는 형식 셋. 앞 바이트로 판정한다.
#
# SVG 는 받지 않는다. 텍스트라 앞 바이트로 가릴 수 없고, 스크립트를 품은 SVG 가 우리 공개
# 주소에서 열리면 그것이 곧 XSS 다. 로고를 벡터로 갖고 있으면 PNG 로 내보내 올린다.
PNG = b"\x89PNG\r\n\x1a\n"
JPEG = b"\xff\xd8\xff"
RIFF = b"RIFF"
WEBP = b"WEBP"

# 로고는 200px 안팎으로 그린다. 그 크기의 PNG 는 수십 KB 다. 2MiB 는 디자인 도구에서
# 생각 없이 내보낸 파일도 지나가게 두면서, 사진을 잘못 고른 것은 막는다
MAX_IMAGE_BYTES = 2 * 1024 * 1024

# 화면에 적는 문구. 형식과 상한을 두 곳에서 따로 쓰지 않는다
ACCEPTED = "PNG, JPEG, WebP"
MAX_IMAGE_LABEL = "2MB"

# 저장소가 답하지 않을 때 오래 매달리지 않는다. 운영자가 화면 앞에서 기다리는 동작이다
_CONNECT_TIMEOUT = 5
_READ_TIMEOUT = 15


class StorageError(RuntimeError):
    """저장소 동작 실패. 사유를 낱말 하나와 문장 하나로 갖는다.

    고치는 방법이 사유마다 다르다 — 키가 틀린 것과 버킷이 없는 것과 주소에 못 닿는 것은
    같은 화면에 같은 문구로 나오면 안 된다.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class ImageKind:
    """올릴 이미지의 형식. 파일 이름이 아니라 내용에서 나온다."""

    extension: str
    content_type: str


def detect_image(data: bytes) -> ImageKind:
    """앞 바이트로 형식을 정한다. 셋 중 하나가 아니면 거절한다."""
    if not data:
        raise StorageError("not_an_image", "파일이 비어 있다")
    if len(data) > MAX_IMAGE_BYTES:
        raise StorageError(
            "too_large",
            f"파일이 상한 {MAX_IMAGE_LABEL} 를 넘는다: {len(data)}바이트",
        )
    if data.startswith(PNG):
        return ImageKind("png", "image/png")
    if data.startswith(JPEG):
        return ImageKind("jpg", "image/jpeg")
    if data[:4] == RIFF and data[8:12] == WEBP:
        return ImageKind("webp", "image/webp")
    raise StorageError("not_an_image", f"받는 형식이 아니다. {ACCEPTED} 만 올릴 수 있다")


def client(config: StorageConfig) -> Any:
    """설정 한 벌로 만든 S3 클라이언트.

    `endpoint_url` 이 비면 넘기지 않는다. 빈 문자열을 넘기면 SDK 가 지역으로 주소를 만드는
    길로 가지 않고 그 자리에서 깨진다.
    """
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint or None,
        region_name=config.region,
        aws_access_key_id=config.access_key,
        aws_secret_access_key=config.secret_key,
        config=BotoConfig(
            connect_timeout=_CONNECT_TIMEOUT,
            read_timeout=_READ_TIMEOUT,
            # 여기서 실패하는 것은 대개 설정이 틀린 것이다. 세 번 더 물어도 답이 같다
            retries={"max_attempts": 1},
        ),
    )


def upload_image(config: StorageConfig, *, data: bytes, name: str) -> str:
    """이미지 하나를 올리고 공개 주소를 돌려준다.

    `name` 은 확장자 없는 객체 이름이다. 확장자는 내용에서 정한 것을 붙인다 — 운영자가 적어
    온 이름을 믿으면 `image/png` 로 서비스되는 JPEG 가 생긴다.
    """
    if not config.configured:
        raise StorageError("not_configured", "저장소 설정이 아직 채워지지 않았다")
    kind = detect_image(data)
    key = f"{name}.{kind.extension}"
    try:
        client(config).put_object(
            Bucket=config.bucket,
            Key=key,
            Body=data,
            ContentType=kind.content_type,
        )
    except (ClientError, BotoCoreError) as exc:
        raise translate(exc, config) from exc
    logger.info("로고를 올렸다: %s/%s (%d bytes)", config.bucket, key, len(data))
    return config.public_url(key)


@dataclass(frozen=True)
class CheckResult:
    """연결 확인 한 번의 결과. 실패했으면 어느 걸음에서인지가 같이 온다."""

    ok: bool
    step: str
    reason: str
    message: str


# 확인이 만드는 객체. 로고와 섞이지 않게 접두어를 둔다. 지우기까지 성공하면 남지 않는다
CHECK_PREFIX = "_check/"
CHECK_BODY = b"job-crawler storage check"


def check(config: StorageConfig) -> CheckResult:
    """작은 객체를 넣고, 읽고, 지운다. 저장된 설정으로 부른다.

    걸음을 나눠 부르는 이유는 사유를 가르기 위해서다. 넣기에서 죽은 것과 읽기에서 죽은 것은
    같은 `AccessDenied` 라도 고치는 자리가 다르다 — 앞은 쓰기 권한, 뒤는 읽기 권한이다.

    던지지 않는다. 이 함수를 부르는 자리가 화면이고, 화면은 실패도 그려야 한다.
    """
    if not config.configured:
        return CheckResult(
            ok=False,
            step="설정",
            reason="not_configured",
            message="버킷과 키를 먼저 저장한다. 확인은 저장된 값으로 한다",
        )

    key = f"{CHECK_PREFIX}{uuid4().hex}.txt"
    step = "연결"
    try:
        s3 = client(config)
        step = "넣기"
        s3.put_object(Bucket=config.bucket, Key=key, Body=CHECK_BODY, ContentType="text/plain")
        step = "읽기"
        body = s3.get_object(Bucket=config.bucket, Key=key)["Body"].read()
        if body != CHECK_BODY:
            return CheckResult(
                ok=False,
                step=step,
                reason="mismatch",
                message="넣은 것과 읽은 것이 다르다. 같은 이름의 다른 객체를 읽고 있다",
            )
        step = "지우기"
        s3.delete_object(Bucket=config.bucket, Key=key)
    except (ClientError, BotoCoreError) as exc:
        error = translate(exc, config)
        logger.info("저장소 연결 확인 실패: %s 에서 %s", step, error.reason)
        return CheckResult(ok=False, step=step, reason=error.reason, message=error.message)
    except Exception as exc:  # noqa: BLE001 - 화면이 부르는 자리다. 무엇이 와도 문장으로 답한다
        logger.warning("저장소 연결 확인이 예상 밖으로 실패했다: %s", exc)
        return CheckResult(
            ok=False,
            step=step,
            reason="failed",
            message=f"{type(exc).__name__}: {exc}",
        )

    where = config.endpoint or f"{config.region} 지역의 S3"
    return CheckResult(
        ok=True,
        step="지우기",
        reason="ok",
        message=f"버킷 `{config.bucket}` 에 넣고 읽고 지웠다 ({where})",
    )


def translate(exc: Exception, config: StorageConfig) -> StorageError:
    """SDK 예외를 고칠 방법이 갈리는 사유로 옮긴다.

    낱말은 다섯이다. 주소에 못 닿는 것(`unreachable`), 키가 틀린 것(`bad_credentials`),
    버킷이 없는 것(`no_bucket`), 키는 맞는데 권한이 없는 것(`denied`), 나머지(`failed`).
    """
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in ("InvalidAccessKeyId", "SignatureDoesNotMatch", "InvalidToken"):
            return StorageError(
                "bad_credentials",
                f"접근 키나 비밀 키가 저장소에서 거절됐다 ({code})",
            )
        if code in ("NoSuchBucket", "404", "NotFound"):
            return StorageError(
                "no_bucket",
                f"버킷 `{config.bucket}` 이 저장소에 없다. 콘솔에서 먼저 만든다",
            )
        if code in ("AccessDenied", "403", "Forbidden"):
            return StorageError(
                "denied",
                f"버킷 `{config.bucket}` 에 대한 권한이 없다. 키는 닿았고 권한이 막혔다",
            )
        return StorageError("failed", f"저장소가 거절했다 ({code}): {exc}")

    name = type(exc).__name__
    if "Connect" in name or "Endpoint" in name or "ConnectionError" in name:
        target = config.endpoint or f"{config.region} 지역의 S3"
        return StorageError("unreachable", f"저장소 주소에 닿지 못했다: {target}")
    return StorageError("failed", f"저장소 호출이 실패했다 ({name}): {exc}")
