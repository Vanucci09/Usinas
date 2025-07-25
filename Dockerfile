FROM python:3.11-slim

# Instala dependências do sistema
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    unzip \
    gnupg \
    fonts-liberation \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Adiciona chave e repositório do Google Chrome
RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list

# Instala a versão mais recente do Google Chrome
RUN apt-get update && \
    apt-get install -y google-chrome-stable && \
    apt-mark hold google-chrome-stable

# Instala o ChromeDriver compatível com o Chrome instalado
RUN CHROME_VERSION=$(google-chrome --version | awk '{print $3}' | cut -d '.' -f 1-3) && \
    DRIVER_VERSION=$(curl -s "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_$CHROME_VERSION") && \
    wget -q "https://chromedriver.storage.googleapis.com/${DRIVER_VERSION}/chromedriver_linux64.zip" && \
    unzip chromedriver_linux64.zip && \
    mv chromedriver /usr/bin/chromedriver && \
    chmod +x /usr/bin/chromedriver && \
    rm chromedriver_linux64.zip

# Define o caminho do executável do Chrome (para uc.Chrome)
ENV CHROME_BIN=/usr/bin/google-chrome
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

# Define variável de ambiente indicando que está em produção
ENV RENDER=1

# Comando para iniciar o app com Gunicorn
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000"]
