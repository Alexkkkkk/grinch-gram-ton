FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e "."

# App code
COPY . .

# Data dir
RUN mkdir -p /app/data

ENV PYTHONPATH=/app
ENV PORT=3000

EXPOSE 3000

CMD ["python", "main.py"]
