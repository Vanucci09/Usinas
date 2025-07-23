from flask import Flask, render_template, request, redirect, url_for, jsonify, make_response, send_file, flash, send_from_directory
from datetime import date, datetime, timedelta
from calendar import monthrange
import os, uuid, calendar
import pandas as pd
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import Numeric, text, func, case, cast
from decimal import Decimal, ROUND_HALF_UP
import fitz, tempfile, glob, platform
from PIL import Image
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import time, hashlib, json, hmac, requests, base64, atexit, math
from email.utils import formatdate
from apscheduler.schedulers.background import BackgroundScheduler
from flask_mail import Mail, Message
from urllib.parse import quote
import base64, shutil, logging
from sqlalchemy.orm import joinedload
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from pathlib import Path
from markupsafe import Markup
from shutil import copyfile
import undetected_chromedriver as uc
from collections import defaultdict
from sqlalchemy import extract


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
app.config['MAIL_USERNAME'] = 'nuza@cgrenergia.com.br'
app.config['MAIL_PASSWORD'] = 'kwou zhvp iszj hqtz'
app.config['MAIL_DEFAULT_SENDER'] = 'nuza@cgrenergia.com.br'

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
    data_ligacao = db.Column(db.Date)
    valor_investido = db.Column(db.Numeric(precision=12, scale=2))
    kehua_station_id = db.Column(db.String, nullable=True, unique=True)
    
    rateios = db.relationship('Rateio', backref='usina', cascade="all, delete-orphan")
    geracoes = db.relationship('Geracao', backref='usina', cascade="all, delete-orphan")
    
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
    email_cc = db.Column(db.String, nullable=True)
    telefone = db.Column(db.String, nullable=True)
    mostrar_saldo = db.Column(db.Boolean, default=True)
    consumo_instantaneo = db.Column(db.Boolean, default=False)
    login_concessionaria = db.Column(db.String, nullable=True)
    senha_concessionaria = db.Column(db.String, nullable=True)
    dia_relatorio = db.Column(db.Integer)
    relatorio_automatico = db.Column(db.Boolean, default=False)

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
    
    data_inicio = db.Column(db.Date, nullable=False, default=date.today)
    ativo = db.Column(db.Boolean, default=True)
    
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
    email_enviado = db.Column(db.Boolean, default=False)
    energia_injetada_real = db.Column(db.Float, default=0.0)

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
    data_pagamento = db.Column(db.Date)
    juros = db.Column(Numeric(10, 2), default=0)

    usina = db.relationship('Usina', backref='financeiros')

class EconomiaExtra(db.Model):
    __tablename__ = 'economias_extra'
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, nullable=True)
    usina_id = db.Column(db.Integer, nullable=True)
    valor_extra = db.Column(db.Numeric(12, 2), nullable=False)
    observacao = db.Column(db.String, nullable=True)
    
class EmpresaInvestidora(db.Model):
    __tablename__ = 'empresas_investidoras'
    id = db.Column(db.Integer, primary_key=True)
    razao_social = db.Column(db.String(255), nullable=False)
    cnpj = db.Column(db.String(20), nullable=False)
    endereco = db.Column(db.String(255))
    responsavel = db.Column(db.String(100))
    telefone = db.Column(db.String(20))
    email = db.Column(db.String(120))

    usinas = db.relationship('UsinaInvestidora', backref='empresa', cascade="all, delete-orphan")
    acionistas = db.relationship('ParticipacaoAcionista', backref='empresa', cascade="all, delete-orphan")
    
class ParticipacaoAcionista(db.Model):
    __tablename__ = 'participacoes_acionistas'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas_investidoras.id'), nullable=False)
    acionista_id = db.Column(db.Integer, db.ForeignKey('acionistas.id'), nullable=False)
    percentual = db.Column(db.Float, nullable=False)  # Exemplo: 33.33 para 33,33%
    
class UsinaInvestidora(db.Model):
    __tablename__ = 'usinas_investidoras'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas_investidoras.id'), nullable=False)
    usina_id = db.Column(db.Integer, db.ForeignKey('usinas.id'), nullable=False)

    usina = db.relationship('Usina', backref='investimentos')
    
class Acionista(db.Model):
    __tablename__ = 'acionistas'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)
    cpf = db.Column(db.String(20), nullable=False, unique=True)
    telefone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    tipo = db.Column(db.String(2), nullable=False, default='PF')  # 'PF' ou 'PJ'
    representante_legal = db.Column(db.String(255), nullable=True)  # Só usado se for PJ

    participacoes = db.relationship('ParticipacaoAcionista', backref='acionista', cascade="all, delete-orphan")
    
