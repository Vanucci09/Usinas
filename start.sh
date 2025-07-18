#!/usr/bin/env bash

echo "📦 Instalando Chromium e ChromeDriver..."

apt-get update && apt-get install -y wget unzip curl jq chromium

CHROME_VERSION=$(chromium --version | grep -oP '\d+\.\d+\.\d+')

CHROMEDRIVER_URL=$(curl -s "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json" \
  | jq -r --arg ver "$CHROME_VERSION" '.versions[] | select(.version | test("^" + $ver)) | .downloads.chromedriver[] | select(.platform == "linux64") | .url')

wget -O chromedriver.zip "$CHROMEDRIVER_URL"
unzip chromedriver.zip
mv chromedriver-linux64/chromedriver /usr/bin/chromedriver
chmod +x /usr/bin/chromedriver

echo "✅ Pronto, iniciando app..."
exec gunicorn app:app
