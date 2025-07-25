FROM python:3.11-slim

# Instala dependências e adiciona chave do Google
RUN apt-get update && apt-get install -y wget gnupg curl unzip \
 && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
 && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google.list \
 && apt-get update

# Instala Google Chrome 114 (especificamente)
RUN apt-get install -y google-chrome-stable=114.0.5735.90-1

# Baixa ChromeDriver compatível
RUN CHROME_VERSION=114.0.5735.90 && \
    DRIVER_VERSION=$(curl -s "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_$CHROME_VERSION") && \
    wget -q "https://chromedriver.storage.googleapis.com/$DRIVER_VERSION/chromedriver_linux64.zip" && \
    unzip chromedriver_linux64.zip && \
    mv chromedriver /usr/bin/chromedriver && \
    chmod +x /usr/bin/chromedriver && \
    rm chromedriver_linux64.zip

# Instala bibliotecas do sistema
RUN apt-get install -y \
    fonts-liberation libnss3 libxss1 libasound2 libatk-bridge2.0-0 libgtk-3-0 \
    default-libmysqlclient-dev build-essential pkg-config \
 && rm -rf /var/lib/apt/lists/*

# Define variáveis de ambiente
ENV CHROME_BIN=/usr/bin/google-chrome
ENV PATH="${PATH}:/usr/bin"

# Define diretório de trabalho
WORKDIR /app

# Copia arquivos do projeto
COPY . .

# Instala dependências Python
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Define variáveis para o ambiente do Render
ENV RENDER=1

# Expõe porta do app
EXPOSE 10000

# Inicializa com Gunicorn
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000"]
