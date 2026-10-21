FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CAIRN_WIDGET_DIST=/app/widget/dist
COPY backend/pyproject.toml backend/
COPY backend/cairn backend/cairn
RUN pip install --no-cache-dir ./backend
COPY widget/dist widget/dist
WORKDIR /app/backend
EXPOSE 8000
CMD ["sh", "-c", "cairn db migrate && cairn seed && uvicorn cairn.api.app:app --host 0.0.0.0 --port 8000"]
