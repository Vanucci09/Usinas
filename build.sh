#!/usr/bin/env bash

echo "📦 Instalando Chromium e ChromeDriver..."

# Atualiza os pacotes
apt-get update && apt-get install -y \
wget \
unzip \
curl \
jq \
tesseract-ocr

# Instala o Chromium
apt-get install -y chromium

# Obtém a versão do Chromium instalada
CHROME_VERSION=$(chromium --version | grep -oP '\d+\.\d+\.\d+')

# Busca o ChromeDriver compatível
CHROMEDRIVER_URL=$(curl -s "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json" \
  | jq -r --arg ver "$CHROME_VERSION" '.versions[] | select(.version | test("^" + $ver)) | .downloads.chromedriver[] | select(.platform == "linux64") | .url')

# Faz o download e instalação
wget -O chromedriver.zip "$CHROMEDRIVER_URL"

unzip chromedriver.zip

mv chromedriver-linux64/chromedriver /usr/bin/chromedriver

chmod +x /usr/bin/chromedriver

echo "✅ Chromium e ChromeDriver instalados."
echo "✅ Tesseract instalado."