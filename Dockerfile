FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

ENV PYTHONPATH=/app/src
ENV PORT=8000
EXPOSE 8000

CMD ["bash", "-lc", "uvicorn questforge_server.main:app --host 0.0.0.0 --port ${PORT}"]
