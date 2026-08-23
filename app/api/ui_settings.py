"""운영 설정 화면의 조각 라우트.

`app/api/settings.py` 를 그대로 부른다. 값 검증은 `app/settings.py` 가 하고, 화면은 거절 사유를
그대로 옮긴다 — 화면에서만 통과하는 값이 생기면 어느 쪽이 진실인지 알 수 없게 된다.

이 화면에 나오는 값은 동시 실행 상한 하나다. 환경변수로 충분한 값을 여기로 옮기면 같은 설정이
두 곳에 생긴다 (`app/settings.py`).

데이터 파일 업로드도 이 화면에 있다. 검증과 병합은 `app/api/import_data.py` 가 하고, 여기서는
올라온 파일을 임시 파일로 받아 넘기고 결과를 숫자로 그린다. 거절 사유는 그대로 옮긴다.
"""

from __future__ import annotations

import logging
import sqlite3
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse

from app import settings as store
from app.api import import_data
from app.api import settings as settings_api
from app.api.ui import render
from app.api.ui_crawlers import error_detail
from app.api.workflows import get_workflow_scheduler
from app.scheduler import WorkflowScheduler

logger = logging.getLogger(__name__)

# 업로드를 읽어 들이는 덩어리 크기. 전체를 메모리에 올리지 않는다
_CHUNK_BYTES = 1024 * 1024

router = APIRouter(tags=["ui"], include_in_schema=False)


def _form(
    request: Request,
    conn: sqlite3.Connection,
    *,
    message: str = "",
    error: str = "",
) -> HTMLResponse:
    """설정 폼 하나. 저장 결과도 이 조각으로 돌아온다."""
    return render(
        request,
        "fragments/settings_form.html",
        values=settings_api.read_settings(conn),
        key=store.MAX_CONCURRENT_RUNS,
        message=message,
        error=error,
    )


@router.get("/ui/settings", response_class=HTMLResponse)
def settings_form_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(settings_api.get_connection)],
) -> HTMLResponse:
    """저장된 값. 아직 없는 키는 환경변수 값으로 채워진 뒤 돌아온다."""
    return _form(request, conn)


@router.put("/ui/settings/{key}", response_class=HTMLResponse)
def update_setting_fragment(
    request: Request,
    key: str,
    conn: Annotated[sqlite3.Connection, Depends(settings_api.get_connection)],
    value: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """값을 바꾼다. 거절된 값은 저장되지 않고 저장된 값이 그대로 다시 그려진다."""
    try:
        parsed = int(value)
    except ValueError:
        return _form(request, conn, error=f"정수가 아니다: {value!r}")

    try:
        saved = settings_api.update_setting(key, settings_api.SettingUpdate(value=parsed), conn)
    except HTTPException as exc:
        return _form(request, conn, error=error_detail(exc)["message"])

    return _form(request, conn, message=f"{saved.key} 를 {saved.value} 로 저장했다")


@router.post("/ui/settings/import", response_class=HTMLResponse)
def import_upload_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(settings_api.get_connection)],
    scheduler: Annotated[WorkflowScheduler, Depends(get_workflow_scheduler)],
    file: Annotated[UploadFile, File()],
) -> HTMLResponse:
    """올린 SQLite 파일을 기존 데이터에 더하고 결과를 숫자로 돌려준다.

    파일은 임시 디렉터리에 받아 두고 끝나면 지운다. SQLite 는 경로가 있어야 열 수 있고, 검증도
    병합도 파일을 여러 번 연다.

    새 워크플로우가 들어왔으면 스케줄러에 알린다. `workflows` 테이블이 진실이고 잡은 그것을
    따라간다 (`.claude/rules/crawling.md`). 다음 기동까지 기다리면 방금 가져온 워크플로우가
    도는지 화면에서 확인할 방법이 없다.
    """
    with tempfile.TemporaryDirectory(prefix="import-") as workspace:
        try:
            path = _spool(file, Path(workspace))
            result = import_data.import_database(conn, path)
        except import_data.ImportRejected as rejected:
            logger.info("데이터 가져오기를 거절했다: %s / %s", rejected.reason, rejected.message)
            return render(request, "fragments/import_result.html", error=rejected)

    if result.workflows_added:
        scheduler.sync(conn)
    return render(request, "fragments/import_result.html", result=result)


def _spool(file: UploadFile, directory: Path) -> Path:
    """올라온 내용을 파일로 받는다. 상한을 넘으면 받다 말고 거절한다.

    다 받은 뒤에 크기를 재지 않는다. 상한이 있는 이유는 디스크를 지키는 것이고, 다 받고 나서
    재면 이미 다 쓴 뒤다.
    """
    path = directory / "upload.db"
    size = 0
    with path.open("wb") as target:
        while chunk := file.file.read(_CHUNK_BYTES):
            size += len(chunk)
            if size > import_data.MAX_UPLOAD_BYTES:
                raise import_data.ImportRejected(
                    "too_large",
                    f"파일이 상한 {import_data.MAX_UPLOAD_BYTES}바이트를 넘는다",
                )
            target.write(chunk)
    return path
