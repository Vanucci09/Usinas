FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Dependências de sistema (Bookworm)
RUN set -eux; \
  apt-get update; \
  apt-get install -y --no-install-recommends \
    wget curl unzip gnupg ca-certificates \
    pkg-config default-libmysqlclient-dev build-essential \
    fonts-liberation \
    # substitui libappindicator3-1 em Debian 12
    libayatana-appindicator3-1 \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdbus-1-3 \
    libgdk-pixbuf2.0-0 libnspr4 libnss3 libx11-xcb1 libxcomposite1 \
    libxdamage1 libxrandr2 xdg-utils libu2f-udev libvulkan1 \
  ; \
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

# Chromedriver compatível com o Chrome instalado
RUN set -eux; \
  CHROME_VERSION="$(google-chrome --version | awk '{print $3}')"; \
  CHROME_MAJOR="${CHROME_VERSION%%.*}"; \
  DRIVER_VERSION="$(curl -fsSL "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_${CHROME_MAJOR}")"; \
  wget -q -O /tmp/chromedriver.zip "https://chromedriver.storage.googleapis.com/${DRIVER_VERSION}/chromedriver_linux64.zip"; \
  unzip /tmp/chromedriver.zip -d /usr/local/bin/; \
  mv /usr/local/bin/chromedriver /usr/bin/chromedriver; \
  chmod +x /usr/bin/chromedriver; \
  rm -rf /tmp/chromedriver.zip

ENV CHROME_BIN=/usr/bin/google-chrome
ENV PATH="${PATH}:/usr/bin"

WORKDIR /app
COPY . /app

RUN pip install --upgrade pip && pip install -r requirements.txt

CMD ["python", "app.py"]
