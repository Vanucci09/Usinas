FROM python:3.11-slim

# 🧱 Define snapshot do Debian para versão 132 do Chromium
RUN echo "deb http://snapshot.debian.org/archive/debian/20240101T000000Z bookworm main" > /etc/apt/sources.list.d/snapshot.list \
    && echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid-until

# ⚙️ Instala dependências e Chromium 132 fixo
RUN apt-get update && apt-get install -y \
    chromium=132.0.6261.111-1 \
    chromium-driver=132.0.6261.111-1 \
    wget \
    unzip \
    curl \
    jq \
    fonts-liberation \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config \
    && apt-mark hold chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Define o caminho do executável do Chromium (para uc.Chrome e Selenium)
ENV CHROME_BIN=/usr/bin/chromium
ENV PATH="${PATH}:/usr/bin"

# Diretório de trabalho
WORKDIR /app

# Copia o projeto
COPY . .

# Instala pacotes Python
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Porta do app
EXPOSE 10000

# Sinaliza ambiente de produção
ENV RENDER=1

# Inicializa o app com Gunicorn
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000"]
