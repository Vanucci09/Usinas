FROM python:3.11-slim

# Instala dependências e adiciona chave do repositório do Chrome
RUN apt-get update && apt-get install -y \
    wget gnupg curl unzip fonts-liberation libnss3 libxss1 libasound2 \
    libatk-bridge2.0-0 libgtk-3-0 default-libmysqlclient-dev build-essential pkg-config \
 && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
 && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list

# Instala a versão mais recente do Google Chrome stable
RUN apt-get update && apt-get install -y google-chrome-stable

# Descobre a versão exata do Chrome instalado
RUN CHROME_VERSION=$(google-chrome --version | awk '{print $3}' | cut -d '.' -f 1-3) && \
    DRIVER_VERSION=$(curl -s "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_$CHROME_VERSION") && \
    wget -q "https://chromedriver.storage.googleapis.com/$DRIVER_VERSION/chromedriver_linux64.zip" && \
    unzip chromedriver_linux64.zip && \
    mv chromedriver /usr/bin/chromedriver && \
    chmod +x /usr/bin/chromedriver && \
    rm chromedriver_linux64.zip

# Define variáveis de ambiente
ENV CHROME_BIN=/usr/bin/google-chrome
ENV PATH="${PATH}:/usr/bin"

# Define diretório de trabalho
WORKDIR /app

# Copia arquivos da aplicação
COPY . .

# Instala dependências Python
RUN pip install --upgrade pip && pip install -r requirements.txt

# Define variável de ambiente para produção
ENV RENDER=1

# Expõe a porta do Flask
EXPOSE 10000

# Inicia a aplicação com Gunicorn
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000"]
