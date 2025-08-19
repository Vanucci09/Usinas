FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Dependências do SO (Bookworm)
RUN set -eux; \
  apt-get update; \
  apt-get install -y --no-install-recommends \
    wget curl unzip gnupg ca-certificates \
    pkg-config build-essential \
    fonts-liberation \
    libayatana-appindicator3-1 \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdbus-1-3 \
    libgdk-pixbuf-2.0-0 libnspr4 libnss3 libx11-xcb1 libxcomposite1 \
    libxdamage1 libxrandr2 xdg-utils libu2f-udev libvulkan1 \
    libxkbcommon0 libxshmfence1 libdrm2 libgbm1 libgtk-3-0 \
    libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
    # opcionais úteis p/ Chrome headless
    libxss1 lsb-release; \
  # MySQL/MariaDB headers
  if apt-cache show default-libmysqlclient-dev >/dev/null 2>&1; then \
    apt-get install -y --no-install-recommends default-libmysqlclient-dev; \
  else \
    apt-get install -y --no-install-recommends libmariadb-dev-compat libmariadb-dev; \
  fi; \
  apt-get clean; \
  rm -rf /var/lib/apt/lists/*

# Repositório do Google Chrome
RUN set -eux; \
  curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /usr/share/keyrings/google.gpg; \
  echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list; \
  apt-get update; \
  apt-get install -y --no-install-recommends google-chrome-stable; \
  apt-mark hold google-chrome-stable; \
  apt-get clean; \
  rm -rf /var/lib/apt/lists/*

# ChromeDriver compatível com a versão major do Chrome
RUN set -eux; \
  CHROME_VERSION="$(google-chrome --version | awk '{print $3}')" ; \
  CHROME_MAJOR="${CHROME_VERSION%%.*}" ; \
  DRIVER_VERSION="$(curl -fsSL "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_${CHROME_MAJOR}")" ; \
  URL1="https://chromedriver.storage.googleapis.com/${DRIVER_VERSION}/chromedriver_linux64.zip" ; \
  URL2="https://chromedriver.storage.googleapis.com/${DRIVER_VERSION}/chromedriver-linux64.zip" ; \
  if curl -fsI "$URL1" >/dev/null; then URL="$URL1"; else URL="$URL2"; fi; \
  wget -q -O /tmp/chromedriver.zip "$URL"; \
  unzip /tmp/chromedriver.zip -d /usr/local/bin/; \
  if [ -f /usr/local/bin/chromedriver ]; then \
    mv /usr/local/bin/chromedriver /usr/bin/chromedriver; \
  else \
    mv /usr/local/bin/chromedriver*/chromedriver /usr/bin/chromedriver; \
  fi; \
  chmod +x /usr/bin/chromedriver; \
  rm -rf /tmp/chromedriver.zip /usr/local/bin/chromedriver*

ENV CHROME_BIN=/usr/bin/google-chrome
ENV PATH="${PATH}:/usr/bin"

WORKDIR /app
COPY . /app

# Cache de pacotes pip para builds mais rápidos
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install -r requirements.txt

CMD ["python", "app.py"]
