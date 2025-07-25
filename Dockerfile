FROM python:3.11-slim

# Instala dependências básicas
RUN apt-get update && apt-get install -y \
    wget unzip curl gnupg \
    fonts-liberation libnss3 libxss1 libasound2 libatk-bridge2.0-0 libgtk-3-0 \
    default-libmysqlclient-dev build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Instala Google Chrome 114
RUN wget -q https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_114.0.5735.90-1_amd64.deb && \
    apt-get update && \
    apt-get install -y ./google-chrome-stable_114.0.5735.90-1_amd64.deb && \
    rm google-chrome-stable_114.0.5735.90-1_amd64.deb

# Instala ChromeDriver 114
RUN wget -q https://chromedriver.storage.googleapis.com/114.0.5735.90/chromedriver_linux64.zip && \
    unzip chromedriver_linux64.zip && \
    mv chromedriver /usr/bin/chromedriver && \
    chmod +x /usr/bin/chromedriver && \
    rm chromedriver_linux64.zip

# Define variáveis de ambiente
ENV CHROME_BIN=/usr/bin/google-chrome
ENV PATH="${PATH}:/usr/bin"

# Cria diretório de trabalho
WORKDIR /app

# Copia os arquivos do projeto
COPY . .

# Instala dependências do Python
RUN pip install --upgrade pip && pip install -r requirements.txt

# Expõe a porta usada pela aplicação
EXPOSE 10000

# Define variável de ambiente indicando que está em produção
ENV RENDER=1

# Comando para iniciar o app com Gunicorn
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000"]