class FinanceiroEmpresaInvestidora(db.Model):
    __tablename__ = 'financeiro_empresa_investidora'

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas_investidoras.id'), nullable=False)
    data = db.Column(db.Date, nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # 'receita' ou 'despesa'
    descricao = db.Column(db.String(255), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    periodicidade = db.Column(db.String(20))  # 'mensal' ou 'recorrente'
    mes_referencia = db.Column(db.Integer, nullable=True)
    ano_referencia = db.Column(db.Integer, nullable=True)

    empresa = db.relationship('EmpresaInvestidora', backref='financeiros')
    
class DistribuicaoMensal(db.Model):
    __tablename__ = 'distribuicoes_mensais'

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas_investidoras.id'), nullable=False)
    usina_id = db.Column(db.Integer, db.ForeignKey('usinas.id'), nullable=False)
    ano = db.Column(db.Integer, nullable=False)
    mes = db.Column(db.Integer, nullable=False)
    valor_total = db.Column(db.Float, nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    empresa = db.relationship('EmpresaInvestidora', backref='distribuicoes_mensais')
    usina = db.relationship('Usina', backref='distribuicoes_mensais')
    
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

from datetime import datetime

@app.route('/cadastrar_usina', methods=['GET', 'POST'])
@login_required
def cadastrar_usina():
    if request.method == 'POST':
        logo = request.files.get('logo')
        cc = request.form['cc']
        nome = request.form['nome']
        potencia = request.form['potencia']
        data_ligacao_str = request.form.get('data_ligacao')
        valor_investido_str = request.form.get('valor_investido')
        ano_atual = date.today().year

        # Conversão dos valores
        data_ligacao = datetime.strptime(data_ligacao_str, '%Y-%m-%d').date() if data_ligacao_str else None
        valor_investido = float(valor_investido_str.replace(',', '.')) if valor_investido_str else None

        nova_usina = Usina(
            cc=cc,
            nome=nome,
            potencia_kw=potencia,
            data_ligacao=data_ligacao,
            valor_investido=valor_investido
        )
        db.session.add(nova_usina)
        db.session.commit()

        # Salvar o logo se enviado
        if logo and logo.filename != '':
            filename = secure_filename(logo.filename)
            caminho_base = os.getenv('LOGOS_PATH', os.path.join('static', 'logos'))
            os.makedirs(caminho_base, exist_ok=True)
            caminho_logo = os.path.join(caminho_base, filename)
            logo.save(caminho_logo)

            nova_usina.logo_url = filename
            db.session.commit()

        # Salvar previsões mensais
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
    potencia_kw = usina.potencia_kw

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

    # --------------------------
    # Média Yield acumulado no ano (exceto mês atual)
    # --------------------------
    geracoes_diarias = db.session.query(
        Geracao.data,
        func.sum(Geracao.energia_kwh)
    ).filter(
        Geracao.usina_id == usina_id,
        extract('year', Geracao.data) == ano,
        extract('month', Geracao.data) < mes
    ).group_by(Geracao.data).all()

    dados_por_mes = defaultdict(list)
    for data, energia in geracoes_diarias:
        dados_por_mes[data.month].append(float(energia))

    yield_mensal = []
    for mes_ref, energias_diarias in dados_por_mes.items():
        dias_com_dados = len(energias_diarias)
        dias_no_mes = monthrange(ano, mes_ref)[1]
        soma_kwh = sum(energias_diarias)

        if potencia_kw and dias_com_dados > 0:
            y = (soma_kwh / potencia_kw) * (dias_no_mes / dias_com_dados)
            yield_mensal.append(y)

    media_yield_acumulado = round(sum(yield_mensal) / len(yield_mensal), 2) if yield_mensal else None

    # --------------------------
    # Yield do mesmo mês do ano anterior
    # --------------------------
    data_inicio_anterior = date(ano - 1, mes, 1)
    data_fim_anterior = date(ano - 1, mes % 12 + 1, 1) if mes < 12 else date(ano, 1, 1)

    resultados_ano_anterior = Geracao.query.filter(
        Geracao.usina_id == usina_id,
        Geracao.data >= data_inicio_anterior,
        Geracao.data < data_fim_anterior
    ).all()

    dias_com_dados_ant = len(resultados_ano_anterior)
    dias_mes_ant = monthrange(ano - 1, mes)[1]
    soma_ant = sum(r.energia_kwh for r in resultados_ano_anterior)

    if (
        potencia_kw and potencia_kw > 0 and
        dias_com_dados_ant > 0 and
        soma_ant > 0
    ):
        valor = (soma_ant / potencia_kw) * (dias_mes_ant / dias_com_dados_ant)
        yield_ano_anterior = round(valor, 2) if not math.isnan(valor) else None
    else:
        yield_ano_anterior = None

    # --------------------------

    usinas = Usina.query.all()

    return render_template(
        'producao_mensal.html',
        usina_nome=usina.nome,
        potencia_kw=potencia_kw,
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
        dias_no_mes=dias_mes,
        media_yield_acumulado=media_yield_acumulado,
        yield_ano_anterior=yield_ano_anterior
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

@app.route('/cadastrar_cliente', methods=['GET', 'POST'])
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
        email_cc = request.form.get('email_cc')
        mostrar_saldo = request.form.get('mostrar_saldo') == 'on'
        consumo_instantaneo = 'consumo_instantaneo' in request.form

        # Novos campos
        login_concessionaria = request.form.get('login_concessionaria')
        senha_concessionaria = request.form.get('senha_concessionaria')
        dia_relatorio = request.form.get('dia_relatorio', type=int)
        relatorio_automatico = request.form.get('relatorio_automatico') == 'on'

        cliente = Cliente(
            nome=nome,
            cpf_cnpj=cpf_cnpj,
            endereco=endereco,
            codigo_unidade=codigo_unidade,
            usina_id=usina_id,
            email=email,
            telefone=telefone,
            email_cc=email_cc,
            mostrar_saldo=mostrar_saldo,
            consumo_instantaneo=consumo_instantaneo,
            login_concessionaria=login_concessionaria,
            senha_concessionaria=senha_concessionaria,
            dia_relatorio=dia_relatorio,
            relatorio_automatico=relatorio_automatico
        )
        db.session.add(cliente)
        db.session.commit()
        return redirect(url_for('listar_clientes'))

    return render_template('cadastrar_cliente.html', usinas=usinas)

@app.route('/clientes')
@login_required
def listar_clientes():
    if not current_user.pode_cadastrar_cliente:
        return "Acesso negado", 403

    usina_id_filtro = request.args.get('usina_id', type=int)
    if usina_id_filtro:
        clientes = Cliente.query.filter_by(usina_id=usina_id_filtro).all()
    else:
        clientes = Cliente.query.all()

    usinas = Usina.query.all()

    return render_template(
        'listar_clientes.html',
        clientes=clientes,
        usinas=usinas,
        usina_id_filtro=usina_id_filtro
    )

@app.route('/cadastrar_rateio', methods=['GET', 'POST'])
@login_required
def cadastrar_rateio():
    usinas = Usina.query.all()

    if request.method == 'POST':
        usina_id = int(request.form['usina_id'])
        cliente_id = int(request.form['cliente_id'])
        percentual = float(request.form['percentual'])
        tarifa_kwh = float(request.form['tarifa_kwh'])

        ultimo_codigo = db.session.query(
            db.func.max(Rateio.codigo_rateio)
        ).filter_by(usina_id=usina_id).scalar()

        proximo_codigo = 1 if ultimo_codigo is None else ultimo_codigo + 1

        rateio = Rateio(
            usina_id=usina_id,
            cliente_id=cliente_id,
            percentual=percentual,
            tarifa_kwh=tarifa_kwh,
            codigo_rateio=proximo_codigo
        )

        db.session.add(rateio)
        db.session.commit()
        return redirect(url_for('cadastrar_rateio'))

    return render_template('cadastrar_rateio.html', usinas=usinas)

@app.route('/listar_rateios')
@login_required
def listar_rateios():
    usinas = Usina.query.all()
    usina_id_filtro = request.args.get('usina_id', type=int)

    if usina_id_filtro:
        rateios = Rateio.query.filter_by(usina_id=usina_id_filtro).all()
    else:
        rateios = Rateio.query.all()

    return render_template('listar_rateios.html', rateios=rateios, usinas=usinas, usina_id_filtro=usina_id_filtro)

@app.route('/editar_rateio/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_rateio(id):
    rateio_antigo = Rateio.query.get_or_404(id)
    usinas = Usina.query.all()
    clientes = Cliente.query.all()

    if request.method == 'POST':
        # Desativa o rateio antigo
        rateio_antigo.ativo = False

        # Cria um novo com os dados atualizados
        novo_rateio = Rateio(
            usina_id=request.form['usina_id'],
            cliente_id=request.form['cliente_id'],
            percentual=float(request.form['percentual']),
            tarifa_kwh=float(request.form['tarifa_kwh']),
            codigo_rateio=rateio_antigo.codigo_rateio,
            data_inicio=date.today(),
            ativo=True
        )
        db.session.add(novo_rateio)
        db.session.commit()

        return redirect(url_for('listar_rateios'))

    return render_template('editar_rateio.html', rateio=rateio_antigo, usinas=usinas, clientes=clientes)

@app.route('/excluir_rateio/<int:id>', methods=['POST'])
@login_required
def excluir_rateio(id):
    rateio = Rateio.query.get_or_404(id)
    db.session.delete(rateio)
    db.session.commit()
    return redirect(url_for('listar_rateios'))

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
        cliente.email_cc = request.form.get('email_cc')
        cliente.mostrar_saldo = request.form.get('mostrar_saldo') == 'on'
        cliente.consumo_instantaneo = 'consumo_instantaneo' in request.form

        # Novos campos
        cliente.login_concessionaria = request.form.get('login_concessionaria')
        cliente.senha_concessionaria = request.form.get('senha_concessionaria')
        cliente.dia_relatorio = request.form.get('dia_relatorio', type=int)
        cliente.relatorio_automatico = request.form.get('relatorio_automatico') == 'on'

        db.session.commit()
        return redirect(url_for('listar_clientes', usina_id=cliente.usina_id))

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
            energia_injetada_real = limpar_valor(request.form.get('energia_injetada_real', '0'))
            consumo_instantaneo = 0.0

            if cliente and cliente.consumo_instantaneo:
                from sqlalchemy import func
                consumo_instantaneo = db.session.query(func.sum(Geracao.energia_kwh)).filter(
                    Geracao.usina_id == usina_id,
                    Geracao.data >= inicio_leitura,
                    Geracao.data <= fim_leitura
                ).scalar() or 0.0

            injetado_total = consumo_usina + consumo_instantaneo - energia_injetada_real

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
                    consumo_usina=injetado_total if cliente and cliente.consumo_instantaneo else consumo_usina,
                    saldo_unidade=saldo_unidade,
                    injetado=injetado,
                    valor_conta_neoenergia=valor_conta_neoenergia,
                    identificador=identificador,
                    energia_injetada_real=energia_injetada_real
                )
                db.session.add(fatura)
                db.session.commit()

                # Receita associada
                if rateio:
                    # Calcula o mês subsequente
                    data_base = date(ano, mes, 1)
                    proximo_mes = (data_base + timedelta(days=32)).replace(day=1)
                    referencia_mes_receita = proximo_mes.month
                    referencia_ano_receita = proximo_mes.year

                    receita_valor = float(Decimal(consumo_usina * rateio.tarifa_kwh).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
                    receita = FinanceiroUsina(
                        usina_id=rateio.usina_id,
                        categoria_id=None,  # pode adicionar a categoria
                        data=date(referencia_ano_receita, referencia_mes_receita, 1),  # data como 1º dia do mês subsequente
                        tipo='receita',
                        descricao=f"Fatura {fatura.identificador} - {cliente.nome}",
                        valor=receita_valor,
                        referencia_mes=referencia_mes_receita,
                        referencia_ano=referencia_ano_receita
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
    email_enviado = request.args.get('email_enviado') == '1'
    usina_id = request.args.get('usina_id', type=int)
    mes = request.args.get('mes', type=int)
    ano = request.args.get('ano', type=int)
    cliente_id = request.args.get('cliente_id', type=int)
    com_boleto = request.args.get('com_boleto') 

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

    # Verifica se existe boleto PDF no sistema de arquivos
    import os
    BOLETOS_PATH = os.getenv('BOLETOS_PATH', '/data/boletos')

    for f in faturas:
        nome_arquivo = f"boleto_{f.id}.pdf"
        f.tem_boleto = os.path.exists(os.path.join(BOLETOS_PATH, nome_arquivo))

    # Filtro por existência do boleto (aplicado após carregar todos os objetos)
    if com_boleto == '1':
        faturas = [f for f in faturas if f.tem_boleto]
    elif com_boleto == '0':
        faturas = [f for f in faturas if not f.tem_boleto]

    # Dados auxiliares para os filtros
    usinas = Usina.query.all()
    clientes = Cliente.query.all()
    anos = sorted({f.ano_referencia for f in FaturaMensal.query.all()}, reverse=True)

    return render_template(
        'listar_faturas.html',
        faturas=faturas,
        usinas=usinas,
        clientes=clientes,
        anos=anos,
        usina_id=usina_id,
        mes=mes,
        ano=ano,
        cliente_id=cliente_id,
        com_boleto=com_boleto,
        email_enviado=email_enviado
    )

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

@app.route('/relatorio/<int:fatura_id>')
def relatorio_fatura(fatura_id):
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

    # Economia acumulada
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

    economia_extra_total = db.session.query(
        db.func.sum(EconomiaExtra.valor_extra)
    ).filter(EconomiaExtra.cliente_id == cliente.id).scalar() or Decimal('0')

    economia_acumulada = economia + economia_total + economia_extra_total

    # ✅ Cálculo da geração no período (somente para consumo instantâneo)
    geracao_periodo = None
    if cliente.consumo_instantaneo:
        geracao_periodo = db.session.query(db.func.sum(Geracao.energia_kwh)).filter(
            Geracao.usina_id == usina.id,
            Geracao.data >= fatura.inicio_leitura,
            Geracao.data <= fatura.fim_leitura
        ).scalar() or Decimal('0')
        geracao_periodo = round(geracao_periodo, 2)

    # Ficha de compensação
    pasta_boletos = '/data/boletos'
    pdf_path = os.path.join(pasta_boletos, f"boleto_{fatura.id}.pdf")
    ficha_compensacao_img = f"ficha_compensacao_{fatura.id}.png"
    ficha_path = os.path.join('static', ficha_compensacao_img)

    ficha_compensacao_data_uri = None
    if os.path.exists(pdf_path):
        ficha_compensacao_img = extrair_ficha_compensacao(pdf_path, ficha_path)
        if ficha_compensacao_img and os.path.exists(ficha_path):
            ficha_base64 = imagem_para_base64(ficha_path)
            ficha_compensacao_data_uri = f"data:image/png;base64,{ficha_base64}"

    # Logo CGR
    logo_cgr_path = os.path.abspath("static/img/logo_cgr.png").replace('\\', '/')
    logo_cgr_data_uri = f"data:image/png;base64,{imagem_para_base64(logo_cgr_path)}"

    # Logo da usina
    logo_usina_data_uri = None
    if usina.logo_url:
        logo_path = os.path.abspath(f"static/logos/{usina.logo_url}").replace('\\', '/')
        if os.path.exists(logo_path):
            logo_usina_data_uri = f"data:image/png;base64,{imagem_para_base64(logo_path)}"

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
        geracao_periodo=geracao_periodo,
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

    # Variáveis de filtro padrão
    usina_id = cliente_id = mes = ano = ''

    if fatura_id_selecionada:
        fatura_selecionada = FaturaMensal.query.get(fatura_id_selecionada)
        if fatura_selecionada:
            cliente = fatura_selecionada.cliente
            usina_id = cliente.usina_id
            cliente_id = ''
            mes = fatura_selecionada.mes_referencia
            ano = fatura_selecionada.ano_referencia

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

    anos = sorted({f.ano_referencia for f in faturas}, reverse=True)
    usinas = Usina.query.all()
    clientes = Cliente.query.all()

    return render_template(
        'upload_boleto.html',
        faturas=faturas,
        mensagem=mensagem,
        fatura_id_selecionada=fatura_id_selecionada,
        usina_id=usina_id,
        cliente_id=cliente_id,
        mes=mes,
        ano=ano,
        usinas=usinas,
        clientes=clientes,
        anos=anos
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
    
    print(linhas)
    def buscar_aliquota_icms():
        for i, linha in enumerate(linhas):
            if "ICMS" in linha.upper():
                candidatos = []
                inicio = max(0, i - 10)
                fim = i
                for j in range(inicio, fim):
                    candidato = linhas[j].strip()
                    if re.match(r'^\d{1,2}[.,]\d{2}$', candidato):
                        try:
                            valor_float = float(candidato.replace('.', '').replace(',', '.'))
                            if 0 <= valor_float <= 25:
                                candidatos.append((j, valor_float, candidato))
                        except ValueError:
                            continue                
                for pos, valor, original in reversed(candidatos):
                    if valor >= 10:  
                        return original.replace('.', '').replace(',', '.')                
                if candidatos:
                    return candidatos[-1][2].replace('.', '').replace(',', '.')
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

    def buscar_energia_injetada_real():
        for i, linha in enumerate(linhas):
            if "ENERGIA INJETADA" in linha.upper():
                if i + 5 < len(linhas):
                    linha_valor = linhas[i + 5].strip()
                    match = re.search(r'\d{1,3}(?:\.\d{3})*,\d{2}', linha_valor)
                    if match:
                        valor_str = match.group(0)
                        valor_float = float(valor_str.replace('.', '').replace(',', '.'))
                        return valor_float
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
        'saldo_unidade': encontrar_valor_com_rotulo("SALDO ATUAL") or "0",
        'energia_injetada_real': buscar_energia_injetada_real()
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
@login_required
def editar_previsoes(usina_id):
    usina = Usina.query.get_or_404(usina_id)
    ano = request.args.get('ano', date.today().year, type=int)

    if request.method == 'POST':
        try:
            # Dados gerais da usina
            usina.cc = request.form.get('cc')
            usina.nome = request.form.get('nome')

            potencia = request.form.get('potencia_kw')
            usina.potencia_kw = float(potencia.replace(',', '.')) if potencia else usina.potencia_kw

            data_ligacao_str = request.form.get('data_ligacao')
            if data_ligacao_str:
                usina.data_ligacao = datetime.strptime(data_ligacao_str, '%Y-%m-%d').date()

            valor_investido_str = request.form.get('valor_investido')
            if valor_investido_str:
                usina.valor_investido = float(valor_investido_str.replace(',', '.'))

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

            # Upload da nova logo
            logo = request.files.get('logo')
            if logo and logo.filename != '':
                filename = secure_filename(logo.filename)
                ext = os.path.splitext(filename)[1]
                unique_filename = f"{uuid.uuid4().hex}{ext}"

                caminho_base = os.getenv('LOGOS_PATH', os.path.join('static', 'logos'))
                os.makedirs(caminho_base, exist_ok=True)

                logo_path = os.path.join(caminho_base, unique_filename)
                logo.save(logo_path)

                usina.logo_url = unique_filename

            db.session.commit()
            flash('Usina atualizada com sucesso!', 'success')
            return redirect(url_for('editar_previsoes', usina_id=usina.id, ano=ano))

        except Exception as e:
            flash(f'Erro ao atualizar: {e}', 'danger')
            return redirect(request.url)

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
        env=os.getenv('FLASK_ENV')
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

def montar_headers_solis(path: str, body_dict: dict) -> tuple[dict, str]:
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
        registros = registros = listar_todos_inversores() 
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
        estacoes=sorted(detalhe_por_plant.keys()),  
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
    hoje = date.today()
    usina_kwh_por_dia = {}

    # -------------------
    # 🔆 PARTE SOLIS
    # -------------------
    registros = listar_todos_inversores()

    for r in registros:
        sn = r.get("sn")
        if not sn:
            continue

        etoday = float(r.get("etoday", 0) or 0)
        etotal = float(r.get("etotal", 0) or 0)

        inversor = Inversor.query.filter_by(inverter_sn=sn).first()
        if not inversor:
            continue

        # Salvar por inversor
        existente = GeracaoInversor.query.filter_by(inverter_sn=sn, data=hoje).first()
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

        usina_kwh_por_dia[inversor.usina_id] = usina_kwh_por_dia.get(inversor.usina_id, 0) + etoday

    # -------------------
    # ⚡ PARTE KEHUA
    # -------------------
    def login_kehua():
        url_login = "https://energy.kehua.com/necp/login/northboundLogin"
        login_data = {
            "username": "monitoramento@cgrenergia.com",
            "password": "12345678",
            "locale": "en"
        }
        response = requests.post(url_login, data=login_data)
        return response.headers.get("Authorization")

    token = login_kehua()
    if token:
        headers = {"Authorization": token, "Content-Type": "application/json"}
        usinas_kehua = Usina.query.filter(Usina.kehua_station_id.isnot(None)).all()

        for usina in usinas_kehua:
            station_id = usina.kehua_station_id
            try:
                resp = requests.post(
                    "https://energy.kehua.com/necp/north/getDeviceInfo",
                    headers=headers,
                    json={"stationId": station_id}
                )
                if resp.status_code != 200 or resp.json().get("code") != "0":
                    print(f"⚠️ Falha ao consultar {usina.nome} ({station_id})")
                    continue

                inversores = resp.json().get("data", [])
                total_etoday = 0.0

                for inv in inversores:
                    sn = inv.get("sn")
                    etoday = float(inv.get("etoday") or 0)
                    etotal = float(inv.get("etotal") or 0)
                    total_etoday += etoday

                    # Salvar geração por inversor
                    leitura_inv = GeracaoInversor.query.filter_by(inverter_sn=sn, data=hoje).first()
                    if leitura_inv:
                        leitura_inv.etoday = etoday
                        leitura_inv.etotal = etotal
                    else:
                        nova_leitura = GeracaoInversor(
                            data=hoje,
                            inverter_sn=sn,
                            etoday=etoday,
                            etotal=etotal,
                            usina_id=usina.id
                        )
                        db.session.add(nova_leitura)

                usina_kwh_por_dia[usina.id] = usina_kwh_por_dia.get(usina.id, 0) + total_etoday
                print(f"✅ Kehua: Geração de {usina.nome}: {total_etoday:.2f} kWh")

            except Exception as e:
                print(f"❌ Erro na estação {usina.nome}: {e}")
    else:
        print("❌ Token da Kehua não obtido.")

    # -------------------
    # 💾 Salvar total por usina
    # -------------------
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
    print("✅ Geração diária salva para todas as usinas.")

def atualizar_geracao_agendada():
    with app.app_context():
        try:
            print(f"[{datetime.now()}] Atualizando geração automaticamente...")
            listar_e_salvar_geracoes()         # Solis
            listar_e_salvar_geracoes_kehua()   # Kehua
            print("✅ Atualização concluída.")
        except Exception as e:
            print(f"❌ Erro na atualização agendada: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(func=atualizar_geracao_agendada, trigger="interval", minutes=30)
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
    categorias = CategoriaDespesa.query.order_by(CategoriaDespesa.nome).all()
    mensagem = None
    data_hoje = date.today().isoformat()

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

    return render_template('registrar_despesa.html', usinas=usinas, categorias=categorias, mensagem=mensagem, data_hoje=data_hoje)

@app.route('/financeiro')
@login_required
def financeiro():
    if not current_user.pode_acessar_financeiro:
        return "Acesso negado", 403

    usinas = Usina.query.order_by(Usina.nome).all()
    categorias = CategoriaDespesa.query.order_by(CategoriaDespesa.nome).all()

    mes = request.args.get('mes', default=date.today().month, type=int)
    ano = request.args.get('ano', default=date.today().year, type=int)
    usina_id = request.args.get('usina_id', type=int)
    tipo = request.args.get('tipo')  # 'receita' ou 'despesa'
    categoria_id = request.args.get('categoria_id', type=int)

    # Base da query
    query = FinanceiroUsina.query.filter(
        FinanceiroUsina.referencia_mes == mes,
        FinanceiroUsina.referencia_ano == ano
    )

    if usina_id:
        query = query.filter(FinanceiroUsina.usina_id == usina_id)

    if tipo in ['receita', 'despesa']:
        query = query.filter(FinanceiroUsina.tipo == tipo)

    if categoria_id:
        query = query.filter(FinanceiroUsina.categoria_id == categoria_id)

    registros = query.order_by(FinanceiroUsina.data.desc()).all()

    # Monta lista para o template
    financeiro = []
    total_receitas = 0
    total_despesas = 0

    for r in registros:
        valor = Decimal(str(r.valor or 0))
        juros = Decimal(str(r.juros or 0))
        item = {
            'id': r.id,
            'tipo': r.tipo,
            'usina': r.usina.nome if r.usina else 'N/A',
            'categoria': r.categoria.nome if r.categoria else '-',
            'descricao': r.descricao,
            'valor': valor,
            'juros': float(juros),
            'data': r.data,
            'referencia': f"{r.referencia_mes:02d}/{r.referencia_ano}",
            'data_pagamento': r.data_pagamento
        }
        financeiro.append(item)

        if r.tipo == 'receita':
            total_receitas += valor + juros
        else:
            total_despesas += valor

    return render_template(
        'financeiro.html',
        financeiro=financeiro,
        mes=mes,
        ano=ano,
        usina_id=usina_id,
        tipo=tipo,
        categorias=categorias,
        categoria_id=categoria_id,
        usinas=usinas,
        total_receitas=total_receitas,
        total_despesas=total_despesas
    )

@app.route('/enviar_email/<int:fatura_id>')
def enviar_email(fatura_id):
    fatura = FaturaMensal.query.get_or_404(fatura_id)
    cliente = Cliente.query.get_or_404(fatura.cliente_id)
    
    rateio = Rateio.query.filter_by(cliente_id=cliente.id, usina_id=cliente.usina_id).first()
    link_relatorio = url_for('relatorio_fatura', fatura_id=fatura.id, _external=True)

    html = render_template('email_fatura.html', cliente=cliente, fatura=fatura, rateio=rateio, link_relatorio=link_relatorio)

    recipients = [cliente.email]
    if cliente.email_cc:
        cc_emails = [email.strip() for email in cliente.email_cc.split(',') if email.strip()]
        recipients.extend(cc_emails)

    msg = Message(
        subject=f'Relatório de Fatura - {fatura.mes_referencia}/{fatura.ano_referencia}',
        recipients=recipients,
        html=html
    )

    try:
        mail.send(msg)
        fatura.email_enviado = True
        db.session.commit()
        flash('E-mail enviado com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao enviar e-mail: {e}', 'danger')

    return redirect(url_for(
        'listar_faturas',
        usina_id=request.args.get('usina_id'),
        cliente_id=request.args.get('cliente_id'),
        mes=request.args.get('mes'),
        ano=request.args.get('ano'),
        com_boleto=request.args.get('com_boleto'),
        email_enviado=1
    ))
    
def imagem_para_base64(caminho):
    with open(caminho, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode("utf-8")

@app.route('/atualizar_pagamento/<int:id>', methods=['POST'])
@login_required
def atualizar_pagamento(id):
    financeiro = FinanceiroUsina.query.get_or_404(id)
    data_str = request.form.get('data_pagamento')
    juros_str = request.form.get('juros')  # Novo campo

    try:
        # Se for uma despesa já paga, bloqueia alteração
        if financeiro.tipo == 'despesa' and financeiro.data_pagamento:
            flash('Despesa já paga! Alteração não permitida.', 'warning')
            return redirect(request.referrer or url_for('financeiro'))

        # Atualiza data de pagamento
        if data_str:
            financeiro.data_pagamento = datetime.strptime(data_str, '%Y-%m-%d').date()
        else:
            financeiro.data_pagamento = None

        # Atualiza juros se informados
        if juros_str:
            juros_normalizado = juros_str.replace(',', '.')
            financeiro.juros = Decimal(juros_normalizado)
        else:
            financeiro.juros = Decimal('0.00')

        db.session.commit()
        flash('Pagamento atualizado com sucesso!', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao atualizar pagamento: {e}', 'danger')

    return redirect(request.referrer or url_for('financeiro'))

@app.route('/editar_despesa/<int:despesa_id>', methods=['GET', 'POST'])
def editar_despesa(despesa_id):
    despesa = FinanceiroUsina.query.get_or_404(despesa_id)
    usinas = Usina.query.all()
    categorias = CategoriaDespesa.query.all()

    if request.method == 'POST':
        despesa.usina_id = request.form['usina_id']
        despesa.categoria_id = request.form['categoria_id']
        despesa.descricao = request.form['descricao']
        despesa.valor = float(request.form['valor'].replace(',', '.'))
        despesa.data = request.form['data']
        despesa.referencia_mes = int(request.form['referencia_mes'])
        despesa.referencia_ano = int(request.form['referencia_ano'])
        db.session.commit()
        return redirect(url_for('listar_despesas'))

    return render_template('editar_despesa.html', despesa=despesa, usinas=usinas, categorias=categorias)

@app.route('/listar_despesas', methods=['GET'])
def listar_despesas():
    # Dicionário {id: nome} para as usinas
    usinas = {u.id: u.nome for u in Usina.query.all()}
    
    # Dicionário {id: nome} para as categorias
    categorias = {c.id: c.nome for c in CategoriaDespesa.query.all()}

    # Filtros
    usina_id = request.args.get('usina_id', type=int)
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')

    query = FinanceiroUsina.query.filter_by(tipo='despesa')

    if usina_id:
        query = query.filter(FinanceiroUsina.usina_id == usina_id)

    if data_inicio and data_fim:
        query = query.filter(FinanceiroUsina.data.between(data_inicio, data_fim))

    despesas = query.order_by(FinanceiroUsina.data.desc()).all()

    usinas_lista = Usina.query.all()

    return render_template('listar_despesas.html',
                           despesas=despesas,
                           usinas=usinas,
                           usinas_lista=usinas_lista,
                           categorias=categorias,
                           usina_id=usina_id,
                           data_inicio=data_inicio,
                           data_fim=data_fim)

@app.route('/relatorio_financeiro', methods=['GET'])
@login_required
def relatorio_financeiro():
    if not current_user.pode_acessar_financeiro:
        return "Acesso negado", 403

    usinas = Usina.query.order_by(Usina.nome).all()

    # Filtros
    usina_id = request.args.get('usina_id', type=int)
    tipo = request.args.get('tipo')
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')

    query = FinanceiroUsina.query

    # Filtro por usina
    if usina_id:
        query = query.filter(FinanceiroUsina.usina_id == usina_id)

    # Filtro por tipo (receita/despesa)
    if tipo in ['receita', 'despesa']:
        query = query.filter(FinanceiroUsina.tipo == tipo)

    # Filtro por data
    if data_inicio:
        query = query.filter(FinanceiroUsina.data >= data_inicio)
    if data_fim:
        query = query.filter(FinanceiroUsina.data <= data_fim)

    registros = query.order_by(FinanceiroUsina.data.asc()).all()

    total_receitas = sum((r.valor or 0) + (r.juros or 0) for r in registros if r.tipo == 'receita')
    total_despesas = sum(r.valor or 0 for r in registros if r.tipo == 'despesa')
    saldo = total_receitas - total_despesas

    return render_template(
        'relatorio_financeiro.html',
        registros=registros,
        usinas=usinas,
        usina_id=usina_id,
        tipo=tipo,
        data_inicio=data_inicio,
        data_fim=data_fim,
        total_receitas=total_receitas,
        total_despesas=total_despesas,
        saldo=saldo
    )

@app.route('/relatorio_consolidado', methods=['GET'])
@login_required
def relatorio_consolidado():
    if not current_user.pode_acessar_financeiro:
        return "Acesso negado", 403

    mes = request.args.get('mes', default=date.today().month, type=int)
    ano = request.args.get('ano', default=date.today().year, type=int)

    usinas = Usina.query.order_by(Usina.nome).all()
    resultado = []

    for usina in usinas:
        # Somar apenas receitas com data_pagamento preenchida
        receitas = db.session.query(
            func.sum((FinanceiroUsina.valor + func.coalesce(FinanceiroUsina.juros, 0)))
        ).filter(
            FinanceiroUsina.usina_id == usina.id,
            FinanceiroUsina.tipo == 'receita',
            FinanceiroUsina.referencia_mes == mes,
            FinanceiroUsina.referencia_ano == ano,
            FinanceiroUsina.data_pagamento.isnot(None)
        ).scalar() or 0

        despesas = db.session.query(db.func.sum(FinanceiroUsina.valor)).filter(
            FinanceiroUsina.usina_id == usina.id,
            FinanceiroUsina.tipo == 'despesa',
            FinanceiroUsina.referencia_mes == mes,
            FinanceiroUsina.referencia_ano == ano
        ).scalar() or 0

        saldo = receitas - despesas

        resultado.append({
            'usina': usina.nome,
            'receitas': receitas,
            'despesas': despesas,
            'saldo': saldo
        })
    
    total_receitas = sum(r['receitas'] for r in resultado)
    total_despesas = sum(r['despesas'] for r in resultado)
    total_saldo = total_receitas - total_despesas

    return render_template(
        'relatorio_consolidado.html',
        resultado=resultado,
        mes=mes,
        ano=ano,
        total_receitas=total_receitas,
        total_despesas=total_despesas,
        total_saldo=total_saldo
    )

@app.route('/relatorio_categoria', methods=['GET'])
@login_required
def relatorio_categoria():
    if not current_user.pode_acessar_financeiro:
        return "Acesso negado", 403

    mes = request.args.get('mes', default=date.today().month, type=int)
    ano = request.args.get('ano', default=date.today().year, type=int)
    usina_id = request.args.get('usina_id', type=int)
    tipo = request.args.get('tipo')  # Pode ser receita, despesa ou None

    query = db.session.query(
        CategoriaDespesa.nome.label('categoria'),
        FinanceiroUsina.tipo,
        db.func.sum(FinanceiroUsina.valor).label('total')
    ).join(CategoriaDespesa, FinanceiroUsina.categoria_id == CategoriaDespesa.id)


    # Filtros básicos
    query = query.filter(
        FinanceiroUsina.referencia_mes == mes,
        FinanceiroUsina.referencia_ano == ano
    )

    if usina_id:
        query = query.filter(FinanceiroUsina.usina_id == usina_id)

    if tipo in ['receita', 'despesa']:
        query = query.filter(FinanceiroUsina.tipo == tipo)

    query = query.group_by(CategoriaDespesa.nome, FinanceiroUsina.tipo).order_by(CategoriaDespesa.nome)

    resultados = query.all()

    # Organizar o resultado para facilitar no template
    categorias = {}
    for r in resultados:
        if r.categoria not in categorias:
            categorias[r.categoria] = {'receita': 0, 'despesa': 0}
        categorias[r.categoria][r.tipo] = r.total

    return render_template(
        'relatorio_categoria.html',
        categorias=categorias,
        mes=mes,
        ano=ano,
        usina_id=usina_id,
        tipo=tipo,
        usinas=Usina.query.order_by(Usina.nome).all()
    )

@app.route('/relatorio_cliente', methods=['GET'])
@login_required
def relatorio_cliente():
    if not current_user.pode_acessar_financeiro:
        return "Acesso negado", 403

    mes = request.args.get('mes', default=date.today().month, type=int)
    ano = request.args.get('ano', default=date.today().year, type=int)
    usina_id = request.args.get('usina_id', type=int)

    query = db.session.query(
        Cliente.nome.label('cliente'),
        db.func.sum(FaturaMensal.consumo_usina).label('consumo_total'),
        db.func.sum(FaturaMensal.consumo_usina * Rateio.tarifa_kwh).label('faturamento_total')
    ).join(Cliente, FaturaMensal.cliente_id == Cliente.id
    ).join(Rateio, Rateio.cliente_id == Cliente.id
    ).join(Usina, Cliente.usina_id == Usina.id
    ).filter(
        FaturaMensal.mes_referencia == mes,
        FaturaMensal.ano_referencia == ano
    )

    if usina_id:
        query = query.filter(Cliente.usina_id == usina_id)

    query = query.group_by(Cliente.nome).order_by(Cliente.nome)

    resultados = query.all()

    return render_template(
        'relatorio_cliente.html',
        resultados=resultados,
        mes=mes,
        ano=ano,
        usina_id=usina_id,
        usinas=Usina.query.order_by(Usina.nome).all()
    )

@app.route('/relatorio_recebido_vs_previsto')
@login_required
def relatorio_recebido_vs_previsto():
    mes = request.args.get('mes', default=date.today().month, type=int)
    ano = request.args.get('ano', default=date.today().year, type=int)

    # Pega todas as faturas daquele mês/ano
    faturas = FaturaMensal.query.filter_by(mes_referencia=mes, ano_referencia=ano).all()

    dados = []

    for fatura in faturas:
        cliente = fatura.cliente
        usina = cliente.usina

        # Tarifa do rateio
        rateio = Rateio.query.filter_by(cliente_id=cliente.id, usina_id=usina.id).first()
        tarifa = rateio.tarifa_kwh if rateio else 0

        # Valor previsto (geração * tarifa)
        valor_previsto = fatura.consumo_usina * tarifa

        # Valor recebido (somatório das receitas pagas no financeiro)
        recebimentos = FinanceiroUsina.query.filter(
            FinanceiroUsina.usina_id == usina.id,
            FinanceiroUsina.tipo == 'receita',
            FinanceiroUsina.descricao.ilike(f"%{cliente.nome}%"),
            db.extract('month', FinanceiroUsina.data) == mes,
            db.extract('year', FinanceiroUsina.data) == ano,
            FinanceiroUsina.data_pagamento != None
        ).with_entities(db.func.sum(FinanceiroUsina.valor)).scalar() or 0

        dados.append({
            'cliente': cliente.nome,
            'usina': usina.nome,
            'consumo_kwh': fatura.consumo_usina,
            'tarifa': tarifa,
            'valor_previsto': valor_previsto,
            'valor_recebido': recebimentos,
            'diferenca': valor_previsto - recebimentos
        })

    return render_template('relatorio_recebido_vs_previsto.html', dados=dados, mes=mes, ano=ano)

@app.route('/relatorio_gestao_usina')
@login_required
def relatorio_gestao_usina():
    if not current_user.pode_acessar_financeiro:
        return "Acesso negado", 403

    from sqlalchemy import func

    # Filtros de mês e ano atual (selecionado pelo usuário)
    mes = request.args.get('mes', default=date.today().month, type=int)
    ano = request.args.get('ano', default=date.today().year, type=int)

    # Definir o mês/ano da geração (sempre o mês anterior)
    if mes == 1:
        mes_geracao = 12
        ano_geracao = ano - 1
    else:
        mes_geracao = mes - 1
        ano_geracao = ano

    usinas = Usina.query.all()
    dados = []

    for usina in usinas:
        # Total gerado no mês anterior
        geracao_total = db.session.query(func.sum(Geracao.energia_kwh)).filter(
            Geracao.usina_id == usina.id,
            func.extract('month', Geracao.data) == mes_geracao,
            func.extract('year', Geracao.data) == ano_geracao
        ).scalar() or 0

        # Receita prevista com base na geração
        receita_prevista = 0
        rateios = Rateio.query.filter_by(usina_id=usina.id).all()

        for rateio in rateios:
            percentual = rateio.percentual / 100
            tarifa = rateio.tarifa_kwh or 0
            receita_prevista += geracao_total * percentual * tarifa

        # Receita recebida no mês selecionado (receitas com data_pagamento preenchida)
        receita_recebida = db.session.query(func.sum(FinanceiroUsina.valor)).filter(
            FinanceiroUsina.usina_id == usina.id,
            FinanceiroUsina.tipo == 'receita',
            FinanceiroUsina.referencia_mes == mes,
            FinanceiroUsina.referencia_ano == ano,
            FinanceiroUsina.data_pagamento != None
        ).scalar() or 0

        dados.append({
            'usina': usina.nome,
            'geracao': geracao_total,
            'previsto': receita_prevista,
            'recebido': receita_recebida,
            'diferenca': receita_recebida - receita_prevista
        })

    return render_template('relatorio_gestao_usina.html', dados=dados, mes=mes, ano=ano, mes_geracao=mes_geracao, ano_geracao=ano_geracao)

@app.route('/cadastrar_empresa', methods=['GET', 'POST'])
@login_required
def cadastrar_empresa():
    if request.method == 'POST':
        razao_social = request.form['razao_social']
        cnpj = request.form['cnpj']
        endereco = request.form.get('endereco')
        responsavel = request.form.get('responsavel')
        telefone = request.form.get('telefone')
        email = request.form.get('email')

        nova_empresa = EmpresaInvestidora(
            razao_social=razao_social,
            cnpj=cnpj,
            endereco=endereco,
            responsavel=responsavel,
            telefone=telefone,
            email=email
        )
        db.session.add(nova_empresa)
        db.session.commit()

        flash('Empresa cadastrada com sucesso!', 'success')
        return redirect(url_for('cadastrar_empresa'))

    empresas = EmpresaInvestidora.query.all()
    return render_template('cadastrar_empresa.html', empresas=empresas)

@app.route('/cadastrar_acionista', methods=['GET', 'POST'])
@login_required
def cadastrar_acionista():
    empresas = EmpresaInvestidora.query.all()

    if request.method == 'POST':
        cpf = request.form['cpf']

        # Verifica se já existe o CPF no banco
        existente = Acionista.query.filter_by(cpf=cpf).first()
        if existente:
            flash(f'O CPF {cpf} já está cadastrado para o acionista: {existente.nome}.', 'danger')
            return redirect(url_for('cadastrar_acionista'))

        # Se não existe, prossegue com o cadastro
        nome = request.form['nome']
        telefone = request.form.get('telefone')
        email = request.form.get('email')
        tipo = request.form['tipo']
        representante_legal = request.form.get('representante_legal') if tipo == 'PJ' else None
        empresa_id = int(request.form['empresa_id'])
        percentual = float(request.form['percentual'])

        # Verifica total de percentual antes
        total_atual = db.session.query(db.func.sum(ParticipacaoAcionista.percentual)).filter_by(empresa_id=empresa_id).scalar() or 0
        if total_atual + percentual > 100:
            flash(f'O percentual total da empresa não pode ultrapassar 100%. Total atual: {total_atual:.2f}%.', 'danger')
            return redirect(url_for('cadastrar_acionista'))

        novo_acionista = Acionista(
            nome=nome,
            cpf=cpf,
            telefone=telefone,
            email=email,
            tipo=tipo,
            representante_legal=representante_legal
        )
        db.session.add(novo_acionista)
        db.session.commit()

        participacao = ParticipacaoAcionista(
            empresa_id=empresa_id,
            acionista_id=novo_acionista.id,
            percentual=percentual
        )
        db.session.add(participacao)
        db.session.commit()

        flash('Acionista cadastrado e vinculado à empresa!', 'success')
        return redirect(url_for('cadastrar_acionista'))

    return render_template('cadastrar_acionista.html', empresas=empresas)

@app.route('/vincular_empresa_usina', methods=['GET', 'POST'])
@login_required
def vincular_empresa_usina():
    empresas = EmpresaInvestidora.query.all()
    usinas = Usina.query.all()

    if request.method == 'POST':
        empresa_id = request.form['empresa_id']
        usina_id = request.form['usina_id']

        # Criando o vínculo
        vinculo = UsinaInvestidora(empresa_id=empresa_id, usina_id=usina_id)
        db.session.add(vinculo)
        db.session.commit()

        flash('Usina vinculada à empresa com sucesso!', 'success')
        return redirect(url_for('vincular_empresa_usina'))

    return render_template('vincular_empresa_usina.html', empresas=empresas, usinas=usinas)

@app.route('/excluir_vinculo/<int:empresa_id>/<int:usina_id>', methods=['POST'])
@login_required
def excluir_vinculo(empresa_id, usina_id):
    vinculo = UsinaInvestidora.query.filter_by(empresa_id=empresa_id, usina_id=usina_id).first_or_404()

    db.session.delete(vinculo)
    db.session.commit()

    flash('Vínculo removido com sucesso.', 'info')
    return redirect(url_for('vincular_empresa_usina'))

from flask import request, render_template, redirect, url_for, flash
from flask_login import login_required
from datetime import datetime
from decimal import Decimal

@app.route('/cadastrar_financeiro_empresa', methods=['GET', 'POST'])
@login_required
def cadastrar_financeiro_empresa():
    empresas = EmpresaInvestidora.query.all()

    if request.method == 'POST':
        empresa_id = int(request.form['empresa_id'])
        data = datetime.strptime(request.form['data'], '%Y-%m-%d').date()
        tipo = request.form['tipo']
        descricao = request.form['descricao']

        if tipo == 'imposto':
            valor = float(request.form['valor_percentual'])
            periodicidade = request.form.get('periodicidade')

            if periodicidade == 'mensal':
                mes_referencia = int(request.form.get('mes_referencia') or 0)
                ano_referencia = int(request.form.get('ano_referencia') or 0)

                # Verifica se já existe imposto mensal para o mesmo mês/ano
                imposto_mensal_existente = FinanceiroEmpresaInvestidora.query.filter_by(
                    empresa_id=empresa_id,
                    tipo='imposto',
                    periodicidade='mensal',
                    mes_referencia=mes_referencia,
                    ano_referencia=ano_referencia
                ).first()
                if imposto_mensal_existente:
                    flash('Já existe um imposto mensal para esse período.', 'danger')
                    return redirect(url_for('cadastrar_financeiro_empresa'))

            else:
                mes_referencia = None
                ano_referencia = None

                # Verifica se já existe imposto recorrente
                imposto_recorrente_existente = FinanceiroEmpresaInvestidora.query.filter_by(
                    empresa_id=empresa_id,
                    tipo='imposto',
                    periodicidade='recorrente'
                ).first()

                # Verifica se já existe mensal para o período atual
                imposto_mensal_no_periodo = FinanceiroEmpresaInvestidora.query.filter_by(
                    empresa_id=empresa_id,
                    tipo='imposto',
                    periodicidade='mensal',
                    mes_referencia=data.month,
                    ano_referencia=data.year
                ).first()

                if imposto_recorrente_existente:
                    flash('Já existe um imposto recorrente cadastrado para esta empresa.', 'danger')
                    return redirect(url_for('cadastrar_financeiro_empresa'))

                if imposto_mensal_no_periodo:
                    flash('Já existe um imposto mensal para o mesmo período. Priorize o mensal.', 'danger')
                    return redirect(url_for('cadastrar_financeiro_empresa'))

        else:
            valor = float(request.form['valor'])
            periodicidade = None
            mes_referencia = None
            ano_referencia = None

        novo_lancamento = FinanceiroEmpresaInvestidora(
            empresa_id=empresa_id,
            data=data,
            tipo=tipo,
            descricao=descricao,
            valor=valor,
            periodicidade=periodicidade,
            mes_referencia=mes_referencia,
            ano_referencia=ano_referencia
        )
        db.session.add(novo_lancamento)
        db.session.commit()

        flash('Lançamento financeiro salvo com sucesso!', 'success')
        return redirect(url_for('cadastrar_financeiro_empresa'))

    ultimos_lancamentos = (
        FinanceiroEmpresaInvestidora
        .query.order_by(FinanceiroEmpresaInvestidora.data.desc())
        .limit(20).all()
    )

    return render_template(
        'cadastrar_financeiro_empresa.html',
        empresas=empresas,
        ultimos_lancamentos=ultimos_lancamentos
    )

@app.route('/relatorio_financeiro_empresa', methods=['GET', 'POST'])
@login_required
def relatorio_financeiro_empresa():
    empresas = EmpresaInvestidora.query.all()
    resultados = []

    if request.method == 'POST':
        mes = int(request.form['mes'])
        ano = int(request.form['ano'])

        for empresa in empresas:
            # Usinas vinculadas à empresa
            usinas_ids = [vinculo.usina_id for vinculo in empresa.usinas]

            # Total de receitas das usinas
            receitas_usinas = db.session.query(db.func.coalesce(db.func.sum(FinanceiroUsina.valor), 0)).filter(
                FinanceiroUsina.usina_id.in_(usinas_ids),
                FinanceiroUsina.tipo == 'receita',
                FinanceiroUsina.referencia_mes == mes,
                FinanceiroUsina.referencia_ano == ano
            ).scalar()

            # Total de despesas das usinas
            despesas_usinas = db.session.query(db.func.coalesce(db.func.sum(FinanceiroUsina.valor), 0)).filter(
                FinanceiroUsina.usina_id.in_(usinas_ids),
                FinanceiroUsina.tipo == 'despesa',
                FinanceiroUsina.referencia_mes == mes,
                FinanceiroUsina.referencia_ano == ano
            ).scalar()

            # Despesas da empresa
            despesas_empresa = db.session.query(db.func.coalesce(db.func.sum(FinanceiroEmpresaInvestidora.valor), 0)).filter(
                FinanceiroEmpresaInvestidora.empresa_id == empresa.id,
                FinanceiroEmpresaInvestidora.tipo == 'despesa',
                db.extract('month', FinanceiroEmpresaInvestidora.data) == mes,
                db.extract('year', FinanceiroEmpresaInvestidora.data) == ano
            ).scalar()

            # Receitas diretas da empresa
            receitas_empresa = db.session.query(db.func.coalesce(db.func.sum(FinanceiroEmpresaInvestidora.valor), 0)).filter(
                FinanceiroEmpresaInvestidora.empresa_id == empresa.id,
                FinanceiroEmpresaInvestidora.tipo == 'receita',
                db.extract('month', FinanceiroEmpresaInvestidora.data) == mes,
                db.extract('year', FinanceiroEmpresaInvestidora.data) == ano
            ).scalar()

            lucro_liquido = receitas_usinas - despesas_usinas - despesas_empresa + receitas_empresa

            resultados.append({
                'empresa': empresa.razao_social,
                'receitas_usinas': receitas_usinas,
                'despesas_usinas': despesas_usinas,
                'despesas_empresa': despesas_empresa,
                'receitas_empresa': receitas_empresa,
                'lucro_liquido': lucro_liquido
            })

        return render_template('relatorio_financeiro_empresa.html', resultados=resultados, mes=mes, ano=ano, empresas=empresas)

    return render_template('relatorio_financeiro_empresa.html', resultados=None, empresas=empresas)

def calcular_distribuicao_lucro(empresa_id, mes, ano):
    empresa = EmpresaInvestidora.query.get_or_404(empresa_id)

    # Usinas vinculadas
    usinas_ids = [vinculo.usina_id for vinculo in empresa.usinas]

    # Receita das usinas
    receitas_usinas = db.session.query(db.func.coalesce(db.func.sum(FinanceiroUsina.valor), 0)).filter(
        FinanceiroUsina.usina_id.in_(usinas_ids),
        FinanceiroUsina.tipo == 'receita',
        FinanceiroUsina.referencia_mes == mes,
        FinanceiroUsina.referencia_ano == ano
    ).scalar()

    # Despesas das usinas
    despesas_usinas = db.session.query(db.func.coalesce(db.func.sum(FinanceiroUsina.valor), 0)).filter(
        FinanceiroUsina.usina_id.in_(usinas_ids),
        FinanceiroUsina.tipo == 'despesa',
        FinanceiroUsina.referencia_mes == mes,
        FinanceiroUsina.referencia_ano == ano
    ).scalar()

    # Despesas da própria empresa
    despesas_empresa = db.session.query(db.func.coalesce(db.func.sum(FinanceiroEmpresaInvestidora.valor), 0)).filter(
        FinanceiroEmpresaInvestidora.empresa_id == empresa.id,
        FinanceiroEmpresaInvestidora.tipo == 'despesa',
        db.extract('month', FinanceiroEmpresaInvestidora.data) == mes,
        db.extract('year', FinanceiroEmpresaInvestidora.data) == ano
    ).scalar()

    # Receitas diretas da empresa
    receitas_empresa = db.session.query(db.func.coalesce(db.func.sum(FinanceiroEmpresaInvestidora.valor), 0)).filter(
        FinanceiroEmpresaInvestidora.empresa_id == empresa.id,
        FinanceiroEmpresaInvestidora.tipo == 'receita',
        db.extract('month', FinanceiroEmpresaInvestidora.data) == mes,
        db.extract('year', FinanceiroEmpresaInvestidora.data) == ano
    ).scalar()

    lucro_liquido = receitas_usinas - despesas_usinas - despesas_empresa + receitas_empresa

    # Agora, distribuir entre acionistas
    distribuicoes = []
    for participacao in empresa.acionistas:
        valor_participante = lucro_liquido * (participacao.percentual / 100)
        distribuicoes.append({
            'acionista': participacao.acionista.nome,
            'percentual': participacao.percentual,
            'valor': round(valor_participante, 2)
        })

    return {
        'empresa': empresa.razao_social,
        'mes': mes,
        'ano': ano,
        'lucro_liquido': round(lucro_liquido, 2),
        'distribuicoes': distribuicoes
    }

@app.route('/distribuicao_lucro_empresa/<int:empresa_id>/<int:mes>/<int:ano>')
@login_required
def distribuicao_lucro_empresa(empresa_id, mes, ano):
    resultado = calcular_distribuicao_lucro(empresa_id, mes, ano)
    return render_template('distribuicao_lucro_empresa.html', resultado=resultado)

@app.route('/selecionar_distribuicao_lucro', methods=['GET', 'POST'])
@login_required
def selecionar_distribuicao_lucro():
    empresas = EmpresaInvestidora.query.all()
    anos_disponiveis = [2024, 2025, 2026]  # Você pode montar dinamicamente depois se quiser.

    if request.method == 'POST':
        empresa_id = int(request.form['empresa_id'])
        mes = int(request.form['mes'])
        ano = int(request.form['ano'])

        return redirect(url_for('distribuicao_lucro_empresa', empresa_id=empresa_id, mes=mes, ano=ano))

    return render_template('selecionar_distribuicao_lucro.html', empresas=empresas, anos=anos_disponiveis)

@app.route('/empresas')
def listar_empresas():
    empresas = EmpresaInvestidora.query.order_by(EmpresaInvestidora.id.asc()).all()
    return render_template('listar_empresas.html', empresas=empresas)

@app.route('/editar_empresa/<int:empresa_id>', methods=['GET', 'POST'])
def editar_empresa(empresa_id):
    empresa = EmpresaInvestidora.query.get_or_404(empresa_id)

    if request.method == 'POST':
        empresa.razao_social = request.form['razao_social']
        empresa.cnpj = request.form['cnpj']
        empresa.endereco = request.form.get('endereco')
        empresa.responsavel = request.form.get('responsavel')
        empresa.telefone = request.form.get('telefone')
        empresa.email = request.form.get('email')

        db.session.commit()
        flash('Empresa atualizada com sucesso!', 'success')
        return redirect(url_for('listar_empresas'))

    return render_template('editar_empresa.html', empresa=empresa)

@app.route('/excluir_empresa/<int:empresa_id>')
def excluir_empresa(empresa_id):
    empresa = EmpresaInvestidora.query.get_or_404(empresa_id)
    db.session.delete(empresa)
    db.session.commit()
    flash('Empresa excluída com sucesso!', 'success')
    return redirect(url_for('listar_empresas'))

@app.route('/acionistas')
@login_required
def listar_acionistas():
    acionistas = Acionista.query.order_by(Acionista.id.asc()).all()
    return render_template('listar_acionistas.html', acionistas=acionistas)

@app.route('/excluir_acionista/<int:acionista_id>')
@login_required
def excluir_acionista(acionista_id):
    acionista = Acionista.query.get_or_404(acionista_id)

    # Excluir as participações vinculadas primeiro
    ParticipacaoAcionista.query.filter_by(acionista_id=acionista.id).delete()

    db.session.delete(acionista)
    db.session.commit()

    flash('Acionista excluído com sucesso!', 'success')
    return redirect(url_for('listar_acionistas'))

@app.route('/editar_acionista/<int:acionista_id>', methods=['GET', 'POST'])
@login_required
def editar_acionista(acionista_id):
    acionista = Acionista.query.get_or_404(acionista_id)

    if request.method == 'POST':
        acionista.nome = request.form['nome']
        acionista.cpf = request.form['cpf']
        acionista.telefone = request.form.get('telefone')
        acionista.email = request.form.get('email')
        acionista.tipo = request.form['tipo']
        acionista.representante_legal = request.form.get('representante_legal') if acionista.tipo == 'PJ' else None

        db.session.commit()
        flash('Acionista atualizado com sucesso!', 'success')
        return redirect(url_for('listar_acionistas'))

    return render_template('editar_acionista.html', acionista=acionista)

@app.route('/editar_participacao/<int:participacao_id>', methods=['GET', 'POST'])
@login_required
def editar_participacao(participacao_id):
    participacao = ParticipacaoAcionista.query.get_or_404(participacao_id)

    # Total de percentuais da empresa, excluindo o atual
    total_outros = db.session.query(db.func.sum(ParticipacaoAcionista.percentual)).filter(
        ParticipacaoAcionista.empresa_id == participacao.empresa_id,
        ParticipacaoAcionista.id != participacao.id
    ).scalar() or 0

    total_empresa = total_outros + participacao.percentual

    if request.method == 'POST':
        novo_percentual = float(request.form['percentual'])

        # Verifica se o novo total ultrapassa 100%
        if total_outros + novo_percentual > 100:
            flash(f'O total atual da empresa (sem considerar esta participação) é {total_outros:.2f}%. Se você salvar com {novo_percentual:.2f}%, vai ultrapassar 100%.', 'danger')
            return redirect(url_for('editar_participacao', participacao_id=participacao.id))

        # Salvar a alteração
        participacao.percentual = novo_percentual
        db.session.commit()
        flash('Percentual de participação atualizado com sucesso!', 'success')
        return redirect(url_for('listar_participacoes_empresa', empresa_id=participacao.empresa_id))

    return render_template(
        'editar_participacao.html',
        participacao=participacao,
        total_outros=total_outros,
        total_empresa=total_empresa
    )

@app.route('/participacoes_empresa/<int:empresa_id>')
@login_required
def listar_participacoes_empresa(empresa_id):
    empresa = EmpresaInvestidora.query.get_or_404(empresa_id)
    participacoes = ParticipacaoAcionista.query.filter_by(empresa_id=empresa.id).all()

    # Cálculo da soma total dos percentuais
    total_percentual = sum(p.percentual for p in participacoes)

    return render_template(
        'listar_participacoes_empresa.html',
        empresa=empresa,
        participacoes=participacoes,
        total_percentual=total_percentual
    )

@app.route('/vincular_acionista', methods=['GET', 'POST'])
@login_required
def vincular_acionista():
    acionistas = Acionista.query.all()
    empresas = EmpresaInvestidora.query.all()

    if request.method == 'POST':
        acionista_id = int(request.form['acionista_id'])
        empresa_id = int(request.form['empresa_id'])
        percentual = float(request.form['percentual'])

        # Verificar se já existe vínculo
        existe = ParticipacaoAcionista.query.filter_by(acionista_id=acionista_id, empresa_id=empresa_id).first()
        if existe:
            flash('Esse acionista já está vinculado a essa empresa. Edite o percentual se quiser.', 'warning')
            return redirect(url_for('vincular_acionista'))

        # Verificar limite de 100%
        total_atual = db.session.query(db.func.sum(ParticipacaoAcionista.percentual)).filter_by(empresa_id=empresa_id).scalar() or 0
        if total_atual + percentual > 100:
            flash(f'O percentual total da empresa não pode ultrapassar 100%. Total atual: {total_atual:.2f}%.', 'danger')
            return redirect(url_for('vincular_acionista'))

        nova_participacao = ParticipacaoAcionista(
            empresa_id=empresa_id,
            acionista_id=acionista_id,
            percentual=percentual
        )
        db.session.add(nova_participacao)
        db.session.commit()

        flash('Vínculo criado com sucesso!', 'success')
        return redirect(url_for('vincular_acionista'))

    # Prepara lista de participações por acionista
    participacoes_por_acionista = {}

    for a in acionistas:
        participacoes = ParticipacaoAcionista.query.filter_by(acionista_id=a.id).all()
        participacoes_por_acionista[a.id] = [
            {
                'empresa': EmpresaInvestidora.query.get(p.empresa_id).razao_social,
                'percentual': p.percentual
            } for p in participacoes
        ]

    return render_template(
        'vincular_acionista.html',
        acionistas=acionistas,
        empresas=empresas,
        participacoes_por_acionista=participacoes_por_acionista
    )

@app.route('/excluir_participacao/<int:participacao_id>', methods=['POST'])
@login_required
def excluir_participacao(participacao_id):
    participacao = ParticipacaoAcionista.query.get_or_404(participacao_id)
    empresa_id = participacao.empresa_id
    db.session.delete(participacao)
    db.session.commit()
    return redirect(url_for('listar_participacoes_empresa', empresa_id=empresa_id))

from flask import send_from_directory

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico')

@app.route('/relatorio_empresas_acionistas')
def relatorio_empresas_acionistas():
    empresas = EmpresaInvestidora.query.options(
        joinedload(EmpresaInvestidora.usinas).joinedload(UsinaInvestidora.usina),
        joinedload(EmpresaInvestidora.acionistas).joinedload(ParticipacaoAcionista.acionista)
    ).all()

    return render_template('relatorio_empresas_acionistas.html', empresas=empresas)

@app.route('/menu_relatorios')
def menu_relatorios():
    return render_template('menu_relatorios.html')

@app.route('/distribuicao_lucro', methods=['GET', 'POST'])
@login_required
def distribuicao_lucro_formulario():
    empresas = EmpresaInvestidora.query.all()
    anos = list(range(2022, date.today().year + 1))  # Exemplo

    if request.method == 'POST':
        empresa_id = int(request.form['empresa_id'])
        mes = int(request.form['mes'])
        ano = int(request.form['ano'])
        return redirect(url_for('distribuicao_lucro_empresa', empresa_id=empresa_id, mes=mes, ano=ano))

    return render_template('form_distribuicao_lucro.html', empresas=empresas, anos=anos)

@app.route('/editar_financeiro_empresa/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_financeiro_empresa(id):
    lancamento = FinanceiroEmpresaInvestidora.query.get_or_404(id)
    empresas = EmpresaInvestidora.query.all()

    if request.method == 'POST':
        lancamento.empresa_id = request.form['empresa_id']
        lancamento.data = datetime.strptime(request.form['data'], '%Y-%m-%d').date()
        lancamento.tipo = request.form['tipo']
        lancamento.descricao = request.form['descricao']

        if lancamento.tipo == 'imposto':
            lancamento.valor = float(request.form['valor_percentual'])
            lancamento.periodicidade = request.form.get('periodicidade')

            if lancamento.periodicidade == 'mensal':
                lancamento.mes_referencia = int(request.form.get('mes_referencia') or 0)
                lancamento.ano_referencia = int(request.form.get('ano_referencia') or 0)
            else:
                lancamento.mes_referencia = None
                lancamento.ano_referencia = None
        else:
            lancamento.valor = float(request.form['valor'])
            lancamento.periodicidade = None
            lancamento.mes_referencia = None
            lancamento.ano_referencia = None

        db.session.commit()
        flash('Lançamento atualizado com sucesso!', 'success')
        return redirect(url_for('cadastrar_financeiro_empresa'))

    return render_template('editar_financeiro_empresa.html', lancamento=lancamento, empresas=empresas)

@app.route('/relatorio_prestacao', methods=['GET'])
@login_required
def relatorio_prestacao():
    hoje = datetime.today()
    mes_atual = hoje.month
    ano_atual = hoje.year
    acionistas = Acionista.query.order_by(Acionista.nome).all()
    acionista_id = request.args.get('acionista_id', type=int)
    mes = request.args.get('mes', type=int) or mes_atual
    ano = request.args.get('ano', type=int) or ano_atual
    usina_id = request.args.get('usina_id', type=int)
    ano_atual = date.today().year

    usinas = []
    relatorio = None

    if acionista_id:
        participacoes = ParticipacaoAcionista.query.filter_by(acionista_id=acionista_id).all()
        empresas_ids = [p.empresa_id for p in participacoes]
        usinas_investidas = UsinaInvestidora.query.filter(UsinaInvestidora.empresa_id.in_(empresas_ids)).all()
        usinas = [ui.usina for ui in usinas_investidas]

    if acionista_id and usina_id:
        usina = Usina.query.get(usina_id)
        acionista = Acionista.query.get(acionista_id)

        if usina not in usinas:
            flash('A usina não está vinculada ao acionista selecionado.', 'danger')
            return redirect(url_for('relatorio_prestacao'))

        previsto = sum(
            p.previsao_kwh for p in usina.previsoes
            if (not mes or p.mes == mes) and (not ano or p.ano == ano)
        )

        realizado = sum(
            g.energia_kwh for g in usina.geracoes
            if (not mes or g.data.month == mes) and (not ano or g.data.year == ano)
        )

        eficiencia = round((realizado / previsto * 100), 2) if previsto else 0

        fluxo_consorcio = []
        receitas_usina = despesas_usina = 0
        for f in usina.financeiros:
            if (not mes or f.referencia_mes == mes) and (not ano or f.referencia_ano == ano):
                valor = f.valor or 0
                if f.tipo == 'receita':
                    receitas_usina += valor
                    fluxo_consorcio.append({'data': f.data, 'descricao': f.descricao, 'credito': valor, 'debito': ''})
                else:
                    despesas_usina += valor
                    fluxo_consorcio.append({'data': f.data, 'descricao': f.descricao, 'credito': '', 'debito': valor})

        empresa_investidora = EmpresaInvestidora.query \
            .join(UsinaInvestidora, UsinaInvestidora.empresa_id == EmpresaInvestidora.id) \
            .filter(UsinaInvestidora.usina_id == usina.id).first()

        fluxo_empresa = []
        receitas_empresa = despesas_empresa = 0
        if empresa_investidora:
            registros_financeiros = FinanceiroEmpresaInvestidora.query.filter_by(empresa_id=empresa_investidora.id).all()
            for f in registros_financeiros:
                if (not mes or f.data.month == mes) and (not ano or f.data.year == ano):
                    valor = f.valor or 0
                    if f.tipo == 'receita':
                        receitas_empresa += valor
                        fluxo_empresa.append({'data': f.data, 'descricao': f.descricao, 'credito': valor, 'debito': ''})
                    elif f.tipo == 'despesa':
                        despesas_empresa += valor
                        fluxo_empresa.append({'data': f.data, 'descricao': f.descricao, 'credito': '', 'debito': valor})

            total_liquido = receitas_usina - despesas_usina
            fluxo_empresa.append({
                'data': None,
                'descricao': 'Receita Líquida do Consórcio',
                'credito': total_liquido,
                'debito': ''
            })

            # Buscar imposto aplicável (mensal tem prioridade sobre recorrente)
            imposto_percentual = 0

            # Primeiro tenta encontrar imposto mensal para o período
            imposto_mensal = next((
                r for r in registros_financeiros
                if r.tipo == 'imposto' and r.periodicidade == 'mensal' and
                r.mes_referencia == mes and r.ano_referencia == ano
            ), None)

            if imposto_mensal:
                imposto_percentual = imposto_mensal.valor
            else:
                # Se não houver mensal, busca um recorrente
                imposto_recorrente = next((
                    r for r in registros_financeiros
                    if r.tipo == 'imposto' and r.periodicidade == 'recorrente'
                ), None)
                if imposto_recorrente:
                    imposto_percentual = imposto_recorrente.valor

            # Calcular imposto
            impostos = round(total_liquido * (imposto_percentual / 100), 2) if imposto_percentual else 0

            # Adicionar ao fluxo financeiro da empresa
            fluxo_empresa.append({
                'data': None,
                'descricao': f'Impostos sobre Receita Líquida ({imposto_percentual}%)',
                'credito': '',
                'debito': impostos
            })

            distribuicao_base = total_liquido - impostos - despesas_empresa

            distribuicao_existente = DistribuicaoMensal.query.filter_by(
                empresa_id=empresa_investidora.id,
                usina_id=usina.id,
                ano=ano,
                mes=mes
            ).first()

            if not distribuicao_existente:
                nova_distribuicao = DistribuicaoMensal(
                    empresa_id=empresa_investidora.id,
                    usina_id=usina.id,
                    ano=ano,
                    mes=mes,
                    valor_total=distribuicao_base
                )
                db.session.add(nova_distribuicao)
                db.session.commit()

            distribuicao = []
            for part in empresa_investidora.acionistas:
                if part.acionista_id == acionista.id:
                    percentual = part.percentual
                    valor = round(distribuicao_base * (percentual / 100), 2)
                    distribuicao.append({
                        'acionista': part.acionista.nome,
                        'percentual': percentual,
                        'valor': valor
                    })

            distrib_anteriores = DistribuicaoMensal.query.filter(
                DistribuicaoMensal.empresa_id == empresa_investidora.id,
                DistribuicaoMensal.usina_id == usina.id,
                (DistribuicaoMensal.ano < ano) |
                ((DistribuicaoMensal.ano == ano) & (DistribuicaoMensal.mes < mes))
            ).all()

            total_distribuido = round(sum(d.valor_total for d in distrib_anteriores) + distribuicao_base, 2)

            financeiros_anteriores = [
                f for f in usina.financeiros
                if f.referencia_ano < ano or (f.referencia_ano == ano and f.referencia_mes <= mes)
            ]
            receitas_anteriores = sum(f.valor for f in financeiros_anteriores if f.tipo == 'receita')
            despesas_anteriores = sum(f.valor for f in financeiros_anteriores if f.tipo == 'despesa')
            receita_liquida_total = receitas_anteriores - despesas_anteriores
            fundo_reserva_acumulado = round(receita_liquida_total * 0.05, 2)

            total_recebido_acionista = 0
            for d in distrib_anteriores:
                part = ParticipacaoAcionista.query.filter_by(
                    empresa_id=empresa_investidora.id,
                    acionista_id=acionista.id
                ).first()
                if part:
                    total_recebido_acionista += (d.valor_total * part.percentual / 100)

            if distribuicao:
                total_recebido_acionista += distribuicao[0]['valor']

            valor_investido_total = usina.valor_investido or 0
            participacao_acionista = ParticipacaoAcionista.query.filter_by(
                empresa_id=empresa_investidora.id,
                acionista_id=acionista.id
            ).first()

            percentual = participacao_acionista.percentual if participacao_acionista else 0
            valor_investido = float(valor_investido_total) * (percentual / 100)

            payback_alcancado = round((total_recebido_acionista / valor_investido) * 100, 2) if valor_investido else 0

            consolidacao = {
                'receita_bruta': round(receitas_usina, 2),
                'despesa_bruta': round(despesas_usina, 2),
                'receita_liquida': round(total_liquido, 2),
                'distribuicao_mensal': round(distribuicao_base, 2),
                'retorno_bruto': round(receitas_usina, 2),
                'impostos': impostos,
                'fundo_reserva': fundo_reserva_acumulado,
                'total_distribuido': total_distribuido,
                'payback_alcancado': payback_alcancado
            }

        dias_no_mes = calendar.monthrange(ano or date.today().year, mes or date.today().month)[1]
        dias_com_dados = len([
            g for g in usina.geracoes if g.data.month == mes and g.data.year == ano and g.energia_kwh > 0
        ])
        potencia_kw = usina.potencia_kw or 0
        soma_total = sum(
            g.energia_kwh for g in usina.geracoes if g.data.month == mes and g.data.year == ano
        )

        yield_kwp = round(soma_total / (dias_com_dados * (potencia_kw / dias_no_mes)), 2) if potencia_kw > 0 and dias_no_mes > 0 and dias_com_dados > 0 else None

        relatorio = {
            'usina': usina,
            'acionista': acionista,
            'previsto': previsto,
            'realizado': realizado,
            'eficiencia': eficiencia,
            'fluxo_consorcio': fluxo_consorcio,
            'fluxo_empresa': fluxo_empresa,
            'distribuicao': distribuicao,
            'consolidacao': consolidacao,
            'yield_kwp': yield_kwp
        }

    return render_template(
        'relatorio_prestacao_contas.html',
        acionistas=acionistas,
        acionista_id=acionista_id,
        usinas=usinas,
        usina_id=usina_id,
        relatorio=relatorio,
        mes=mes,
        ano=ano,
        ano_atual=ano_atual
    )

def listar_e_salvar_geracoes_kehua():
    def login_kehua():
        url_login = "https://energy.kehua.com/necp/login/northboundLogin"
        login_data = {
            "username": "monitoramento@cgrenergia.com",
            "password": "12345678",
            "locale": "en"
        }
        response = requests.post(url_login, data=login_data)
        if response.status_code == 200:
            json_resp = response.json()
            return json_resp.get("token") or response.headers.get("Authorization")
        return None

    hoje = date.today()
    token = login_kehua()

    if not token:
        print("❌ Token da Kehua não encontrado.")
        return

    headers = {
        "Authorization": token,
        "Content-Type": "application/x-www-form-urlencoded",
        "clienttype": "web"
    }

    usinas = Usina.query.filter(Usina.kehua_station_id.isnot(None)).all()

    for usina in usinas:
        soma_kwh = 0.0

        if usina.id == 9:  # ID da usina Bloco A Expansão
            payload = {
                "stationId": "31080",
                "companyId": "757",
                "areaCode": "903",
                "deviceId": "16872",  # ID numérico válido
                "deviceType": "00010001",
                "templateId": "1041"
            }

            try:
                resp = requests.post(
                    "https://energy.kehua.com/necp/monitor/getDeviceRealtimeData",
                    headers=headers,
                    data=payload
                )
                
                json_resp = resp.json()                

                if json_resp.get("code") != "0":
                    print(f"⚠️ Erro API Kehua: {json_resp.get('message')}")
                    continue

                yc_infos = json_resp.get("data", {}).get("ycInfos", [])
                kwh = 0.0
                for grupo in yc_infos:
                    data_points = grupo.get("dataPoint")
                    if isinstance(data_points, list):  
                        for ponto in data_points:
                            if ponto.get("property") == "dayElec":
                                kwh = float(ponto.get("val", 0))
                                break
                
                soma_kwh += kwh

            except Exception as e:
                print(f"❌ Erro ao consultar Bloco A Expansão: {e}")

        # Salvar geração
        if soma_kwh > 0:
            geracao = Geracao.query.filter_by(usina_id=usina.id, data=hoje).first()
            if geracao:
                geracao.energia_kwh = soma_kwh
            else:
                nova = Geracao(data=hoje, usina_id=usina.id, energia_kwh=soma_kwh)
                db.session.add(nova)

            db.session.commit()
            print(f"✅ Kehua: Geração salva para {usina.nome}: {soma_kwh:.2f} kWh")
        else:
            print(f"⚠️ Kehua: {usina.nome} retornou geração 0")

def buscar_estacoes_kehua():
    url_login = "https://energy.kehua.com/necp/login/northboundLogin"
    login_data = {
        "username": "monitoramento@cgrenergia.com",
        "password": "12345678",
        "locale": "en"
    }
    response = requests.post(url_login, data=login_data)
    token = response.headers.get("Authorization")    

    if not token:
        return []

    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }

    estacoes = []
    url_lista = "https://energy.kehua.com/necp/north/queryPowerStationInfoPage"
    body = {"pageSize": 10, "pageNumber": 1}
    resp_estacoes = requests.post(url_lista, headers=headers, json=body)    

    if resp_estacoes.status_code == 200:
        lista = resp_estacoes.json().get("data", {}).get("result", [])
        
        for est in lista:
            station_id = est.get("stationId")
            station_name = est.get("stationName")

            # Buscar inversores dessa estação
            url_inversores = "https://energy.kehua.com/necp/north/getDeviceInfo"
            resp_inv = requests.post(url_inversores, headers=headers, json={"stationId": station_id})
            inversores = []
            if resp_inv.status_code == 200:
                dados_inversores = resp_inv.json().get("data", [])                
                
                inversores = [
                    i.get("sn")
                    for i in dados_inversores
                    if i.get("stationId") == station_id
                ]

            estacoes.append({
                "station_id": station_id,
                "station_name": station_name,
                "inversores": inversores
            })

    return estacoes

@app.route('/vincular_kehua', methods=['GET', 'POST'])
@login_required
def vincular_kehua():    
    usinas = Usina.query.order_by(Usina.nome).all()
    estacoes = buscar_estacoes_kehua()

    if request.method == 'POST':
        usina_id = request.form.get('usina_id')
        station_id = request.form.get('station_id')
        inversores_sn = request.form.getlist('inversores')

        # Atualiza station_id na usina
        usina = Usina.query.get(usina_id)
        usina.kehua_station_id = station_id

        # Adiciona inversores
        for sn in inversores_sn:
            inversor_existente = Inversor.query.filter_by(inverter_sn=sn).first()
            if not inversor_existente:
                inversor = Inversor(inverter_sn=sn, usina_id=usina.id)
                db.session.add(inversor)
        db.session.commit()

        flash("Estação vinculada com sucesso!", "success")
        return redirect('/vincular_kehua')

    return render_template('vincular_kehua.html', usinas=usinas, estacoes=estacoes)

def baixar_fatura_neoenergia(cpf_cnpj, senha, codigo_unidade, mes_referencia, pasta_download, api_2captcha):    
    
    URL_LOGIN = "https://agenciavirtual.neoenergiabrasilia.com.br/Account/EfetuarLogin"
    SITEKEY = "6LdmOIAbAAAAANXdHAociZWz1gqR9Qvy3AN0rJy4"    

    # Detectar se está em produção (Render) ou local
    em_producao = os.getenv("RENDER", "0") == "1"
    print(f"[DEBUG] Ambiente: {'Render' if em_producao else 'Local'}")

    # Configuração do navegador
    options = Options()
    if em_producao:
        options.add_argument("--headless=new")
        options.binary_location = "/usr/bin/chromium"

    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    # Diretório de download resolvido corretamente
    download_path = Path(pasta_download).resolve()
    prefs = {
        "download.default_directory": str(download_path),
        "plugins.always_open_pdf_externally": True,
        "download.prompt_for_download": False
    }
    options.add_experimental_option("prefs", prefs)

    # Diretório de perfil exclusivo para evitar conflitos
    if em_producao:
        user_data_dir = tempfile.mkdtemp(prefix="selenium_user_data_")
        options.add_argument(f"--user-data-dir={user_data_dir}")
        driver = webdriver.Chrome(executable_path="/usr/bin/chromedriver", options=options)
    else:
        driver = webdriver.Chrome(options=options)

    try:
        print("🌐 Acessando página de login...")
        driver.get(URL_LOGIN)
        time.sleep(5)

        print("✍️ Preenchendo CPF e senha...")
        driver.find_element(By.CSS_SELECTOR, "input[placeholder='CPF/CNPJ']").send_keys(cpf_cnpj)
        driver.find_element(By.CSS_SELECTOR, "input[placeholder='Senha']").send_keys(senha)

        print("🎯 Enviando CAPTCHA para 2Captcha...")
        resp = requests.get(
            f"http://2captcha.com/in.php?key={api_2captcha}&method=userrecaptcha&googlekey={SITEKEY}&pageurl={URL_LOGIN}"
        )
        if not resp.text.startswith("OK|"):
            raise Exception(f"Erro ao enviar CAPTCHA: {resp.text}")
        request_id = resp.text.split('|')[1]

        print("⏳ Aguardando solução do CAPTCHA...")
        token = ""
        for _ in range(30):
            time.sleep(5)
            check = requests.get(f"http://2captcha.com/res.php?key={api_2captcha}&action=get&id={request_id}")
            if check.text.startswith("OK|"):
                token = check.text.split('|')[1]
                break

        if not token:
            raise Exception("❌ CAPTCHA não resolvido")

        print("✅ CAPTCHA resolvido!")
        driver.execute_script("document.getElementById('g-recaptcha-response').style.display = 'block';")
        driver.execute_script(f"document.getElementById('g-recaptcha-response').innerHTML = '{token}';")
        driver.execute_script("if (typeof recaptchaCallback === 'function') recaptchaCallback();")
        time.sleep(3)

        print("🚀 Clicando em entrar...")
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "a.btn")))

        print("🔍 Buscando unidade consumidora...")
        botoes = driver.find_elements(By.CSS_SELECTOR, "a.btn")
        for botao in botoes:
            texto = botao.text.strip().replace("-", "").replace(".", "")
            if codigo_unidade in texto:
                driver.execute_script("arguments[0].click();", botao)
                break
        else:
            raise Exception("Unidade consumidora não encontrada.")

        print("📄 Acessando histórico de consumo...")
        historico = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(@href, 'HistoricoConsumo')]"))
        )
        historico.click()

        print("🔍 Procurando fatura...")
        linhas_faturas = WebDriverWait(driver, 30).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "tr"))
        )

        for linha in linhas_faturas:
            if mes_referencia in linha.text:
                driver.execute_script("arguments[0].scrollIntoView();", linha)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", linha)
                time.sleep(2)

                link_element = linha.find_element(By.XPATH, ".//a[contains(@href, 'SegundaVia')]")
                driver.execute_script("arguments[0].click();", link_element)

                print("⏬ Aguardando download do PDF...")
                time.sleep(10)

                # Criar subpasta do CPF
                cpf_limpo = ''.join(filter(str.isdigit, cpf_cnpj))
                subpasta_cpf = download_path / cpf_limpo
                subpasta_cpf.mkdir(parents=True, exist_ok=True)

                # Pega o último PDF
                arquivos_pdf = list(Path(pasta_download).glob("*.pdf"))
                if not arquivos_pdf:
                    return False, "❌ Nenhum PDF encontrado após clique no link da fatura."

                ultimo_pdf = max(arquivos_pdf, key=lambda f: f.stat().st_mtime)

                # Novo nome + destino
                nome_arquivo = f"fatura_{cpf_limpo}_{codigo_unidade}_{mes_referencia.replace('/', '_')}.pdf"
                caminho_novo = subpasta_cpf / nome_arquivo
                # Se o destino já existir, exclui o antigo
                if caminho_novo.exists():
                    caminho_novo.unlink()

                # 🔄 Mover e renomear o arquivo
                ultimo_pdf.rename(caminho_novo)

                # Copia para static/faturas
                pasta_publica = Path("static/faturas")
                pasta_publica.mkdir(parents=True, exist_ok=True)
                caminho_exibicao = pasta_publica / nome_arquivo
                shutil.copy2(caminho_novo, caminho_exibicao)

                # Retorna a URL relativa para ser usada na view
                url_pdf = f"/static/faturas/{nome_arquivo}"
                print(f"✅ PDF disponível em: {url_pdf}")
                return True, url_pdf  # ✅ este é o único return necessário

        return False, "❌ Fatura do mês não encontrada."

    except Exception as e:
        print("❌ Erro:", e)
        return False, f"❌ Erro: {e}"

    finally:
        driver.quit()
        
@app.route('/baixar_fatura', methods=['GET', 'POST'])
def baixar_fatura():
    if request.method == 'POST':
        cpf = request.form['cpf']
        senha = request.form['senha']
        codigo = request.form['codigo_unidade']
        mes = request.form['mes_referencia']

        # 🔐 Chave da API 2Captcha
        captcha_key = "a8a517df68cc0cf9cf37d8e976d8be33"

        # 📁 Pasta base para salvar as faturas
        pasta_download = Path('data/boletos').resolve()
        pasta_download.mkdir(parents=True, exist_ok=True)

        # ⬇️ Executa a função de download
        sucesso, retorno = baixar_fatura_neoenergia(
            cpf_cnpj=cpf,
            senha=senha,
            codigo_unidade=codigo,
            mes_referencia=mes,
            pasta_download=str(pasta_download),
            api_2captcha=captcha_key
        )

        if sucesso:
            # Exibe link clicável na mensagem de sucesso
            link = request.host_url.rstrip('/') + retorno
            flash(Markup(f"✅ Fatura baixada com sucesso. <a href='{link}' target='_blank'>Clique aqui para abrir o PDF</a>"))
        else:
            flash(retorno)

        return redirect(url_for('baixar_fatura'))

    return render_template('form_baixar_fatura.html')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
