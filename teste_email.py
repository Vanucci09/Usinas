from flask import Flask
from flask_mail import Mail, Message
import pdfkit
import tempfile
import os

app = Flask(__name__)

# Configurações do Flask-Mail (substitua com as suas)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'posvenda@cgrenergia.com.br'  # 👈 seu email
app.config['MAIL_PASSWORD'] = 'edtz zhfj oflx pqpc'         # 👈 sua senha de app (Gmail)
app.config['MAIL_DEFAULT_SENDER'] = app.config['MAIL_USERNAME']

mail = Mail(app)

with app.app_context():
    try:
        # Caminho para o wkhtmltopdf instalado
        path_wkhtmltopdf = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'
        config = pdfkit.configuration(wkhtmltopdf=path_wkhtmltopdf)
        pdf_options = {'enable-local-file-access': ''}

        # HTML de exemplo
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>PDF de Teste</title>
        </head>
        <body>
            <h1>Este é um PDF de teste</h1>
            <p>Gerado com PDFKit e enviado via Flask-Mail.</p>
        </body>
        </html>
        """

        # Gera PDF temporário
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            caminho_pdf = tmp.name
            pdfkit.from_string(html, caminho_pdf, configuration=config, options=pdf_options)

        # Envia o e-mail
        msg = Message(
            subject='Teste de Envio com PDF',
            recipients=['felipe_11sul@hotmail.com'],  # 👈 substitua pelo e-mail de destino
            body='Olá! Este é um e-mail de teste com anexo PDF.'
        )

        with open(caminho_pdf, 'rb') as f:
            msg.attach("teste.pdf", 'application/pdf', f.read())

        mail.send(msg)
        print("✅ E-mail com PDF enviado com sucesso!")

    except Exception as e:
        print(f"❌ Erro ao enviar e-mail: {e}")

    finally:
        # Limpa o arquivo temporário
        if 'caminho_pdf' in locals() and os.path.exists(caminho_pdf):
            os.unlink(caminho_pdf)
