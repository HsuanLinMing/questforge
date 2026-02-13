FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -U pip \
 && pip install --no-cache-dir -r /app/requirements.txt

COPY . /app
RUN pip install --no-cache-dir -e .

ENV PYTHONPATH=/app/src
EXPOSE 8000

# Render 會提供 $PORT；這裡用預設值避免本機跑 Docker 時沒有 PORT
CMD ["sh", "-c", "gunicorn -k uvicorn.workers.UvicornWorker questforge_server.main:app --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120"]
