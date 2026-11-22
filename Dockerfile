FROM node:22-bookworm-slim AS frontend
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app/ ./app/
COPY backend/data/characters/ ./data/characters/
COPY --from=frontend /web/dist/ ./web/
CMD ["python", "-m", "uvicorn", "app.web:app", "--host", "0.0.0.0", "--port", "8000"]
