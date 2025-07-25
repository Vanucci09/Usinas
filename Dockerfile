FROM python:3.11-slim

# Instala dependências básicas
RUN apt-get update && apt-get install -y \
    wget curl unzip gnupg ca-certificates fonts-liberation \
    libnss3 libxss1 libasound2 libatk-bridge2.0-0 libgtk-3-0 \
    default-libmysqlclient-dev build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Adiciona o repositório oficial do Google Chrome
RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list

# Instala o Google Chrome e congela a versão desejada (114)
RUN apt-get update && \
    apt-get install -y google-chrome-stable=114.0.5735.90-1 && \
    apt-mark hold google-chrome-stable

# Instala o ChromeDriver correspondente
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
