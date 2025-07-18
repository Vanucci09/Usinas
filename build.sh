#!/usr/bin/env bash

echo "📦 Instalando Chromium e ChromeDriver..."

# Atualiza os pacotes
apt-get update && apt-get install -y wget unzip

# Instala o Chromium
apt-get install -y chromium

# Baixa e instala o ChromeDriver compatível
CHROME_VERSION=$(chromium --version | grep -oP '\d+\.\d+\.\d+')
CHROMEDRIVER_VERSION=$(wget -qO- "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json" | grep -A 2 $CHROME_VERSION | grep "linux64" | grep -oP 'https:\/\/[^"]+')
wget -O chromedriver.zip $CHROMEDRIVER_VERSION
unzip chromedriver.zip
mv chromedriver /usr/bin/chromedriver
chmod +x /usr/bin/chromedriver

echo "✅ Chromium e ChromeDriver instalados."
