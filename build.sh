#!/usr/bin/env bash

set -o errexit

echo "📦 Configurando ChromeDriver..."

# Obtém versão do Chromium
CHROME_VERSION=$(chromium --version | grep -oP '\d+\.\d+\.\d+')

# Busca ChromeDriver compatível
CHROMEDRIVER_URL=$(curl -s "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json" \
  | jq -r --arg ver "$CHROME_VERSION" '.versions[] | select(.version | test("^" + $ver)) | .downloads.chromedriver[] | select(.platform == "linux64") | .url')

wget -O chromedriver.zip "$CHROMEDRIVER_URL"

unzip chromedriver.zip

mv chromedriver-linux64/chromedriver /usr/bin/chromedriver

chmod +x /usr/bin/chromedriver

echo "✅ ChromeDriver instalado"