FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY sigiltree/ sigiltree/

RUN pip install --no-cache-dir .

COPY artifacts/ artifacts/

EXPOSE 8080

CMD ["python", "-m", "sigiltree.cli", "serve", "artifacts", "--host", "0.0.0.0", "--port", "8080"]
