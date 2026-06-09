# ============================================================
# Multi-stage Dockerfile для AI Telegram Bot
# Оптимизирован для продакшена: минимальный размер образа,
# кеширование слоёв, non-root пользователь.
# ============================================================

# ── Stage 1: Сборка зависимостей ─────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Системные зависимости для сборки C-расширений (asyncpg, chromadb)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Финальный образ ─────────────────────────────────
FROM python:3.11-slim AS runtime

# Метаданные
LABEL maintainer="AI Bot Team" \
      description="AI Telegram Bot" \
      version="0.1.0"

# Системные зависимости runtime (только libpq для asyncpg)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 \
        curl && \
        rm -rf /var/lib/apt/lists/*

# Непривилегированный пользователь
RUN groupadd --gid 1000 botuser && \
    useradd --uid 1000 --gid botuser --create-home botuser

WORKDIR /app

# Копируем установленные пакеты из builder-стадии
COPY --from=builder /install /usr/local

# Копируем исходный код приложения и базу знаний
COPY common/ ./common/
COPY telegram/ ./telegram/
COPY whatsapp/ ./whatsapp/
COPY instagram/ ./instagram/
COPY data/ ./data/
COPY main.py .

# Установка прав для non-root пользователя
RUN chown -R botuser:botuser /app

# Переключаемся на non-root пользователя
USER botuser

# Переменные окружения Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Health-check для оркестраторов (Docker Swarm / K8s)
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# Запуск: uvicorn с 1 воркером (полностью async боту этого достаточно, экономит RAM)
CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--loop", "uvloop", \
     "--http", "httptools", \
     "--log-level", "info"]
