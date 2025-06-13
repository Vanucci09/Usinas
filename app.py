from flask import Flask, render_template, request, redirect, url_for, jsonify, make_response, send_file, flash
from datetime import date, datetime, timedelta
from calendar import monthrange
import os
import pandas as pd
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import Numeric, text, func, extract
from decimal import Decimal, ROUND_HALF_UP
import fitz, tempfile
from PIL import Image
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import time, hashlib, json, hmac, requests, base64, atexit
from email.utils import formatdate
from apscheduler.schedulers.background import BackgroundScheduler
from flask_mail import Mail, Message
from urllib.parse import quote
import base64


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "12345678-1")

# Configuração do banco de dados PostgreSQL
db_url = os.getenv('DATABASE_URL', 'postgresql://postgres:Fl%40mengo09@localhost:5432/usinas_db')

# Corrige o prefixo caso venha como 'postgres://' do Render
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

SOLIS_KEY_ID     = os.getenv("SOLIS_KEY_ID")
SOLIS_KEY_SECRET = os.getenv("SOLIS_KEY_SECRET")
SOLIS_BASE_URL   = os.getenv("SOLIS_BASE_URL", "https://www.soliscloud.com:13333")

if not SOLIS_KEY_ID or not SOLIS_KEY_SECRET:
    raise RuntimeError("As variáveis de ambiente SOLIS_KEY_ID e SOLIS_KEY_SECRET precisam estar definidas.")

app.config['MAIL_SERVER'] = 'smtp.gmail.com'  # ou outro servidor
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'posvenda@cgrenergia.com.br'
app.config['MAIL_PASSWORD'] = 'edtz zhfj oflx pqpc'
app.config['MAIL_DEFAULT_SENDER'] = 'posvenda@cgrenergia.com.br'

mail = Mail(app)


@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

# Modelos
class Usina(db.Model):
    __tablename__ = 'usinas'
    id = db.Column(db.Integer, primary_key=True)
    cc = db.Column(db.String, nullable=False)
    nome = db.Column(db.String, nullable=False)
    potencia_kw = db.Column(db.Float, nullable=True)
    rateios = db.relationship('Rateio', backref='usina', cascade="all, delete-orphan")
    logo_url = db.Column(db.String(200))
    
class Inversor(db.Model):
    """
    Cada registro aqui representa um inversor (device) da Solis,
    vinculado a uma única usina. Uma usina pode ter vários inversores.
    """
    __tablename__ = 'inversores'
    id = db.Column(db.Integer, primary_key=True)
    inverter_sn = db.Column(db.String, unique=True, nullable=False)
    usina_id = db.Column(db.Integer, db.ForeignKey('usinas.id'), nullable=False)

    usina = db.relationship('Usina', backref='inversores')

class Geracao(db.Model):
    __tablename__ = 'geracoes'
    id = db.Column(db.Integer, primary_key=True)
    usina_id = db.Column(db.Integer, db.ForeignKey('usinas.id'))
    data = db.Column(db.Date, nullable=False)
    energia_kwh = db.Column(db.Float)
    
class GeracaoInversor(db.Model):
    __tablename__ = 'geracoes_inversores'
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, nullable=False)
    inverter_sn = db.Column(db.String, nullable=False)
    etoday = db.Column(db.Float)
    etotal = db.Column(db.Float)
    usina_id = db.Column(db.Integer, db.ForeignKey('usinas.id'))

class Cliente(db.Model):
    __tablename__ = 'clientes'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String, nullable=False)
    cpf_cnpj = db.Column(db.String, nullable=False)
    endereco = db.Column(db.String, nullable=False)
    codigo_unidade = db.Column(db.String, nullable=False)
    usina_id = db.Column(db.Integer, db.ForeignKey('usinas.id'), nullable=False)
    email = db.Column(db.String, nullable=True)
    telefone = db.Column(db.String, nullable=True)

    rateios = db.relationship('Rateio', backref='cliente', cascade="all, delete-orphan")
    usina = db.relationship('Usina')

