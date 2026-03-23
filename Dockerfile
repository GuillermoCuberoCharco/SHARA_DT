FROM node:20-bullseye AS frontend-builder

WORKDIR /app/src/web

COPY src/web/package.json src/web/yarn.lock src/web/.yarnrc.yml ./
RUN yarn install --non-interactive

COPY src/web/ ./
RUN yarn build

FROM python:3.10-bullseye AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app/src/server_flask

COPY src/server_flask/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/server_flask/ ./
COPY --from=frontend-builder /app/src/web/dist ./static

CMD ["python", "app.py"]
