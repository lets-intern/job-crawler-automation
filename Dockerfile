# 컨테이너 하나, 프로세스 하나 (.claude/docs/architecture.md "프로세스 구성").
# Node 나 프런트엔드 빌드 단계는 넣지 않는다. Chromium 은 render_mode=playwright 인
# 크롤러만 쓰고, 그 사이트들은 정적 fetch 로 목록이 오지 않는 것이 실측으로 확인됐다
# (seeds/sample-sites.json).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DATABASE_PATH=/data/jobs.db

# 브라우저를 root 홈이 아니라 공용 경로에 깐다. 비루트로 실행해도 읽을 수 있어야 한다.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# 런타임 의존성만 설치한다. dev extra 는 이미지에 넣지 않는다.
# 목록의 출처는 pyproject.toml 하나뿐이다 — 여기에 다시 적지 않는다.
COPY pyproject.toml ./
RUN python -c "import tomllib, pathlib; deps = tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['dependencies']; pathlib.Path('requirements.txt').write_text('\n'.join(deps))" \
    && pip install --no-cache-dir -r requirements.txt \
    && rm requirements.txt

# Chromium 과 그것이 필요로 하는 시스템 라이브러리. 이미지가 크게 무거워지는 단계라 따로
# 둔다 (측정값은 .claude/tasks/todo/tasks-job-crawler-push11.md).
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

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