class Rateio(db.Model):
    __tablename__ = 'rateios'
    id = db.Column(db.Integer, primary_key=True)
    usina_id = db.Column(db.Integer, db.ForeignKey('usinas.id'), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    percentual = db.Column(db.Float, nullable=False)
    tarifa_kwh = db.Column(db.Float, nullable=False)
    codigo_rateio = db.Column(db.Integer, nullable=True)
    
class FaturaMensal(db.Model):
    __tablename__ = 'faturas_mensais'
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    mes_referencia = db.Column(db.Integer, nullable=False)
    ano_referencia = db.Column(db.Integer, nullable=False)
    inicio_leitura = db.Column(db.Date, nullable=False)
    fim_leitura = db.Column(db.Date, nullable=False)
    tarifa_neoenergia = db.Column(Numeric(10, 7), nullable=False)
    icms = db.Column(db.Float, nullable=False)
    consumo_total = db.Column(db.Float, nullable=False)
    consumo_neoenergia = db.Column(db.Float, nullable=False)
    consumo_usina = db.Column(db.Float, nullable=False)
    saldo_unidade = db.Column(db.Float, nullable=False)
    injetado = db.Column(db.Float, nullable=False)
    valor_conta_neoenergia = db.Column(db.Float, nullable=False)
    identificador = db.Column(db.String, unique=True, nullable=False)

    cliente = db.relationship('Cliente', backref='faturas')
    
class PrevisaoMensal(db.Model):
    __tablename__ = 'previsoes_mensais'
    id = db.Column(db.Integer, primary_key=True)
    usina_id = db.Column(db.Integer, db.ForeignKey('usinas.id'), nullable=False)
    ano = db.Column(db.Integer, nullable=False)
    mes = db.Column(db.Integer, nullable=False)  # 1 a 12
    previsao_kwh = db.Column(db.Float, nullable=False)

    usina = db.relationship('Usina', backref='previsoes')

class CategoriaDespesa(db.Model):
    __tablename__ = 'categorias_despesa'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    
    despesas = db.relationship('FinanceiroUsina', backref='categoria')

class FinanceiroUsina(db.Model):
    __tablename__ = 'financeiro_usina'
    id = db.Column(db.Integer, primary_key=True)
    usina_id = db.Column(db.Integer, db.ForeignKey('usinas.id'), nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias_despesa.id'), nullable=True)
    data = db.Column(db.Date, nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # 'receita' ou 'despesa'
    descricao = db.Column(db.String(255), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    referencia_mes = db.Column(db.Integer, nullable=True)
    referencia_ano = db.Column(db.Integer, nullable=True)

    usina = db.relationship('Usina', backref='financeiros')
    
class Usuario(db.Model, UserMixin):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String, nullable=False)
    email = db.Column(db.String, unique=True, nullable=False)
    senha_hash = db.Column(db.String, nullable=False)
    pode_cadastrar_geracao = db.Column(db.Boolean, default=False)
    pode_cadastrar_cliente = db.Column(db.Boolean, default=False)
    pode_cadastrar_fatura = db.Column(db.Boolean, default=False)
    pode_acessar_financeiro = db.Column(db.Boolean, default=False)

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def verificar_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)


# Pasta para uploads
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/cadastrar_usina', methods=['GET', 'POST'])
@login_required
def cadastrar_usina():
    if request.method == 'POST':
        logo = request.files.get('logo')
        cc = request.form['cc']
        nome = request.form['nome']
        potencia = request.form['potencia']
        ano_atual = date.today().year

        nova_usina = Usina(cc=cc, nome=nome, potencia_kw=potencia)
        db.session.add(nova_usina)
        db.session.commit()

        # Salvar o logo se enviado
        if logo and logo.filename != '':
            filename = secure_filename(logo.filename)

            # Define o caminho com base no ambiente
            if os.getenv('FLASK_ENV') == 'production':
                caminho_base = '/data/logos'
            else:
                caminho_base = os.path.join('static', 'logos')

            os.makedirs(caminho_base, exist_ok=True)  # Garante que a pasta existe

            caminho_logo = os.path.join(caminho_base, filename)
            logo.save(caminho_logo)

            nova_usina.logo_url = filename
            db.session.commit()

        # Previsões mensais
        for mes in range(1, 13):
            chave = f'previsoes[{mes}]'
            valor = request.form.get(chave)
            if valor:
                previsao = PrevisaoMensal(
                    usina_id=nova_usina.id,
                    ano=ano_atual,
                    mes=mes,
                    previsao_kwh=float(valor.replace(',', '.'))
                )
                db.session.add(previsao)

        db.session.commit()
        return redirect(url_for('cadastrar_usina'))

    return render_template('cadastrar_usina.html', env=os.getenv('FLASK_ENV'))

@app.route('/cadastrar_geracao', methods=['GET', 'POST'])
@login_required
def cadastrar_geracao():
    if not current_user.pode_cadastrar_geracao:
        return "Acesso negado", 403
    usinas = Usina.query.all()
    if request.method == 'POST':
        usina_id = request.form['usina_id']
        data = datetime.strptime(request.form['data'], '%Y-%m-%d').date()
        energia = float(request.form['energia'])

        existente = Geracao.query.filter_by(usina_id=usina_id, data=data).first()
        if existente:
            return render_template('cadastrar_geracao.html', usinas=usinas, mensagem="Já existe um registro para esta usina nesta data.")

        nova_geracao = Geracao(usina_id=usina_id, data=data, energia_kwh=energia)
        db.session.add(nova_geracao)
        db.session.commit()
        return redirect(url_for('cadastrar_geracao'))

    return render_template('cadastrar_geracao.html', usinas=usinas)

@app.route('/listar_geracoes')
@login_required
def listar_geracoes():
    data_inicio = request.args.get('data_inicio', date.today().replace(day=1))
    data_fim = request.args.get('data_fim', date.today())
    usina_id = request.args.get('usina_id')

    query = """
        SELECT g.id as id_geracao, u.nome, g.data, g.energia_kwh
        FROM geracoes g
        JOIN usinas u ON g.usina_id = u.id
        WHERE g.data BETWEEN :data_inicio AND :data_fim
        {filtro_usina}
        ORDER BY g.data DESC
    """.format(filtro_usina="AND u.id = :usina_id" if usina_id else "")

    params = {'data_inicio': data_inicio, 'data_fim': data_fim}
    if usina_id:
        params['usina_id'] = usina_id

    result = db.session.execute(text(query), params)
    geracoes = result.fetchall()
    usinas = Usina.query.all()

    return render_template('listar_geracoes.html', geracoes=geracoes, usinas=usinas,
                           data_inicio_default=data_inicio, data_fim_default=data_fim)

@app.route('/editar_geracao/<int:id>', methods=['GET', 'POST'])
def editar_geracao(id):
    geracao = Geracao.query.get_or_404(id)
    if request.method == 'POST':
        nova_energia = float(request.form['energia'])
        geracao.energia_kwh = nova_energia
        db.session.commit()
        return redirect(url_for('listar_geracoes'))

    usina = Usina.query.get(geracao.usina_id)
    return render_template('editar_geracao.html', geracao=geracao, usina=usina)

@app.route('/excluir_geracao/<int:id>', methods=['GET'])
def excluir_geracao(id):
    geracao = Geracao.query.get_or_404(id)
    db.session.delete(geracao)
    db.session.commit()
    return redirect(url_for('listar_geracoes'))

@app.route('/consulta')
@login_required
def consulta():
    usina_id = request.args.get('usina_id', '')
    data_inicio = request.args.get('data_inicio', date.today().replace(day=1).isoformat())
    data_fim = request.args.get('data_fim', date.today().isoformat())

    query = db.session.query(Geracao, Usina).join(Usina).filter(Geracao.data.between(data_inicio, data_fim))
    if usina_id:
        query = query.filter(Usina.id == usina_id)

    resultados = query.order_by(Geracao.data.asc()).all()
    usinas = Usina.query.all()

    total = 0
    data = []
    dias = []
    geracoes = []
    previsoes = []

    for geracao, usina in resultados:
        dias_no_mes = monthrange(geracao.data.year, geracao.data.month)[1]
        previsao_registro = PrevisaoMensal.query.filter_by(
            usina_id=usina.id,
            ano=geracao.data.year,
            mes=geracao.data.month
        ).first()
        previsao_mensal = previsao_registro.previsao_kwh if previsao_registro else 0
        previsao_diaria = previsao_mensal / dias_no_mes if dias_no_mes else 0
        producao_negativa = geracao.energia_kwh < previsao_diaria

        data.append({
            'nome': usina.nome,
            'data': geracao.data,
            'energia_kwh': geracao.energia_kwh,
            'previsao_diaria': previsao_diaria,
            'producao_negativa': producao_negativa,
        })

        dias.append(geracao.data.day)
        geracoes.append(geracao.energia_kwh)
        previsoes.append(previsao_diaria)
        total += geracao.energia_kwh

    return render_template('consulta.html', resultados=data, total=total, usinas=usinas, usina_id=usina_id,
                           data_inicio=data_inicio, data_fim=data_fim, dias=dias, geracoes=geracoes, previsoes=previsoes)

@app.route('/producao_mensal/<int:usina_id>/<int:ano>/<int:mes>')
@login_required
def producao_mensal(usina_id, ano, mes):
    usina = Usina.query.get_or_404(usina_id)

    # Define intervalo do mês
    data_inicio = date(ano, mes, 1)
    data_fim = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)
    
    resultados = Geracao.query.filter(
        Geracao.usina_id == usina_id,
        Geracao.data >= data_inicio,
        Geracao.data < data_fim
    ).order_by(Geracao.data).all()

    dias_mes = monthrange(ano, mes)[1]
    totais = [0.0] * dias_mes
    detalhes = []
    soma = 0.0

    for r in resultados:
        dia = r.data.day
        totais[dia - 1] = r.energia_kwh
        soma += r.energia_kwh
        detalhes.append({'data': r.data, 'energia_kwh': r.energia_kwh})
    
    dias_com_dado = len(resultados)
    media_diaria = soma / dias_com_dado if dias_com_dado > 0 else 0.0
    previsao_total = round(media_diaria * dias_mes, 2)
    
    previsao_registro = PrevisaoMensal.query.filter_by(
        usina_id=usina_id, ano=ano, mes=mes
    ).first()
    valor_mensal = previsao_registro.previsao_kwh if previsao_registro else 0.0
    previsao_diaria_padrao = (valor_mensal / dias_mes) if dias_mes else 0.0
    previsoes = [round(previsao_diaria_padrao, 2) for _ in range(dias_mes)]

    inicio_ano = date(ano, 1, 1)
    fim_periodo = data_fim - timedelta(days=1)  
    ano_sum = db.session.query(func.coalesce(func.sum(Geracao.energia_kwh), 0.0)).filter(
        Geracao.usina_id == usina_id,
        Geracao.data >= inicio_ano,
        Geracao.data <= fim_periodo
    ).scalar() or 0.0

    # Receita bruta e líquida acumuladas no ano
    ano_bruto = round(ano_sum * 0.83, 2)
    ano_liquido = round(ano_bruto * 0.80, 2)

    usinas = Usina.query.all()

    return render_template(
        'producao_mensal.html',
        usina_nome=usina.nome,
        potencia_kw=usina.potencia_kw,
        usina_id=usina_id,
        ano=ano,
        mes=mes,
        usinas=usinas,
        meses=[str(i + 1) for i in range(dias_mes)],
        totais=totais,
        detalhes=detalhes,
        soma_total=soma,
        media_diaria=round(media_diaria, 2),
        previsao_total=previsao_total,
        previsoes=previsoes,
        previsao_mensal=round(valor_mensal, 2),
        ano_geracao_total=round(ano_sum, 2),
        ano_faturamento_bruto=ano_bruto,
        ano_faturamento_liquido=ano_liquido,
        dias_no_mes=dias_mes
    )

@app.route('/clientes_da_usina/<int:usina_id>')
def clientes_da_usina(usina_id):
    clientes = Cliente.query.filter_by(usina_id=usina_id).all()
    return jsonify([{"id": c.id, "nome": c.nome} for c in clientes])

@app.route('/importar_planilha', methods=['GET', 'POST'])
def importar_planilha():
    mensagem = ''
    usinas = Usina.query.all()

    if request.method == 'POST':
        arquivo = request.files.get('arquivo')
        usina_id = request.form.get('usina_id')

        if not usina_id:
            mensagem = "Selecione uma usina."
        elif arquivo and arquivo.filename.endswith(('.xlsx', '.xls')):
            caminho = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(arquivo.filename))
            arquivo.save(caminho)

            try:
                df = pd.read_excel(caminho)
                if not {'data', 'energia_kwh'}.issubset(df.columns):
                    mensagem = "A planilha deve conter as colunas 'data' e 'energia_kwh'."
                else:
                    inseridos = 0
                    duplicados = 0

                    for _, linha in df.iterrows():
                        data = pd.to_datetime(linha['data']).date()
                        energia = linha['energia_kwh']
                        existente = Geracao.query.filter_by(usina_id=usina_id, data=data).first()
                        if existente:
                            duplicados += 1
                            continue

                        nova_geracao = Geracao(usina_id=usina_id, data=data, energia_kwh=energia)
                        db.session.add(nova_geracao)
                        inseridos += 1

                    db.session.commit()
                    mensagem = f"{inseridos} registros inseridos. {duplicados} ignorados por já existirem."
            except Exception as e:
                mensagem = f"Erro ao processar a planilha: {str(e)}"
        else:
            mensagem = "Envie um arquivo .xlsx ou .xls válido."

    return render_template('importar_planilha.html', mensagem=mensagem, usinas=usinas)

def formato_brasileiro(valor):
    try:
        return f"R$ {float(valor):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except (ValueError, TypeError):
        return "R$ 0,00"

def formato_tarifa(valor):
    try:
        return f"R$ {float(valor):,.7f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except (ValueError, TypeError):
        return "R$ 0,0000000"

app.jinja_env.filters['formato_brasileiro'] = formato_brasileiro
app.jinja_env.filters['formato_tarifa'] = formato_tarifa

@app.route('/clientes', methods=['GET', 'POST'])
@login_required
def cadastrar_cliente():
    if not current_user.pode_cadastrar_cliente:
        return "Acesso negado", 403
    
    usinas = Usina.query.all()
    
    if request.method == 'POST':
        nome = request.form['nome']
        cpf_cnpj = request.form['cpf_cnpj']
        endereco = request.form['endereco']
        codigo_unidade = request.form['codigo_unidade']
        usina_id = request.form['usina_id']
        email = request.form['email']
        telefone = request.form['telefone']

        cliente = Cliente(
            nome=nome,
            cpf_cnpj=cpf_cnpj,
            endereco=endereco,
            codigo_unidade=codigo_unidade,
            usina_id=usina_id,
            email=email,
            telefone=telefone
        )
        db.session.add(cliente)
        db.session.commit()
        return redirect(url_for('cadastrar_cliente'))

    usina_id_filtro = request.args.get('usina_id', type=int)
    if usina_id_filtro:
        clientes = Cliente.query.filter_by(usina_id=usina_id_filtro).all()
    else:
        clientes = Cliente.query.all()

    return render_template(
        'clientes.html',
        clientes=clientes,
        usinas=usinas,
        usina_id_filtro=usina_id_filtro
    )

