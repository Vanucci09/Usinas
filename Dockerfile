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

# Repositório e instalação do Google Chrome
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

# ChromeDriver via Chrome for Testing (compatível com a versão major do Chrome)# ChromeDriver via Chrome for Testing (tenta a versão exata; se 404, usa known-good do major)
RUN set -eux; \
  CHROME_VERSION="$(google-chrome --version | awk '{print $3}')" ; \
  CHROME_MAJOR="${CHROME_VERSION%%.*}" ; \
  DIRECT_URL="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chromedriver-linux64.zip"; \
  if curl -fsI "$DIRECT_URL" >/dev/null; then \
    DRIVER_URL="$DIRECT_URL"; \
  else \
    JSON_URL="https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"; \
    curl -fsSL "$JSON_URL" -o /tmp/cft.json; \
    DRIVER_URL="$(python3 <<EOF
import json, os, sys
mj = os.environ.get("CHROME_MAJOR")
with open("/tmp/cft.json","r",encoding="utf-8") as f:
    data = json.load(f)
cands = [v for v in data["versions"] if v["version"].split(".")[0] == mj]
if not cands:
    sys.exit(1)
ver = cands[-1]
for d in ver["downloads"]["chromedriver"]:
    if d["platform"] == "linux64":
        print(d["url"], end="")
        break
EOF
)"; \
  fi; \
  test -n "$DRIVER_URL"; \
  wget -q -O /tmp/chromedriver.zip "$DRIVER_URL"; \
  unzip -o /tmp/chromedriver.zip -d /usr/local/bin/; \
  mv /usr/local/bin/chromedriver-linux64/chromedriver /usr/bin/chromedriver; \
  chmod +x /usr/bin/chromedriver; \
  rm -rf /usr/local/bin/chromedriver-linux64 /tmp/chromedriver.zip /tmp/cft.json

ENV CHROME_BIN=/usr/bin/google-chrome
ENV PATH="${PATH}:/usr/bin"

WORKDIR /app
COPY . /app

# Cache de pacotes pip para builds mais rápidos
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install -r requirements.txt

CMD ["python", "app.py"]
