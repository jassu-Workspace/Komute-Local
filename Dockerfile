FROM python:3.12-slim

# glibc malloc: fewer arenas keeps resident memory flat across requests
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MALLOC_ARENA_MAX=2 \
    KOMUTE_ENV=production KOMUTE_STORAGE_ROOT=/var/lib/komute

WORKDIR /app

# requirements.txt, not the Windows-frozen requirements.lock: the lock may pin platform-specific wheels
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY storage/ storage/
COPY scripts/ scripts/
COPY tests/fixtures/synthetic_vehicle.png tests/fixtures/synthetic_vehicle.png

RUN useradd --system --uid 10001 komute && mkdir -p /var/lib/komute && chown -R komute /var/lib/komute
USER komute
VOLUME /var/lib/komute
EXPOSE 8000

# One worker: one verification at a time per container. Scale by adding containers.
CMD ["uvicorn", "backend.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
