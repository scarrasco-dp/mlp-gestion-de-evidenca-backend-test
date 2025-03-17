FROM ghcr.io/esri/arcgis-python-api-notebook:2.3.0

WORKDIR /app

ENV FRONTEND_URL="*"
ENV SELENIUM_MANAGER="0"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar Playwright y sus navegadores
RUN playwright install

COPY ./app /app

USER root

RUN apt-get update && apt-get install -y \
    wget \
    gnupg2 \
    unzip \
    libnss3 \
    libgconf-2-4 \
    libxss1 \
    libappindicator1 \
    libindicator7 \
    fonts-liberation \
    xdg-utils \
    --no-install-recommends && \
    wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - && \
    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && apt-get install -y google-chrome-stable --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
