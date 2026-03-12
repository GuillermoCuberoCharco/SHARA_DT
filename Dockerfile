FROM node:20-bullseye AS frontend-builder

WORKDIR /app/src/web

COPY src/web/package.json src/web/yarn.lock src/web/.yarnrc.yml ./
RUN npm install -g yarn@1.22.22 && yarn install --frozen-lockfile

COPY src/web/ ./
RUN yarn build

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app/src/server_flask

COPY src/server_flask/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/server_flask/ ./
COPY --from=frontend-builder /app/src/web/dist ./static

CMD ["python", "app.py"]
