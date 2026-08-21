# 컨테이너 하나, 프로세스 하나 (.claude/docs/architecture.md "프로세스 구성").
# Playwright·Node·빌드 단계는 넣지 않는다.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DATABASE_PATH=/data/jobs.db

WORKDIR /app

# 런타임 의존성만 설치한다. dev extra 는 이미지에 넣지 않는다.
# 목록의 출처는 pyproject.toml 하나뿐이다 — 여기에 다시 적지 않는다.
COPY pyproject.toml ./
RUN python -c "import tomllib, pathlib; deps = tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['dependencies']; pathlib.Path('requirements.txt').write_text('\n'.join(deps))" \
    && pip install --no-cache-dir -r requirements.txt \
    && rm requirements.txt

# app/db.py 가 migrations/ 를 app/ 의 형제 디렉터리로 찾는다. 배치를 그대로 유지한다.
COPY app ./app
COPY migrations ./migrations

# 비루트 실행. /data 를 미리 만들어 두면 named volume 이 이 소유권을 물려받는다.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data
USER appuser

EXPOSE 8000

# 마이그레이션을 적용한 뒤 서버를 띄운다. 볼륨의 DB 파일은 여기서 생성만 되고, 지우는 경로는 없다.
CMD ["sh", "-c", "python -m app.cli migrate up && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
