FROM python:3.11-slim

# Instala dependências do sistema
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
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
    && rm -rf /var/lib/apt/lists/*

# Define o caminho do executável do Chromium (para uc.Chrome)
ENV CHROME_BIN=/usr/bin/chromium
ENV PATH="${PATH}:/usr/bin"

# Cria diretório de trabalho
WORKDIR /app

# Copia os arquivos do projeto
COPY . .

# Instala as dependências do Python
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Expõe a porta usada pela aplicação
EXPOSE 10000

# Comando para iniciar o app com Gunicorn
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000"]
