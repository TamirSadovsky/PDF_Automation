FROM python:3.11-slim

# Microsoft ODBC Driver 18 + unixODBC
RUN apt-get update && \
    apt-get install -y curl gnupg apt-transport-https ca-certificates && \
    curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - && \
    curl https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/microsoft-prod.list && \
    apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app
ENV PORT=8000
CMD ["gunicorn","-w","1","--threads","2","--timeout","120","-b","0.0.0.0:${PORT}","main:app"]  # change to app:app if your file is app.py
