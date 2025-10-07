# ---------- Dockerfile (Render) ----------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# System deps + Microsoft repo (no apt-key)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl gnupg ca-certificates apt-transport-https \
        unixodbc unixodbc-dev libgssapi-krb5-2 && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
      | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg && \
    printf "Types: deb\nURIs: https://packages.microsoft.com/debian/12/prod/\nSuites: bookworm\nComponents: main\nSigned-By: /etc/apt/keyrings/microsoft.gpg\n" \
      > /etc/apt/sources.list.d/microsoft-prod.sources && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# App setup
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

# Gunicorn listens on $PORT provided by Render
CMD ["gunicorn", "-w", "1", "--threads", "2", "--timeout", "120", "-b", "0.0.0.0:${PORT}", "main:app"]
