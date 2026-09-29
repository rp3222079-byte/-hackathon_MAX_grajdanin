FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Зависимости отдельным слоем: при правке кода они не переустанавливаются
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY data ./data
COPY certs ./certs

# Непривилегированный пользователь; каталоги для писем и состояния бота
RUN useradd --create-home --uid 1000 domovoy \
    && mkdir -p /app/outbox /app/state \
    && chown -R domovoy:domovoy /app
USER domovoy

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
