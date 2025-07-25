FROM python:3.11-slim

# Instala dependências básicas do sistema
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    unzip \
    gnupg \
    ca-certificates \
    python3 \
    python3-pip \
    pkg-config \
    default-libmysqlclient-dev \
    build-essential \
    fonts-liberation \
    libappindicator3-1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libgdk-pixbuf2.0-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    libu2f-udev \
    libvulkan1 \
    && rm -rf /var/lib/apt/lists/*

# Instala o Google Chrome mais recente (geralmente v138+)
RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && \
    apt-get install -y google-chrome-stable && \
    apt-mark hold google-chrome-stable

# Instala o ChromeDriver compatível com a versão do Chrome instalada (v138)
RUN wget -q https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/138.0.7204.168/linux64/chromedriver-linux64.zip && \
    unzip chromedriver-linux64.zip && \
    mv chromedriver-linux64/chromedriver /usr/bin/chromedriver && \
    chmod +x /usr/bin/chromedriver && \
    rm -rf chromedriver-linux64*

# Define variáveis de ambiente para o Chrome
ENV CHROME_BIN=/usr/bin/google-chrome
ENV PATH="${PATH}:/usr/bin"

# Cria diretório de trabalho
WORKDIR /app

# Copia os arquivos do projeto
COPY . /app

# Instala as dependências Python
RUN pip install --upgrade pip && pip install -r requirements.txt

# Define o comando padrão (ajuste se estiver usando Gunicorn ou Flask direto)
CMD ["python", "app.py"]