@app.route('/rateios', methods=['GET', 'POST'])
@login_required
def cadastrar_rateio():
    usinas = Usina.query.all()
    clientes = Cliente.query.all()

    if request.method == 'POST':
        usina_id = int(request.form['usina_id'])
        cliente_id = int(request.form['cliente_id'])
        percentual = float(request.form['percentual'])
        tarifa_kwh = float(request.form['tarifa_kwh'])

        # Buscar o maior codigo_rateio já usado para essa usina
        ultimo_codigo = db.session.query(
            db.func.max(Rateio.codigo_rateio)
        ).filter_by(usina_id=usina_id).scalar()

        proximo_codigo = 1 if ultimo_codigo is None else ultimo_codigo + 1

        rateio = Rateio(
            usina_id=usina_id,
            cliente_id=cliente_id,
            percentual=percentual,
            tarifa_kwh=tarifa_kwh,
            codigo_rateio=proximo_codigo  # Define o código sequencial
        )

        db.session.add(rateio)
        db.session.commit()
        return redirect(url_for('cadastrar_rateio'))

    rateios = Rateio.query.all()
    return render_template('rateios.html', rateios=rateios, usinas=usinas, clientes=clientes)

@app.route('/editar_rateio/<int:id>', methods=['GET', 'POST'])
def editar_rateio(id):
    rateio = Rateio.query.get_or_404(id)
    usinas = Usina.query.all()
    clientes = Cliente.query.all()

    if request.method == 'POST':
        rateio.usina_id = request.form['usina_id']
        rateio.cliente_id = request.form['cliente_id']
        rateio.percentual = float(request.form['percentual'])
        rateio.tarifa_kwh = float(request.form['tarifa_kwh'])
        db.session.commit()
        return redirect(url_for('cadastrar_rateio'))

    return render_template('editar_rateio.html', rateio=rateio, usinas=usinas, clientes=clientes)

@app.route('/excluir_rateio/<int:id>', methods=['POST'])
def excluir_rateio(id):
    rateio = Rateio.query.get_or_404(id)
    db.session.delete(rateio)
    db.session.commit()
    return redirect(url_for('cadastrar_rateio'))

@app.route('/editar_cliente/<int:id>', methods=['GET', 'POST'])
def editar_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    usinas = Usina.query.all()

    if request.method == 'POST':
        cliente.nome = request.form['nome']
        cliente.cpf_cnpj = request.form['cpf_cnpj']
        cliente.endereco = request.form['endereco']
        cliente.codigo_unidade = request.form['codigo_unidade']
        cliente.usina_id = request.form['usina_id']
        cliente.email = request.form['email']
        cliente.telefone = request.form['telefone']
        db.session.commit()
        return redirect(url_for('cadastrar_cliente'))

    return render_template('editar_cliente.html', cliente=cliente, usinas=usinas)

@app.route('/excluir_cliente/<int:id>')
def excluir_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    db.session.delete(cliente)
    db.session.commit()
    return redirect(url_for('cadastrar_cliente'))

