#!/usr/bin/env bash

set -o errexit

echo "📦 Instalando dependências..."

# Atualiza pacotes
apt-get update

# Instala dependências Linux
apt-get install -y \
wget \
unzip \
curl \
jq \
chromium \
tesseract-ocr

echo "✅ Tesseract instalado"

echo "VERSAO TESSERACT:"
tesseract --version

# Obtém versão do Chromium
CHROME_VERSION=$(chromium --version | grep -oP '\d+\.\d+\.\d+')

echo "📦 Versão Chromium:"
echo "$CHROME_VERSION"

# Busca ChromeDriver compatível
CHROMEDRIVER_URL=$(curl -s "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json" \
  | jq -r --arg ver "$CHROME_VERSION" '.versions[] | select(.version | test("^" + $ver)) | .downloads.chromedriver[] | select(.platform == "linux64") | .url')

echo "📦 Download ChromeDriver..."

wget -O chromedriver.zip "$CHROMEDRIVER_URL"

unzip chromedriver.zip

mv chromedriver-linux64/chromedriver /usr/bin/chromedriver

chmod +x /usr/bin/chromedriver

echo "✅ Chromium e ChromeDriver instalados."