@app.route('/faturamento', methods=['GET', 'POST'])
@login_required
def faturamento():
    if not current_user.pode_cadastrar_fatura:
        return "Acesso negado", 403

    usinas = Usina.query.all()
    clientes = Cliente.query.all()
    mensagem = ''

    def limpar_valor(valor):
        if not valor:
            return 0.0
        return float(
            valor.replace('R$', '')
                 .replace('%', '')
                 .replace('.', '')
                 .replace(',', '.')
                 .strip()
        )

    if request.method == 'POST':
        try:
            cliente_id = int(request.form.get('cliente_id', 0))
            usina_id = int(request.form.get('usina_id', 0))
            mes = int(request.form.get('mes', 0))
            ano = int(request.form.get('ano', 0))

            if not cliente_id or not usina_id:
                raise ValueError("Cliente e Usina são obrigatórios")

            cliente = Cliente.query.get(cliente_id)
            rateio = cliente.rateios[0] if cliente and cliente.rateios else None
            codigo_rateio = rateio.codigo_rateio if rateio else "SEM"

            inicio_leitura = datetime.strptime(request.form['inicio_leitura'], '%Y-%m-%d').date()
            fim_leitura = datetime.strptime(request.form['fim_leitura'], '%Y-%m-%d').date()

            tarifa_neoenergia = limpar_valor(request.form['tarifa_neoenergia'])
            icms = limpar_valor(request.form['icms'])
            consumo_total = limpar_valor(request.form['consumo_total'])
            consumo_neoenergia = limpar_valor(request.form['consumo_neoenergia'])
            consumo_usina = limpar_valor(request.form['consumo_usina'])
            saldo_unidade = limpar_valor(request.form['saldo_unidade'])
            injetado = limpar_valor(request.form['injetado'])
            valor_conta_neoenergia = limpar_valor(request.form['valor_conta_neoenergia'])

            identificador = f"U{usina_id}: {codigo_rateio}-{mes:02d}-{ano}"
            existente = FaturaMensal.query.filter_by(identificador=identificador).first()

            if existente:
                mensagem = 'Já existe uma fatura para esse cliente neste mês.'
            else:
                fatura = FaturaMensal(
                    cliente_id=cliente_id,
                    mes_referencia=mes,
                    ano_referencia=ano,
                    inicio_leitura=inicio_leitura,
                    fim_leitura=fim_leitura,
                    tarifa_neoenergia=tarifa_neoenergia,
                    icms=icms,
                    consumo_total=consumo_total,
                    consumo_neoenergia=consumo_neoenergia,
                    consumo_usina=consumo_usina,
                    saldo_unidade=saldo_unidade,
                    injetado=injetado,
                    valor_conta_neoenergia=valor_conta_neoenergia,
                    identificador=identificador
                )
                db.session.add(fatura)
                db.session.commit()

                # Receita associada
                if rateio:
                    receita_valor = float(Decimal(consumo_usina * rateio.tarifa_kwh).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
                    receita = FinanceiroUsina(
                        usina_id=rateio.usina_id,
                        categoria_id=None, # pode adicionar a categoria
                        data=date.today(),
                        tipo='receita',
                        descricao=f"Fatura {fatura.identificador} - {cliente.nome}",
                        valor=receita_valor,
                        referencia_mes=mes,
                        referencia_ano=ano
                    )
                    db.session.add(receita)
                    db.session.commit()

                mensagem = 'Fatura cadastrada com sucesso.'

        except Exception as e:
            db.session.rollback()
            mensagem = f"Erro ao salvar fatura: {str(e)}"

    return render_template('faturamento.html', usinas=usinas, clientes=clientes, mensagem=mensagem)

@app.route('/clientes_por_usina/<int:usina_id>')
@login_required
def clientes_por_usina(usina_id):
    clientes = Cliente.query.filter_by(usina_id=usina_id).all()
    resultado = []

    for cliente in clientes:
        rateio = cliente.rateios[0] if cliente.rateios else None
        resultado.append({
            'id': cliente.id,
            'nome': cliente.nome,
            'codigo_rateio': rateio.codigo_rateio if rateio else ''
        })

    return jsonify(resultado)

@app.route('/faturas')
@login_required
def listar_faturas():
    usina_id = request.args.get('usina_id', type=int)
    mes = request.args.get('mes', type=int)
    ano = request.args.get('ano', type=int)
    cliente_id = request.args.get('cliente_id', type=int)

    query = FaturaMensal.query.join(Cliente).join(Usina)

    if usina_id:
        query = query.filter(Usina.id == usina_id)
    if cliente_id:
        query = query.filter(FaturaMensal.cliente_id == cliente_id)
    if mes:
        query = query.filter(FaturaMensal.mes_referencia == mes)
    if ano:
        query = query.filter(FaturaMensal.ano_referencia == ano)

    faturas = query.order_by(FaturaMensal.ano_referencia.desc(), FaturaMensal.mes_referencia.desc()).all()
    usinas = Usina.query.all()
    clientes = Cliente.query.all()
    anos = sorted({f.ano_referencia for f in FaturaMensal.query.all()}, reverse=True)

    return render_template('listar_faturas.html', faturas=faturas, usinas=usinas, clientes=clientes, anos=anos,
                           usina_id=usina_id, mes=mes, ano=ano)

@app.route('/editar_fatura/<int:id>', methods=['GET', 'POST'])
def editar_fatura(id):
    fatura = FaturaMensal.query.get_or_404(id)
    clientes = Cliente.query.all()
    usinas = Usina.query.all()

    if request.method == 'POST':
        fatura.mes_referencia = int(request.form['mes'])
        fatura.ano_referencia = int(request.form['ano'])
        fatura.inicio_leitura = datetime.strptime(request.form['inicio_leitura'], '%Y-%m-%d').date()
        fatura.fim_leitura = datetime.strptime(request.form['fim_leitura'], '%Y-%m-%d').date()
        fatura.tarifa_neoenergia = float(request.form['tarifa_neoenergia'].replace(',', '.'))
        fatura.icms = float(request.form['icms'].replace(',', '.'))
        fatura.consumo_total = float(request.form['consumo_total'].replace(',', '.'))
        fatura.consumo_neoenergia = float(request.form['consumo_neoenergia'].replace(',', '.'))
        fatura.consumo_usina = float(request.form['consumo_usina'].replace(',', '.'))
        fatura.saldo_unidade = float(request.form['saldo_unidade'].replace(',', '.'))
        fatura.injetado = float(request.form['injetado'].replace(',', '.'))
        fatura.valor_conta_neoenergia = float(request.form['valor_conta_neoenergia'].replace(',', '.'))
        db.session.commit()
        return redirect(url_for('listar_faturas'))

    return render_template('editar_fatura.html', fatura=fatura, clientes=clientes, usinas=usinas)

def render_template_relatorio(fatura_id):
    from decimal import Decimal

    fatura = FaturaMensal.query.get_or_404(fatura_id)
    cliente = Cliente.query.get(fatura.cliente_id)
    usina = Usina.query.get(cliente.usina_id)

    tarifa_base = Decimal(str(fatura.tarifa_neoenergia))
    if fatura.icms == 0:
        tarifa_neoenergia_aplicada = tarifa_base * Decimal('1.2625')
    elif fatura.icms == 20:
        tarifa_neoenergia_aplicada = tarifa_base
    else:
        tarifa_neoenergia_aplicada = tarifa_base * Decimal('1.1023232323')

    consumo_usina = Decimal(str(fatura.consumo_usina))
    valor_conta = Decimal(str(fatura.valor_conta_neoenergia))

    rateio = Rateio.query.filter_by(cliente_id=cliente.id, usina_id=usina.id).first()
    tarifa_cliente = Decimal(str(rateio.tarifa_kwh)) if rateio else Decimal('0')

    valor_usina = consumo_usina * tarifa_cliente
    com_desconto = valor_conta + valor_usina
    sem_desconto = consumo_usina * tarifa_neoenergia_aplicada + valor_conta
    economia = sem_desconto - com_desconto

    faturas_anteriores = FaturaMensal.query.filter(
        FaturaMensal.cliente_id == cliente.id,
        FaturaMensal.id != fatura.id,
        (FaturaMensal.ano_referencia < fatura.ano_referencia) |
        ((FaturaMensal.ano_referencia == fatura.ano_referencia) &
         (FaturaMensal.mes_referencia < fatura.mes_referencia))
    ).all()

    economia_total = Decimal('0')
    for f in faturas_anteriores:
        try:
            tarifa_base_ant = Decimal(str(f.tarifa_neoenergia))
            if f.icms == 0:
                tarifa_aplicada_ant = tarifa_base_ant * Decimal('1.2625')
            elif f.icms == 20:
                tarifa_aplicada_ant = tarifa_base_ant
            else:
                tarifa_aplicada_ant = tarifa_base_ant * Decimal('1.1023232323')

            consumo_usina_ant = Decimal(str(f.consumo_usina))
            valor_conta_ant = Decimal(str(f.valor_conta_neoenergia))

            valor_usina_ant = consumo_usina_ant * tarifa_cliente
            com_desconto_ant = valor_conta_ant + valor_usina_ant
            sem_desconto_ant = consumo_usina_ant * tarifa_aplicada_ant + valor_conta_ant

            economia_total += sem_desconto_ant - com_desconto_ant
        except:
            continue

    economia_acumulada = economia + economia_total

    # Caminhos fixos no Render
    pasta_boletos = '/data/boletos'
    pasta_logos = '/data/logos'

    pdf_path = os.path.join(pasta_boletos, f"boleto_{fatura.id}.pdf")
    ficha_compensacao_img = f"ficha_compensacao_{fatura.id}.png"
    ficha_path = os.path.join('static', ficha_compensacao_img)
    ficha_compensacao_img = extrair_ficha_compensacao(pdf_path, ficha_path) if os.path.exists(pdf_path) else None

    logo_cgr_path = "file:///static/img/logo_cgr.png"

    logo_usina_path = None
    if usina.logo_url:
        logo_usina_path = os.path.join(pasta_logos, usina.logo_url)
        if os.path.exists(logo_usina_path):
            logo_usina_path = f"file://{logo_usina_path}"

    ficha_compensacao_path = None
    if ficha_compensacao_img and os.path.exists(ficha_path):
        ficha_compensacao_path = f"file://{os.path.abspath(ficha_path)}"

    bootstrap_path = os.path.abspath("static/css/bootstrap.min.css").replace('\\', '/')
    bootstrap_path = f"file:///{bootstrap_path}"

    return render_template(
        'relatorio_fatura.html',
        fatura=fatura,
        cliente=cliente,
        usina=usina,
        tarifa_neoenergia_aplicada=tarifa_neoenergia_aplicada,
        tarifa_cliente=tarifa_cliente,
        valor_usina=valor_usina,
        com_desconto=com_desconto,
        sem_desconto=sem_desconto,
        economia=economia,
        economia_acumulada=economia_acumulada,
        ficha_compensacao_path=ficha_compensacao_path,
        logo_cgr_path=logo_cgr_path,
        logo_usina_path=logo_usina_path,
        bootstrap_path=bootstrap_path
    )

@app.route('/relatorio/<int:fatura_id>')
def relatorio_fatura(fatura_id):
    
    fatura = FaturaMensal.query.get_or_404(fatura_id)
    cliente = Cliente.query.get(fatura.cliente_id)
    usina = Usina.query.get(cliente.usina_id)

    # Cálculo da tarifa aplicada com ICMS
    tarifa_base = Decimal(str(fatura.tarifa_neoenergia))
    if fatura.icms == 0:
        tarifa_neoenergia_aplicada = tarifa_base * Decimal('1.2625')
    elif fatura.icms == 20:
        tarifa_neoenergia_aplicada = tarifa_base
    else:
        tarifa_neoenergia_aplicada = tarifa_base * Decimal('1.1023232323')

    consumo_usina = Decimal(str(fatura.consumo_usina))
    valor_conta = Decimal(str(fatura.valor_conta_neoenergia))

    # Tarifa do cliente
    rateio = Rateio.query.filter_by(cliente_id=cliente.id, usina_id=usina.id).first()
    tarifa_cliente = Decimal(str(rateio.tarifa_kwh)) if rateio else Decimal('0')

    # Cálculo de valores
    valor_usina = consumo_usina * tarifa_cliente
    com_desconto = valor_conta + valor_usina
    sem_desconto = consumo_usina * tarifa_neoenergia_aplicada + valor_conta
    economia = sem_desconto - com_desconto

    # Faturas anteriores para calcular economia acumulada
    faturas_anteriores = FaturaMensal.query.filter(
        FaturaMensal.cliente_id == cliente.id,
        FaturaMensal.id != fatura.id,
        (FaturaMensal.ano_referencia < fatura.ano_referencia) |
        ((FaturaMensal.ano_referencia == fatura.ano_referencia) &
         (FaturaMensal.mes_referencia < fatura.mes_referencia))
    ).all()

    economia_total = Decimal('0')
    for f in faturas_anteriores:
        try:
            tarifa_base_ant = Decimal(str(f.tarifa_neoenergia))
            if f.icms == 0:
                tarifa_aplicada_ant = tarifa_base_ant * Decimal('1.2625')
            elif f.icms == 20:
                tarifa_aplicada_ant = tarifa_base_ant
            else:
                tarifa_aplicada_ant = tarifa_base_ant * Decimal('1.1023232323')

            consumo_usina_ant = Decimal(str(f.consumo_usina))
            valor_conta_ant = Decimal(str(f.valor_conta_neoenergia))

            valor_usina_ant = consumo_usina_ant * tarifa_cliente
            com_desconto_ant = valor_conta_ant + valor_usina_ant
            sem_desconto_ant = consumo_usina_ant * tarifa_aplicada_ant + valor_conta_ant

            economia_total += sem_desconto_ant - com_desconto_ant
        except:
            continue

    economia_acumulada = economia + economia_total

    # Caminho da ficha de compensação
    pasta_boletos = os.getenv('BOLETOS_PATH', 'static/boletos')
    pdf_path = os.path.join(pasta_boletos, f"boleto_{fatura.id}.pdf")
    ficha_compensacao_img = f"ficha_compensacao_{fatura.id}.png"
    ficha_path = os.path.abspath(f"static/{ficha_compensacao_img}")
    ficha_compensacao_img = extrair_ficha_compensacao(pdf_path, ficha_path) if os.path.exists(pdf_path) else None

    # Caminhos absolutos para imagens e CSS (compatível com PDFKit)
    logo_cgr_path = os.path.abspath("static/img/logo_cgr.png").replace('\\', '/')
    logo_cgr_base64 = imagem_para_base64(logo_cgr_path)
    logo_cgr_data_uri = f"data:image/png;base64,{logo_cgr_base64}"

    logo_usina_data_uri = None
    if usina.logo_url:
        logo_usina_path = os.path.abspath(f"static/logos/{usina.logo_url}").replace('\\', '/')
        logo_usina_base64 = imagem_para_base64(logo_usina_path)
        logo_usina_data_uri = f"data:image/png;base64,{logo_usina_base64}"

    ficha_compensacao_data_uri = None
    if ficha_compensacao_img:
        ficha_abspath = os.path.abspath(f"static/{ficha_compensacao_img}").replace('\\', '/')
        if os.path.exists(ficha_abspath):
            ficha_base64 = imagem_para_base64(ficha_abspath)
            ficha_compensacao_data_uri = f"data:image/png;base64,{ficha_base64}"

    # Bootstrap
    bootstrap_path = os.path.abspath("static/css/bootstrap.min.css").replace('\\', '/')
    bootstrap_path = f"file:///{bootstrap_path}"

    return render_template(
        'relatorio_fatura.html',
        fatura=fatura,
        cliente=cliente,
        usina=usina,
        tarifa_neoenergia_aplicada=tarifa_neoenergia_aplicada,
        tarifa_cliente=tarifa_cliente,
        valor_usina=valor_usina,
        com_desconto=com_desconto,
        sem_desconto=sem_desconto,
        economia=economia,
        economia_acumulada=economia_acumulada,
        ficha_compensacao_path=ficha_compensacao_data_uri,
        logo_cgr_path=logo_cgr_data_uri,
        logo_usina_path=logo_usina_data_uri,
        bootstrap_path=bootstrap_path
    )
    
def extrair_ficha_compensacao(pdf_path, output_path='static/ficha_compensacao.png'):
    doc = fitz.open(pdf_path)
    page = doc.load_page(-1)  
    pix = page.get_pixmap(dpi=300)
    temp_img = "static/temp_page.png"
    pix.save(temp_img)

    imagem = Image.open(temp_img)
    largura, altura = imagem.size
    top = int(altura * 0.37)  
    bottom = int(altura * 0.75)
    ficha = imagem.crop((0, top, largura, bottom))
    ficha.save(output_path)
    return output_path

@app.route('/upload_boleto', methods=['GET', 'POST'])
@login_required
def upload_boleto():
    faturas = FaturaMensal.query.join(Cliente).order_by(
        FaturaMensal.ano_referencia.desc(),
        FaturaMensal.mes_referencia.desc()
    ).all()

    fatura_id_selecionada = request.args.get('fatura_id', type=int)
    mensagem = ''

    if request.method == 'POST':
        fatura_id = request.form.get('fatura_id')
        arquivo = request.files.get('boleto_pdf')

        if not fatura_id or not arquivo:
            mensagem = "Selecione uma fatura e envie um arquivo."
        elif not arquivo.filename.lower().endswith('.pdf'):
            mensagem = "O arquivo deve ser um PDF."
        else:
            pasta_boletos = os.getenv('BOLETOS_PATH', '/data/boletos')
            os.makedirs(pasta_boletos, exist_ok=True)

            nome_arquivo = f"boleto_{fatura_id}.pdf"
            caminho = os.path.join(pasta_boletos, nome_arquivo)
            arquivo.save(caminho)

            mensagem = f"Boleto da fatura {fatura_id} enviado com sucesso."

    return render_template(
        'upload_boleto.html',
        faturas=faturas,
        mensagem=mensagem,
        fatura_id_selecionada=fatura_id_selecionada
    )

@app.route('/excluir_fatura/<int:id>', methods=['POST'])
@login_required
def excluir_fatura(id):
    fatura = FaturaMensal.query.get_or_404(id)

    try:
        # Buscar a receita associada à fatura
        cliente = fatura.cliente
        rateio = cliente.rateios[0] if cliente.rateios else None
        if rateio:
            descricao_receita = f"Fatura {fatura.identificador} - {cliente.nome}"
            receita = FinanceiroUsina.query.filter_by(
                usina_id=rateio.usina_id,
                tipo='receita',
                referencia_mes=fatura.mes_referencia,
                referencia_ano=fatura.ano_referencia,
                descricao=descricao_receita
            ).first()
            if receita:
                db.session.delete(receita)

        # Excluir a fatura
        db.session.delete(fatura)
        db.session.commit()
        flash('Fatura e receita vinculada excluídas com sucesso.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir: {str(e)}', 'danger')

    return redirect(url_for('listar_faturas'))

@app.route('/extrair_dados_fatura', methods=['POST'])
@login_required
def extrair_dados_fatura():
    import re

    arquivo = request.files.get('arquivo')
    if not arquivo or not arquivo.filename.endswith('.pdf'):
        return jsonify({'erro': 'Arquivo inválido.'}), 400

    caminho_pdf = os.path.join('uploads', secure_filename(arquivo.filename))
    os.makedirs('uploads', exist_ok=True)
    arquivo.save(caminho_pdf)

    # Ler PDF
    doc = fitz.open(caminho_pdf)
    texto = "\n".join([pagina.get_text() for pagina in doc])
    linhas = texto.splitlines()
    doc.close()

    def encontrar_valor_com_rotulo(rotulo):
        for linha in linhas:
            if rotulo in linha:
                partes = linha.split(":")
                if len(partes) > 1:
                    return partes[-1].strip().replace('.', '').replace(',', '.')
        return None

    def buscar_datas():
        for i in range(len(linhas) - 1):
            d1 = linhas[i].strip()
            d2 = linhas[i + 1].strip()
            if re.match(r'\d{2}/\d{2}/\d{4}', d1) and re.match(r'\d{2}/\d{2}/\d{4}', d2):
                return d1, d2
        return '', ''

    def buscar_tarifa():
        match = re.search(r'KWh\s+\d+\s+([\d.,]+)', texto)
        return match.group(1).replace('.', '').replace(',', '.') if match else None

    def buscar_aliquota_icms():
        for linha in linhas:
            if "12,00" in linha or "12.00" in linha:
                return "12.00"
        return None

    def buscar_consumo_total():
        for i, linha in enumerate(linhas):
            if "ENERGIA ATIVA" in linha.upper() and i + 5 < len(linhas):
                valor = linhas[i + 5].strip()
                if re.match(r'^[\d.]+,\d{2}$', valor):
                    return valor.replace('.', '').replace(',', '.')
        return None

    def buscar_consumo_neoenergia():
        for i, linha in enumerate(linhas):
            if "CONSUMO" in linha.upper():
                for j in range(i + 1, min(i + 5, len(linhas))):
                    if linhas[j].strip() == "KWh" and j + 1 < len(linhas):
                        prox = linhas[j + 1].strip()
                        if re.match(r'^\d+$', prox):
                            return prox
        return None

    def buscar_valor_conta():
        for i, linha in enumerate(linhas):
            if "TOTAL A PAGAR" in linha.upper() and i >= 1:
                valor = linhas[i - 1].strip()
                if re.match(r'^[\d.]+,\d{2}$', valor):
                    return valor.replace('.', '').replace(',', '.')
        return None

    # Buscar dados
    inicio_leitura, fim_leitura = buscar_datas()

    dados = {
        'inicio_leitura': inicio_leitura,
        'fim_leitura': fim_leitura,
        'mes': fim_leitura.split('/')[1] if fim_leitura else '',
        'ano': fim_leitura.split('/')[2] if fim_leitura else '',
        'consumo_total': buscar_consumo_total(),
        'consumo_neoenergia': buscar_consumo_neoenergia(),
        'tarifa': buscar_tarifa(),
        'valor_conta': buscar_valor_conta(),
        'icms': buscar_aliquota_icms(),
        'injetado': encontrar_valor_com_rotulo("INJETADO") or "0",
        'consumo_usina': encontrar_valor_com_rotulo("COMPENSADO") or "0",
        'saldo_unidade': encontrar_valor_com_rotulo("SALDO ATUAL") or "0"
    }

    return jsonify(dados)

@app.route('/visualizar_pdf_temp/<nome_arquivo>')
def visualizar_pdf_temp(nome_arquivo):
    caminho = os.path.join('uploads', nome_arquivo)
    if os.path.exists(caminho):
        return send_file(caminho)
    return "Arquivo não encontrado", 404

@app.route('/salvar_pdf_temp', methods=['POST'])
def salvar_pdf_temp():
    arquivo = request.files.get('arquivo')
    if not arquivo or not arquivo.filename.endswith('.pdf'):
        return "Arquivo inválido", 400
    caminho = os.path.join('uploads', 'temp_preview.pdf')
    os.makedirs('uploads', exist_ok=True)
    arquivo.save(caminho)
    return "OK"

@app.route('/editar_previsoes/<int:usina_id>', methods=['GET', 'POST'])
def editar_previsoes(usina_id):
    usina = Usina.query.get_or_404(usina_id)
    ano = request.args.get('ano', date.today().year, type=int)

    if request.method == 'POST':
        # Atualiza potência da usina
        potencia = request.form.get('potencia_kw')
        if potencia:
            usina.potencia_kw = float(potencia.replace(',', '.'))

        # Atualiza previsões mensais
        for mes in range(1, 13):
            campo = f'previsoes[{mes}]'
            valor = request.form.get(campo)
            if valor:
                previsao = PrevisaoMensal.query.filter_by(usina_id=usina.id, ano=ano, mes=mes).first()
                if not previsao:
                    previsao = PrevisaoMensal(usina_id=usina.id, ano=ano, mes=mes)
                    db.session.add(previsao)
                previsao.previsao_kwh = float(valor.replace(',', '.'))

        # Upload da nova logo (se enviada)
        if 'logo' in request.files:
            logo = request.files['logo']
            if logo and logo.filename != '':
                filename = secure_filename(logo.filename)

                # Define o caminho com base no ambiente
                if os.getenv('FLASK_ENV') == 'production':
                    caminho_base = '/data/logos'
                else:
                    caminho_base = os.path.join('static', 'logos')

                os.makedirs(caminho_base, exist_ok=True)  # Garante que a pasta existe

                logo_path = os.path.join(caminho_base, filename)
                logo.save(logo_path)

                usina.logo_url = filename

        db.session.commit()
        return redirect(url_for('editar_previsoes', usina_id=usina.id, ano=ano))

    # Preenche os valores existentes no formulário
    previsoes = {
        p.mes: p.previsao_kwh
        for p in PrevisaoMensal.query.filter_by(usina_id=usina.id, ano=ano).all()
    }

    return render_template(
        'editar_previsoes.html',
        usina=usina,
        previsoes=previsoes,
        ano=ano,
        env=os.getenv('FLASK_ENV')  # para uso no template
    )

@app.route('/usinas')
def listar_usinas():
    usinas = Usina.query.all()
    return render_template('listar_usinas_previsao.html', usinas=usinas)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        senha = request.form['senha']
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario and usuario.verificar_senha(senha):
            login_user(usuario)
            return redirect(url_for('index'))
        else:
            return render_template('login.html', erro='Credenciais inválidas.')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/cadastrar_usuario', methods=['GET', 'POST'])
@login_required
def cadastrar_usuario():
    if current_user.email != 'master@admin.com':
        return "Acesso negado", 403
    
    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        senha = request.form['senha']
        pode_geracao = 'pode_cadastrar_geracao' in request.form
        pode_cliente = 'pode_cadastrar_cliente' in request.form
        pode_fatura = 'pode_cadastrar_fatura' in request.form
        pode_financeiro = 'pode_acessar_financeiro' in request.form

        novo_usuario = Usuario(
            nome=nome,
            email=email,
            pode_cadastrar_geracao=pode_geracao,
            pode_cadastrar_cliente=pode_cliente,
            pode_cadastrar_fatura=pode_fatura,
            pode_acessar_financeiro=pode_financeiro
        )
        novo_usuario.set_senha(senha)
        db.session.add(novo_usuario)
        db.session.commit()
        return redirect(url_for('cadastrar_usuario'))

    return render_template('cadastrar_usuario.html')

@app.route('/usuarios')
@login_required
def listar_usuarios():
    if current_user.email != 'master@admin.com':
        return "Acesso negado", 403
    usuarios = Usuario.query.all()
    return render_template('usuarios_admin.html', usuarios=usuarios)

@app.route('/editar_usuario/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_usuario(id):
    if current_user.email != 'master@admin.com':
        return "Acesso negado", 403

    usuario = Usuario.query.get_or_404(id)

    if request.method == 'POST':
        usuario.nome = request.form['nome']
        usuario.email = request.form['email']
        usuario.pode_cadastrar_geracao = 'pode_cadastrar_geracao' in request.form
        usuario.pode_cadastrar_cliente = 'pode_cadastrar_cliente' in request.form
        usuario.pode_cadastrar_fatura = 'pode_cadastrar_fatura' in request.form
        usuario.pode_acessar_financeiro = 'pode_acessar_financeiro' in request.form
        print(request.form)

        if request.form.get('senha'):
            usuario.set_senha(request.form['senha'])

        db.session.commit()
        return redirect(url_for('listar_usuarios'))

    return render_template('editar_usuario.html', usuario=usuario)

@app.route('/excluir_usuario/<int:id>', methods=['POST'])
@login_required
def excluir_usuario(id):
    if current_user.email != 'master@admin.com':
        return "Acesso negado", 403

    usuario = Usuario.query.get_or_404(id)
    db.session.delete(usuario)
    db.session.commit()
    return redirect(url_for('listar_usuarios'))

def montar_headers_solis(path: str, body_dict: dict) -> (dict, str):
    # 1) JSON “compacto”
    body_json = json.dumps(body_dict, separators=(",", ":"))
    body_bytes = body_json.encode("utf-8")

    # 2) MD5 em base64
    md5_digest = hashlib.md5(body_bytes).digest()
    content_md5 = base64.b64encode(md5_digest).decode()

    # 3) Date GMT
    date_str = formatdate(timeval=None, localtime=False, usegmt=True)

    # 4) Content-Type exato
    content_type = "application/json"

    # 5) Montagem da string canônica
    canonical_str = "\n".join([
        "POST",
        content_md5,
        content_type,
        date_str,
        path
    ])

    # 6) Cálculo do HMAC-SHA1 e Base64
    hmac_sha1 = hmac.new(
        SOLIS_KEY_SECRET.encode("utf-8"),
        canonical_str.encode("utf-8"),
        hashlib.sha1
    ).digest()
    signature_b64 = base64.b64encode(hmac_sha1).decode()

    # 7) Authorization
    authorization_header = f"API {SOLIS_KEY_ID}:{signature_b64}"

    # 8) Monta dicionário de headers
    headers = {
        "Content-MD5": content_md5,
        "Content-Type": content_type,
        "Date": date_str,
        "Authorization": authorization_header
    }
    return headers, body_json

def solis_listar_inversores():
    """
    Faz POST para /v1/api/inverterList com os headers corretos.
    Retorna lista de inverter_sn (strings) ou lança RuntimeError se status != 200.
    """
    path = "/v1/api/inverterList"
    endpoint = f"{SOLIS_BASE_URL}{path}"

    # inverterList costuma aceitar corpo vazio:
    body = {}
    headers, body_json = montar_headers_solis(path, body)

    resp = requests.post(endpoint, headers=headers, data=body_json, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"[Solis] Erro {resp.status_code} ao listar inversores: {resp.text}")

    dados = resp.json()
    
    pagina = dados.get("data", {}).get("page", {})
    registros = pagina.get("records", []) or []
    
    return [item.get("sn") for item in registros if item.get("sn")]

def solis_obter_dados_dia(inverter_sn, dia_str):
    """
    Faz POST para /v1/api/inverterDay e retorna o JSON de geração diária.
    Parâmetros:
      - inverter_sn: string do número de série do inversor
      - dia_str: data no formato "YYYY-MM-DD"
    Retorna: dict (resp.json()), ou lança RuntimeError em caso de erro HTTP.
    """
    path = "/v1/api/inverterDay"
    endpoint = f"{SOLIS_BASE_URL}{path}"

    body = {
        "inverter_sn": inverter_sn,
        "day": dia_str
    }
    headers, body_json = montar_headers_solis(path, body)

    resp = requests.post(endpoint, headers=headers, data=body_json, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"[Solis] Erro {resp.status_code} ao obter dados do dia: {resp.text}")
    return resp.json()

@app.route('/sync_solis/<string:dia>', methods=['GET'])
@login_required
def sync_solis(dia):
    try:
        data_obj = datetime.strptime(dia, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'erro': 'Formato de data inválido. Use YYYY-MM-DD.'}), 400

    inversores = Inversor.query.all()
    registros_inseridos = 0
    registros_pulos = 0
    erros = []

    for inv in inversores:
        try:
            resp_json = solis_obter_dados_dia(inv.inverter_sn, dia)
            lista_dados = resp_json.get("dataList") or resp_json.get("data") or []

            energia_kwh = float(lista_dados[-1].get("dayEnergy", 0.0)) if lista_dados else 0.0

            existente = Geracao.query.filter_by(usina_id=inv.usina_id, data=data_obj).first()
            if existente:
                registros_pulos += 1
                continue

            nova = Geracao(usina_id=inv.usina_id, data=data_obj, energia_kwh=energia_kwh)
            db.session.add(nova)
            registros_inseridos += 1
        except Exception as e:
            erros.append(f"{inv.inverter_sn}: {str(e)}")
            continue

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': f'Falha ao salvar: {str(e)}'}), 500

    return jsonify({
        'status': 'ok',
        'dia': dia,
        'inseridos': registros_inseridos,
        'pulados': registros_pulos,
        'total_inversores': len(inversores),
        'erros': erros
    })
    
@app.route('/portal_usinas')
@login_required
def portal_usinas():
    try:
        todos_records = listar_todos_inversores()
    except Exception as e:
        return render_template(
            'portal_usinas.html',
            usinas_info=[],
            detalhe_por_plant={},
            erro=f"Falha ao chamar API Solis: {str(e)}",
            hoje="",
            usinas=[]  
        ), 500

    # Agrupar inversores por planta
    detalhe_por_plant = {}
    for rec in todos_records:
        station_id = rec.get("stationId") or ""
        station_name = rec.get("stationName") or "Sem Nome"
        nome_plant = f"{station_id} - {station_name}"
        detalhe_por_plant.setdefault(nome_plant, []).append(rec)

    # Resumo por planta
    usinas_info = []
    for nome_plant, lista in detalhe_por_plant.items():
        total_inversores = len(lista)
        online_inversores = sum(1 for r in lista if r.get("state") == 1)
        rendimento_diario = sum(float(r.get("etoday", 0) or 0) for r in lista)
        rendimento_total = sum(float(r.get("etotal", 0) or 0) for r in lista)

        usinas_info.append({
            "nome": nome_plant,
            "total": total_inversores,
            "online": online_inversores,
            "rendimento_diario": rendimento_diario,
            "rendimento_total": rendimento_total
        })

    usinas_info.sort(key=lambda x: x["nome"])
    hoje = date.today().strftime("%Y-%m-%d")
    
    usinas = Usina.query.all()

    return render_template(
        'portal_usinas.html',
        usinas_info=usinas_info,
        detalhe_por_plant=detalhe_por_plant,
        erro=None,
        hoje=hoje,
        usinas=usinas  
    )
    
def listar_todos_inversores():
    path = "/v1/api/inverterList"
    todos = []
    pagina = 1
    MAX_PAGINAS = 5  # limite alto, mas seguro

    while pagina <= MAX_PAGINAS:
        body = {"currentPage": pagina, "pageSize": 100}
        headers, body_json = montar_headers_solis(path, body)

        try:
            resp = requests.post(f"{SOLIS_BASE_URL}{path}", headers=headers, data=body_json, timeout=10)
            resp.raise_for_status()
            dados = resp.json()
        except Exception as e:
            print(f"Erro na página {pagina}: {e}")
            break

        registros = dados.get("data", {}).get("page", {}).get("records", [])
        
        if not registros:
            break

        todos.extend(registros)
        pagina += 1

    # Remover duplicados por SN (caso a API esteja replicando)
    vistos = set()
    unicos = []
    for r in todos:
        sn = r.get("sn")
        if sn and sn not in vistos:
            vistos.add(sn)
            unicos.append(r)

    print(f"Total de inversores únicos: {len(unicos)}")
    return unicos

@app.route('/cadastrar_inversor', methods=['GET', 'POST'])
@login_required
def cadastrar_inversor():
    usinas = Usina.query.all()
    mensagem = ''

    if request.method == 'POST':
        inverter_sn = request.form['inverter_sn']
        usina_id = request.form['usina_id']

        if Inversor.query.filter_by(inverter_sn=inverter_sn).first():
            mensagem = "Este inversor já está cadastrado."
        else:
            novo = Inversor(inverter_sn=inverter_sn, usina_id=usina_id)
            db.session.add(novo)
            db.session.commit()
            mensagem = "Inversor vinculado com sucesso."

    return render_template('cadastrar_inversor.html', usinas=usinas, mensagem=mensagem)

@app.route('/vincular_inversores', methods=['GET', 'POST'])
@login_required
def vincular_inversores():
    try:
        # Lista todos os inversores da Solis
        registros = registros = listar_todos_inversores()  # função já existente no seu código
    except Exception as e:
        return render_template('vincular_inversores.html', erro=str(e), inversores=[], usinas=[])

    # Remove duplicados pelo serial (caso a API tenha registros repetidos)
    vistos = set()
    unicos = []
    for r in registros:
        sn = r.get("sn")
        if sn and sn not in vistos:
            unicos.append(r)
            vistos.add(sn)

    usinas = Usina.query.all()

    if request.method == 'POST':
        sn = request.form.get('inverter_sn')
        usina_id = request.form.get('usina_id')

        if sn and usina_id:
            # Verifica se já está vinculado
            existente = Inversor.query.filter_by(inverter_sn=sn).first()
            if not existente:
                novo = Inversor(inverter_sn=sn, usina_id=usina_id)
                db.session.add(novo)
                db.session.commit()
                flash(f"Inversor {sn} vinculado com sucesso!", "success")
            else:
                flash(f"Inversor {sn} já está vinculado.", "warning")

        return redirect(url_for('vincular_inversores'))

    return render_template('vincular_inversores.html', inversores=unicos, usinas=usinas)

@app.route('/vincular_estacoes', methods=['GET', 'POST'])
@login_required
def vincular_estacoes():
    try:
        registros = listar_todos_inversores()
    except Exception as e:
        return render_template('vincular_estacoes.html', erro=str(e), estacoes=[], usinas=[])

    # Agrupar inversores por estação válida (com stationId e stationName)
    detalhe_por_plant = {}
    for rec in registros:
        station_id = rec.get("stationId")
        station_name = rec.get("stationName")
        if not station_id or not station_name:
            continue
        nome_plant = f"{station_id} - {station_name}"
        detalhe_por_plant.setdefault(nome_plant, []).append(rec)

    usinas = Usina.query.all()

    if request.method == 'POST':
        nome_plant = request.form.get('nome_plant')
        usina_id = request.form.get('usina_id')

        if nome_plant and usina_id and nome_plant in detalhe_por_plant:
            inversores_da_estacao = detalhe_por_plant[nome_plant]
            novos = 0
            for rec in inversores_da_estacao:
                sn = rec.get("sn")
                if sn:
                    ja_existe = Inversor.query.filter_by(inverter_sn=sn).first()
                    if not ja_existe:
                        novo = Inversor(inverter_sn=sn, usina_id=usina_id)
                        db.session.add(novo)
                        novos += 1
            db.session.commit()
            flash(f"{novos} inversores da estação \"{nome_plant}\" foram vinculados com sucesso!", "success")
        else:
            flash("Estação ou usina inválida.", "danger")

        return redirect(url_for('vincular_estacoes'))

    
    return render_template(
        'vincular_estacoes.html',
        estacoes=sorted(detalhe_por_plant.keys()),  # <-- sem acento
        usinas=usinas
    )
    
@app.route('/atualizar_geracao')
@login_required
def atualizar_geracao():
    registros = listar_todos_inversores()
    hoje = date.today()

    # Dicionário para acumular por usina
    soma_por_usina = {}

    for r in registros:
        sn = r.get("sn")
        if not sn:
            continue

        etoday = float(r.get("etoday", 0) or 0)
        etotal = float(r.get("etotal", 0) or 0)

        # Atualiza/inclui na tabela geracoes_inversores (opcional)
        existente = GeracaoInversor.query.filter_by(inverter_sn=sn, data=hoje).first()
        if existente:
            existente.etoday = etoday
            existente.etotal = etotal
        else:
            nova = GeracaoInversor(
                data=hoje,
                inverter_sn=sn,
                etoday=etoday,
                etotal=etotal
            )
            inversor = Inversor.query.filter_by(inverter_sn=sn).first()
            if inversor:
                nova.usina_id = inversor.usina_id
                db.session.add(nova)
            else:
                continue  # não insere se não achar o inversor

        # Acumula total por usina
        inversor = Inversor.query.filter_by(inverter_sn=sn).first()
        if inversor and inversor.usina_id:
            soma_por_usina[inversor.usina_id] = soma_por_usina.get(inversor.usina_id, 0) + etoday

    # Atualiza ou insere na tabela GERACOES (por usina e dia)
    for usina_id, total_kwh in soma_por_usina.items():
        geracao = Geracao.query.filter_by(usina_id=usina_id, data=hoje).first()
        if geracao:
            geracao.energia_kwh = total_kwh
        else:
            nova_geracao = Geracao(
                usina_id=usina_id,
                data=hoje,
                energia_kwh=total_kwh
            )
            db.session.add(nova_geracao)

    db.session.commit()
    flash("Geração dos inversores e das usinas atualizada com sucesso.", "success")
    return redirect(url_for('portal_usinas'))

def listar_e_salvar_geracoes():
    registros = listar_todos_inversores()
    hoje = date.today()

    # Para salvar dados por inversor
    usina_kwh_por_dia = {}

    for r in registros:
        sn = r.get("sn")
        if not sn:
            continue

        etoday = float(r.get("etoday", 0) or 0)
        etotal = float(r.get("etotal", 0) or 0)

        # Salva leitura individual
        existente = GeracaoInversor.query.filter_by(inverter_sn=sn, data=hoje).first()
        inversor = Inversor.query.filter_by(inverter_sn=sn).first()
        if not inversor:
            continue

        # Atualiza/inclui leitura do inversor
        if existente:
            existente.etoday = etoday
            existente.etotal = etotal
        else:
            nova = GeracaoInversor(
                data=hoje,
                inverter_sn=sn,
                etoday=etoday,
                etotal=etotal,
                usina_id=inversor.usina_id
            )
            db.session.add(nova)

        # Acumula sempre (independente de já existir)
        usina_kwh_por_dia[inversor.usina_id] = usina_kwh_por_dia.get(inversor.usina_id, 0) + etoday

    # Agora salva o total por usina na tabela Geracao
    for usina_id, soma_etoday in usina_kwh_por_dia.items():
        leitura = Geracao.query.filter_by(usina_id=usina_id, data=hoje).first()
        if leitura:
            leitura.energia_kwh = soma_etoday
        else:
            nova_leitura = Geracao(
                data=hoje,
                usina_id=usina_id,
                energia_kwh=soma_etoday
            )
            db.session.add(nova_leitura)

    db.session.commit()

def atualizar_geracao_agendada():
    with app.app_context():
        try:
            print(f"[{datetime.now()}] Atualizando geração automaticamente...")
            listar_e_salvar_geracoes()
            print("Atualização concluída.")
        except Exception as e:
            print(f"Erro na atualização agendada: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(func=atualizar_geracao_agendada, trigger="interval", minutes=45)
scheduler.start()

# Garantir que pare quando o app for encerrado
atexit.register(lambda: scheduler.shutdown())

@app.route('/atualizar_periodo', methods=['GET', 'POST'])
def atualizar_periodo():
    usinas = Usina.query.all()

    if request.method == 'POST':
        usina_id = request.form.get('usina_id')
        data_inicio = request.form.get('data_inicio')
        data_fim = request.form.get('data_fim')

        if not usina_id or not data_inicio or not data_fim:
            flash("Todos os campos são obrigatórios.", "danger")
            return redirect(url_for('atualizar_periodo'))

        usina = Usina.query.get(int(usina_id))
        if not usina:
            flash("Usina não encontrada.", "danger")
            return redirect(url_for('atualizar_periodo'))

        data_atual = datetime.strptime(data_inicio, "%Y-%m-%d").date()
        data_final = datetime.strptime(data_fim, "%Y-%m-%d").date()

        while data_atual <= data_final:
            print(f"🔄 Atualizando {usina.nome} para {data_atual}")
            registros = listar_todos_inversores_por_data(data_atual)

            # soma por stationName e salva só se tiver valor
            soma_kwh = sum(
                float(inv.get("pac", 0) or 0)
                for inv in registros
                if inv.get("stationName") == usina.nome
            )

            if soma_kwh > 0:
                geracao_existente = Geracao.query.filter_by(usina_id=usina.id, data=data_atual).first()
                if geracao_existente:
                    geracao_existente.energia_kwh = soma_kwh
                else:
                    nova_geracao = Geracao(
                        usina_id=usina.id,
                        data=data_atual,
                        energia_kwh=soma_kwh
                    )
                    db.session.add(nova_geracao)

            data_atual += timedelta(days=1)

        db.session.commit()
        flash("Atualização concluída com sucesso!", "success")
        return redirect(url_for('atualizar_periodo'))

    return render_template('atualizar_periodo.html', usinas=usinas)


def listar_todos_inversores_por_data(data: date):
    """
    Consulta todos os inversores da Solis para uma data retroativa.
    """
    
    registros = []
    ids_ja_vistos = set()
    current_page = 1
    page_size = 100
    max_paginas = 50
    data_str = data.strftime("%Y-%m-%d")

    while current_page <= max_paginas:
        payload = {
            "currentPage": current_page,
            "pageSize": page_size,
            "day": data_str
        }

        headers, body_json = montar_headers_solis('/v1/api/inverterList', payload)

        try:
            response = requests.post(
                url="https://www.soliscloud.com:13333/v1/api/inverterList",
                headers=headers,
                data=body_json,
                timeout=20,
                verify=False
            )
            response.raise_for_status()

            print(f"🔍 Página {current_page} - Resposta da API ({data_str}):\n{response.text[:500]}")
            data_api = response.json()
            registros_pagina = data_api.get("data", {}).get("page", {}).get("records", [])

            if data_api.get("success") and registros_pagina:
                novos_registros = []

                for reg in registros_pagina:
                    reg_id = reg.get("id")
                    if reg_id in ids_ja_vistos:
                        continue  # apenas ignora duplicados

                    ids_ja_vistos.add(reg_id)
                    novos_registros.append(reg)

                registros.extend(novos_registros)

                if len(registros_pagina) < page_size:
                    print(f"✅ Última página atingida com {len(registros_pagina)} registros.")
                    break

                current_page += 1
            else:
                print(f"⚠️ Sem registros válidos em {data_str} (página {current_page}).")
                break

        except Exception as e:
            print(f"❌ Erro ao consultar a API ({data_str}): {e}")
            break

    else:
        print(f"🛑 Máximo de {max_paginas} páginas atingido. Parando busca.")

    return registros

@app.route('/logos/<nome_arquivo>')
def servir_logo(nome_arquivo):
    caminho_base = '/data/logos'
    return send_from_directory(caminho_base, nome_arquivo)

@app.route('/registrar_despesa', methods=['GET', 'POST'])
@login_required
def registrar_despesa():
    if not current_user.pode_acessar_financeiro:
        return "Acesso negado", 403

    usinas = Usina.query.all()
    clientes = Cliente.query.all()
    mensagem = ''

    usinas = Usina.query.all()
    categorias = CategoriaDespesa.query.order_by(CategoriaDespesa.nome).all()
    mensagem = None

    if request.method == 'POST':
        try:
            usina_id = int(request.form['usina_id'])
            categoria_id = int(request.form['categoria_id'])
            valor = float(request.form['valor'].replace(',', '.'))
            descricao = request.form['descricao']
            data = datetime.strptime(request.form['data'], '%Y-%m-%d').date()
            referencia_mes = int(request.form['referencia_mes'])
            referencia_ano = int(request.form['referencia_ano'])

            nova_despesa = FinanceiroUsina(
                usina_id=usina_id,
                categoria_id=categoria_id,
                tipo='despesa',
                valor=valor,
                descricao=descricao,
                data=data,
                referencia_mes=referencia_mes,
                referencia_ano=referencia_ano
            )

            db.session.add(nova_despesa)
            db.session.commit()
            mensagem = 'Despesa registrada com sucesso.'

        except Exception as e:
            db.session.rollback()
            mensagem = f'Erro ao registrar despesa: {str(e)}'

    return render_template('registrar_despesa.html', usinas=usinas, categorias=categorias, mensagem=mensagem)

@app.route('/financeiro')
@login_required
def financeiro():
    if not current_user.pode_acessar_financeiro:
        return "Acesso negado", 403

    usinas = Usina.query.all()
    clientes = Cliente.query.all()
    mensagem = ''

    # Filtros de mês, ano e usina
    mes = request.args.get('mes', default=date.today().month, type=int)
    ano = request.args.get('ano', default=date.today().year, type=int)
    usina_id = request.args.get('usina_id', type=int)

    # Base da query
    query = FinanceiroUsina.query.filter(
        FinanceiroUsina.referencia_mes == mes,
        FinanceiroUsina.referencia_ano == ano
    )

    if usina_id:
        query = query.filter(FinanceiroUsina.usina_id == usina_id)

    registros = query.order_by(FinanceiroUsina.data.desc()).all()

    # Monta lista para o template
    financeiro = []
    total_receitas = 0
    total_despesas = 0

    for r in registros:
        valor = r.valor or 0
        item = {
            'tipo': r.tipo,
            'usina': r.usina.nome if r.usina else 'N/A',
            'categoria': r.categoria.nome if r.categoria else '-',
            'descricao': r.descricao,
            'valor': valor,
            'data': r.data,
            'referencia': f"{r.referencia_mes:02d}/{r.referencia_ano}"
        }
        financeiro.append(item)

        if r.tipo == 'receita':
            total_receitas += valor
        else:
            total_despesas += valor

    usinas = Usina.query.order_by(Usina.nome).all()

    return render_template(
        'financeiro.html',
        financeiro=financeiro,
        mes=mes,
        ano=ano,
        usina_id=usina_id,
        usinas=usinas,
        total_receitas=total_receitas,
        total_despesas=total_despesas
    )

@app.route('/enviar_email/<int:fatura_id>')
def enviar_email(fatura_id):
    fatura = FaturaMensal.query.get_or_404(fatura_id)
    cliente = Cliente.query.get_or_404(fatura.cliente_id)
    
    link_relatorio = url_for('relatorio_fatura', fatura_id=fatura.id, _external=True)

    html = render_template('email_fatura.html', cliente=cliente, fatura=fatura, link_relatorio=link_relatorio)

    msg = Message(
        subject=f'Relatório de Fatura - {fatura.mes_referencia}/{fatura.ano_referencia}',
        recipients=[cliente.email],
        html=html
    )

    try:
        mail.send(msg)
        flash('E-mail enviado com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao enviar e-mail: {e}', 'danger')

    return redirect(url_for('listar_faturas'))

@app.route('/gerar_pdf/<int:fatura_id>')
def gerar_pdf_fatura(fatura_id):
    fatura = FaturaMensal.query.get_or_404(fatura_id)
    cliente = Cliente.query.get(fatura.cliente_id)
    usina = Usina.query.get(cliente.usina_id)

    tarifa_base = Decimal(str(fatura.tarifa_neoenergia))
    if fatura.icms == 0:
        tarifa_neoenergia_aplicada = tarifa_base * Decimal('1.2625')
    elif fatura.icms == 20:
        tarifa_neoenergia_aplicada = tarifa_base
    else:
        tarifa_neoenergia_aplicada = tarifa_base * Decimal('1.1023232323')

    consumo_usina = Decimal(str(fatura.consumo_usina))
    valor_conta = Decimal(str(fatura.valor_conta_neoenergia))
    rateio = Rateio.query.filter_by(cliente_id=cliente.id, usina_id=usina.id).first()
    tarifa_cliente = Decimal(str(rateio.tarifa_kwh)) if rateio else Decimal('0')

    valor_usina = consumo_usina * tarifa_cliente
    com_desconto = valor_conta + valor_usina
    sem_desconto = consumo_usina * tarifa_neoenergia_aplicada + valor_conta
    economia = sem_desconto - com_desconto

    faturas_anteriores = FaturaMensal.query.filter(
        FaturaMensal.cliente_id == cliente.id,
        FaturaMensal.id != fatura.id,
        (FaturaMensal.ano_referencia < fatura.ano_referencia) |
        ((FaturaMensal.ano_referencia == fatura.ano_referencia) &
         (FaturaMensal.mes_referencia < fatura.mes_referencia))
    ).all()

    economia_total = Decimal('0')
    for f in faturas_anteriores:
        try:
            tarifa_base_ant = Decimal(str(f.tarifa_neoenergia))
            if f.icms == 0:
                tarifa_aplicada_ant = tarifa_base_ant * Decimal('1.2625')
            elif f.icms == 20:
                tarifa_aplicada_ant = tarifa_base_ant
            else:
                tarifa_aplicada_ant = tarifa_base_ant * Decimal('1.1023232323')

            consumo_usina_ant = Decimal(str(f.consumo_usina))
            valor_conta_ant = Decimal(str(f.valor_conta_neoenergia))

            valor_usina_ant = consumo_usina_ant * tarifa_cliente
            com_desconto_ant = valor_conta_ant + valor_usina_ant
            sem_desconto_ant = consumo_usina_ant * tarifa_aplicada_ant + valor_conta_ant

            economia_total += sem_desconto_ant - com_desconto_ant
        except:
            continue

    economia_acumulada = economia + economia_total

    # Caminhos com encoding e file://
    def to_file_url(path):
        abs_path = os.path.abspath(path).replace('\\', '/')
        return f"file:///{abs_path}"

    logo_cgr_path = to_file_url("static/img/logo_cgr.png")
    logo_usina_path = to_file_url(f"static/logos/{usina.logo_url}") if usina.logo_url else None

    ficha_compensacao_path = None
    pdf_path = os.path.join('static/boletos', f"boleto_{fatura.id}.pdf")
    ficha_img = f"ficha_compensacao_{fatura.id}.png"
    if os.path.exists(pdf_path):
        ficha_compensacao_path = to_file_url(f"static/{ficha_img}")

    bootstrap_path = to_file_url("static/css/bootstrap.min.css")

    html = render_template(
        'relatorio_fatura.html',
        fatura=fatura,
        cliente=cliente,
        usina=usina,
        tarifa_neoenergia_aplicada=tarifa_neoenergia_aplicada,
        tarifa_cliente=tarifa_cliente,
        valor_usina=valor_usina,
        com_desconto=com_desconto,
        sem_desconto=sem_desconto,
        economia=economia,
        economia_acumulada=economia_acumulada,
        ficha_compensacao_path=ficha_compensacao_path,
        logo_cgr_path=logo_cgr_path,
        logo_usina_path=logo_usina_path,
        bootstrap_path=bootstrap_path
    )

    # Configura PDFKit com wkhtmltopdf correto
    #config = pdfkit.configuration(wkhtmltopdf=r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe")

    options = {
        'enable-local-file-access': '',
        'quiet': '',
        'page-size': 'A4',
        'encoding': 'UTF-8'
    }
    print("LOGO CGR:", logo_cgr_path)
    print("LOGO USINA:", logo_usina_path)
    print("FICHA COMP:", ficha_compensacao_path)
    print("BOOTSTRAP:", bootstrap_path)

    #pdf = pdfkit.from_string(html, False, options=options, configuration=config)

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=fatura_{fatura_id}.pdf'
    return response

def imagem_para_base64(caminho):
    with open(caminho, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode("utf-8")
        

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
