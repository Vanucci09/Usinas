from flask import Flask, render_template, request, redirect, url_for, jsonify, make_response, send_file, flash, send_from_directory, abort, current_app
from datetime import date, datetime, timedelta
import datetime as dt
from calendar import monthrange
import os, uuid, calendar, subprocess, threading
import pandas as pd
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import Numeric, text, func, case, cast, or_, and_, literal
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import fitz, tempfile, glob, platform
from PIL import Image
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import time, hashlib, json, hmac, requests, base64, atexit, math
from email.utils import formatdate
from apscheduler.schedulers.background import BackgroundScheduler
from flask_mail import Mail, Message
from urllib.parse import quote, parse_qs, urlparse
import base64, shutil, logging
from sqlalchemy.orm import joinedload
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from pathlib import Path
from markupsafe import Markup
from shutil import copyfile
from collections import defaultdict
from sqlalchemy import extract, tuple_, UniqueConstraint, Index
from threading import Lock
import undetected_chromedriver as uc
from sqlalchemy.exc import IntegrityError
from dateutil.relativedelta import relativedelta
import re, unicodedata
from sqlalchemy.dialects.postgresql import JSONB


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
    saldo_kwh = db.Column(db.Float, default=0)
    kehua_station_id = db.Column(db.String, nullable=True, unique=True)
    tusd_fio_b = db.Column(db.Boolean, nullable=False, default=False)
    boleto_proprio = db.Column(db.Boolean, nullable=False, default=False)
    
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

    # NOVO: vínculo opcional com InversorCadastrado
    inversor_id = db.Column(db.Integer, db.ForeignKey('inversores_cadastrados.id'), nullable=True)
    inversor = db.relationship('InversorCadastrado', backref=db.backref('geracoes', lazy='dynamic'))

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
    ativo = db.Column(db.Boolean, default=True)

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
    custo_tusd_fio_b = db.Column(Numeric(12, 2), nullable=True, default=None)
    
    data_cadastro = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

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

    credor_id = db.Column(db.Integer, db.ForeignKey('credores.id'), nullable=True)
    comprovante_arquivo = db.Column(db.String(255))
    
    usina = db.relationship('Usina', backref='financeiros')    
    credor = db.relationship(
        'Credor',
        backref=db.backref('financeiros', lazy='dynamic'),
        lazy='joined'
    )

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
    
class Credor(db.Model):
    __tablename__ = 'credores'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)
    cnpj = db.Column(db.String(20), nullable=True, unique=True)
    endereco = db.Column(db.String(255), nullable=True)
    telefone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(120), nullable=True)

    def __repr__(self):
        return f'<Credor {self.nome}>'
    
class ParticipacaoAcionistaDireta(db.Model):
    __tablename__ = 'participacoes_diretas'

    id = db.Column(db.Integer, primary_key=True)
    usina_id = db.Column(db.Integer, db.ForeignKey('usinas.id'), nullable=False)
    acionista_id = db.Column(db.Integer, db.ForeignKey('acionistas.id'), nullable=False)
    percentual = db.Column(db.Float, nullable=False)  # Exemplo: 25.00 para 25%

    usina = db.relationship('Usina', backref='participacoes_diretas')
    acionista = db.relationship('Acionista', backref='participacoes_diretas')
    
class InjecaoMensalUsina(db.Model):
    __tablename__ = 'injecoes_mensais_usina'

    id = db.Column(db.Integer, primary_key=True)
    usina_id = db.Column(db.Integer, db.ForeignKey('usinas.id'), nullable=False)
    ano = db.Column(db.Integer, nullable=False)
    mes = db.Column(db.Integer, nullable=False)
    kwh_injetado = db.Column(db.Float, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('usina_id', 'ano', 'mes', name='uniq_usina_ano_mes'),
    )

    usina = db.relationship('Usina', backref='injecoes')
    
class Monitoramento(db.Model):
    __tablename__ = 'monitoramentos'
    id = db.Column(db.Integer, primary_key=True)

    usina_id = db.Column(db.Integer, db.ForeignKey('usinas.id'), nullable=False, index=True)
    usina = db.relationship('Usina', backref=db.backref('monitoramentos', lazy='dynamic', cascade="all, delete-orphan"))
    inverter_sn = db.Column(db.String(100), nullable=False, index=True)

    # Recorte temporal
    data = db.Column(db.Date, nullable=False, default=date.today, index=True)
    coletado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Métricas
    etoday = db.Column(db.Float, nullable=True)
    potencia_kw = db.Column(db.Float, nullable=True)

    # Status
    online = db.Column(db.Boolean, default=False, nullable=False)
    comunicando = db.Column(db.Boolean, default=False, nullable=False)
    ultimo_ping = db.Column(db.DateTime, nullable=True)
    mensagem_erro = db.Column(db.String(255), nullable=True)

    payload_bruto = db.Column(JSONB, nullable=True)

    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_mon_usina_data', 'usina_id', 'data'),
        Index('idx_mon_usina_inversor', 'usina_id', 'inverter_sn'),
        Index('idx_mon_status_data', 'data', 'online', 'comunicando'),
        # Índice composto para acelerar “último do dia por inversor”
        Index('idx_mon_usina_sn_data_coletado', 'usina_id', 'inverter_sn', 'data', db.text('coletado_em DESC')),
    )
    
class InversorCadastrado(db.Model):
    __tablename__ = 'inversores_cadastrados'
    id = db.Column(db.Integer, primary_key=True)
    usina_id = db.Column(db.Integer, db.ForeignKey('usinas.id'), nullable=False, index=True)
    inverter_sn = db.Column(db.String(100), nullable=False)
    nome = db.Column(db.String(120), nullable=True)
    potencia_kw = db.Column(db.Float, nullable=True)
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('usina_id', 'inverter_sn', name='uniq_usina_inverter_sn'),
    )

    usina = db.relationship('Usina', backref=db.backref(
        'inversores_cadastrados', lazy='dynamic', cascade="all, delete-orphan"
    ))
    
class Empresa(db.Model):
    __tablename__ = 'empresas'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)
    cnpj = db.Column(db.String(20), nullable=True, unique=True)
    endereco = db.Column(db.String(255))
    telefone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    responsavel = db.Column(db.String(120))

    # Relacionamentos
    contas = db.relationship('FinanceiroEmpresa', backref='empresa', cascade="all, delete-orphan")
    caixas = db.relationship('CaixaBanco', backref='empresa', cascade="all, delete-orphan")
    clientes_operacionais = db.relationship('ClienteOperacional', backref='empresa', cascade="all, delete-orphan")
    centros_custos = db.relationship('CentroCusto', backref='empresa', cascade="all, delete-orphan")

class FinanceiroEmpresa(db.Model):
    __tablename__ = 'financeiro_empresa'

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    data = db.Column(db.Date, nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # 'receita' ou 'despesa'
    descricao = db.Column(db.String(255), nullable=False)
    valor = db.Column(db.Numeric(12, 2), nullable=False)

    status = db.Column(db.String(20), nullable=False, default='pendente')  # pendente, pago, recebido
    data_vencimento = db.Column(db.Date)
    conta_id = db.Column(db.Integer, db.ForeignKey('caixas_bancos.id'), nullable=True)
    comprovante_arquivo = db.Column(db.String(255), nullable=True)
    comprovante_baixa_arquivo = db.Column(db.String(255))
    plano_financeiro_id = db.Column(db.Integer, db.ForeignKey('planos_financeiros.id'), nullable=True)
    centro_custo_id = db.Column(db.Integer, db.ForeignKey('centros_custos.id'), nullable=True)
    aprovado = db.Column(db.Boolean, nullable=False, default=False)
    numero_documento = db.Column(db.String(50))  # NF/recibo
    data_liquidado = db.Column(db.Date)                          # data efetiva do pgto/recebimento
    juros = db.Column(db.Numeric(12, 2), default=0)     # juros ou multa aplicados
    
    credor_id = db.Column(db.Integer, db.ForeignKey('credores.id'), nullable=True)

    plano_financeiro = db.relationship('PlanoFinanceiro', lazy='joined')
    centro_custo = db.relationship('CentroCusto', lazy='joined')
    conta = db.relationship('CaixaBanco', lazy='selectin')
    credor = db.relationship('Credor', lazy='joined')
    
    cliente_operacional_id = db.Column(
        db.Integer,
        db.ForeignKey('clientes_operacionais.id', ondelete='SET NULL'),
        nullable=True
    )

    # NOVO: relationship (deixe explícito o foreign_keys para evitar ambiguidade)
    cliente_operacional = db.relationship(
        'ClienteOperacional',
        backref=db.backref('titulos', lazy='dynamic'),
        foreign_keys=[cliente_operacional_id]
    )
    
class FinanceiroAnexo(db.Model):
    __tablename__ = 'financeiro_anexos'

    id = db.Column(db.Integer, primary_key=True)
    titulo_id = db.Column(db.Integer, db.ForeignKey('financeiro_empresa.id', ondelete='CASCADE'), nullable=False, index=True)
    tipo = db.Column(db.String(20), nullable=False)  # 'titulo' | 'baixa'
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=True)
    uploaded_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    titulo = db.relationship('FinanceiroEmpresa', backref=db.backref('anexos', cascade='all, delete-orphan', lazy='selectin'))
    
class CaixaBanco(db.Model):
    __tablename__ = 'caixas_bancos'

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    nome = db.Column(db.String(120), nullable=False)  # Ex: Caixa Geral, Banco do Brasil, Nubank PJ
    tipo = db.Column(db.String(50), nullable=False)   # Ex: 'Caixa', 'Banco', 'Conta Digital'
    saldo_inicial = db.Column(db.Numeric(12, 2), default=0)
    saldo_atual = db.Column(db.Numeric(12, 2), default=0)
    agencia = db.Column(db.String(20), nullable=True)
    conta = db.Column(db.String(20), nullable=True)
    banco = db.Column(db.String(100), nullable=True)

    movimentacoes = db.relationship('MovimentoCaixaBanco', backref='conta', cascade="all, delete-orphan")

class MovimentoCaixaBanco(db.Model):
    __tablename__ = 'movimentos_caixa_banco'

    id = db.Column(db.Integer, primary_key=True)
    conta_id = db.Column(db.Integer, db.ForeignKey('caixas_bancos.id'), nullable=False)
    data = db.Column(db.Date, nullable=False)
    tipo = db.Column(db.String(10), nullable=False)  # 'entrada' ou 'saida'
    descricao = db.Column(db.String(255), nullable=False)
    valor = db.Column(db.Numeric(12, 2), nullable=False)
    origem = db.Column(db.String(50), nullable=True)  # opcional: 'conta_pagar', 'conta_receber', etc.
    referencia_id = db.Column(db.Integer, nullable=True)
    
class ClienteOperacional(db.Model):
    __tablename__ = 'clientes_operacionais'

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)

    nome = db.Column(db.String(255), nullable=False)
    cpf_cnpj = db.Column(db.String(20), nullable=True)  # pode ser único por empresa, ver constraint abaixo
    endereco = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    telefone = db.Column(db.String(30), nullable=True)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime(timezone=True), server_default=func.now())
    atualizado_em = db.Column(db.DateTime(timezone=True), onupdate=func.now())

    # Relacionamentos
    centros_custos = db.relationship(
        'CentroCusto',
        backref='cliente_operacional',
        cascade="all, delete-orphan",
        lazy='selectin'
    )

    __table_args__ = (
        # Evita duplicar o mesmo documento no mesmo grupo econômico
        UniqueConstraint('empresa_id', 'cpf_cnpj', name='uq_cliente_operacional_doc_por_empresa'),
        Index('ix_clientes_operacionais_empresa_nome', 'empresa_id', 'nome'),
    )

class CentroCusto(db.Model):
    __tablename__ = 'centros_custos'

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes_operacionais.id'), nullable=False)

    codigo = db.Column(db.String(50), nullable=False)   # Ex.: CC-001, 1001, etc.
    nome = db.Column(db.String(255), nullable=False)

    cpf_cnpj = db.Column(db.String(20), nullable=True)
    endereco = db.Column(db.String(255), nullable=True)
    telefone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(120), nullable=True)

    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime(timezone=True), server_default=func.now())
    atualizado_em = db.Column(db.DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        # Um mesmo código não se repete dentro da mesma empresa
        UniqueConstraint('empresa_id', 'codigo', name='uq_centro_custo_codigo_por_empresa'),
        Index('ix_centros_custos_empresa_codigo', 'empresa_id', 'codigo'),
        Index('ix_centros_custos_empresa_cliente', 'empresa_id', 'cliente_id'),
    )


class PlanoFinanceiro(db.Model):
    __tablename__ = 'planos_financeiros'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False, unique=True)  # único global
    descricao = db.Column(db.Text)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime(timezone=True), server_default=func.now())
    atualizado_em = db.Column(db.DateTime(timezone=True), onupdate=func.now())
    
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
    pode_aprovar_financeiro = db.Column(db.Boolean, default=False)

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def verificar_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)


lock_selenium = Lock()
# Pasta para uploads
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
UPLOAD_FOLDER = os.environ.get('COMPROVANTES_PATH', 'uploads')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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

        # potencia do form é string; converta para float
        potencia_str = request.form.get('potencia')
        potencia = float(str(potencia_str).replace(',', '.')) if potencia_str else None

        data_ligacao_str = request.form.get('data_ligacao')
        valor_investido_str = request.form.get('valor_investido')
        ano_atual = date.today().year

        saldo_kwh_str = request.form.get('saldo_kwh')
        saldo_kwh = float(saldo_kwh_str.replace(',', '.')) if saldo_kwh_str else 0.0

        data_ligacao = datetime.strptime(data_ligacao_str, '%Y-%m-%d').date() if data_ligacao_str else None
        valor_investido = float(valor_investido_str.replace(',', '.')) if valor_investido_str else None

        # checkboxes (funciona com hidden+checkbox)
        tusd_vals = request.form.getlist('tusd_fio_b')
        tusd_fio_b = bool(tusd_vals and str(tusd_vals[-1]).lower() in ('1', 'true', 'on', 'sim'))

        boleto_vals = request.form.getlist('boleto_proprio')
        boleto_proprio = bool(boleto_vals and str(boleto_vals[-1]).lower() in ('1', 'true', 'on', 'sim'))

        nova_usina = Usina(
            cc=cc,
            nome=nome,
            potencia_kw=potencia,
            data_ligacao=data_ligacao,
            valor_investido=valor_investido,
            saldo_kwh=saldo_kwh,
            tusd_fio_b=tusd_fio_b,          
            boleto_proprio=boleto_proprio   
        )
        db.session.add(nova_usina)
        db.session.commit()

        # upload do logo (usando LOGOS_PATH)
        if logo and logo.filename:
            filename = secure_filename(logo.filename)
            ext = os.path.splitext(filename)[1]
            unique_filename = f"{uuid.uuid4().hex}{ext}"

            caminho_base = os.path.abspath(os.getenv('LOGOS_PATH', os.path.join('static', 'logos')))
            os.makedirs(caminho_base, exist_ok=True)
            logo_path = os.path.join(caminho_base, unique_filename)

            print(f"[LOGOS] Salvando logo em: {logo_path}")
            logo.save(logo_path)

            nova_usina.logo_url = unique_filename
            db.session.commit()

        # previsões mensais
        for mes in range(1, 13):
            chave = f'previsoes[{mes}]'
            valor = request.form.get(chave)
            if valor:
                previsao = PrevisaoMensal(
                    usina_id=nova_usina.id, ano=ano_atual, mes=mes,
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
    
@app.template_filter('formato_kwh')
def formato_kwh(valor):
    if valor is None:
        return "0,00"
    try:
        return f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return valor

app.jinja_env.filters['formato_brasileiro'] = formato_brasileiro
app.jinja_env.filters['formato_tarifa'] = formato_tarifa
app.jinja_env.filters['formato_kwh'] = formato_kwh

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
        usina_id = int(request.form['usina_id']) 
        email = request.form['email']
        telefone = request.form['telefone']
        email_cc = request.form.get('email_cc')

        mostrar_saldo = request.form.get('mostrar_saldo') == 'on'
        consumo_instantaneo = 'consumo_instantaneo' in request.form

        login_concessionaria = request.form.get('login_concessionaria')
        senha_concessionaria = request.form.get('senha_concessionaria')

        # request.form.get(..., type=int) não funciona; faz a conversão manual:
        _dia_rel = request.form.get('dia_relatorio')
        dia_relatorio = int(_dia_rel) if _dia_rel else None

        relatorio_automatico = request.form.get('relatorio_automatico') == 'on'

        ativo = request.form.get('ativo') == 'on' if 'ativo' in request.form else True

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
            relatorio_automatico=relatorio_automatico,
            ativo=ativo 
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
    if request.method == 'GET' and request.args.get('ajax') == '1':
        usina_id = request.args.get('usina_id', type=int)
        if not usina_id:
            return jsonify([])

        # Clientes da usina SEM rateio nessa mesma usina
        clientes = (
            db.session.query(Cliente)
            .outerjoin(
                Rateio,
                and_(Rateio.usina_id == usina_id,
                     Rateio.cliente_id == Cliente.id)
            )
            .filter(Cliente.usina_id == usina_id)
            .filter(Rateio.id.is_(None))  # só quem não tem rateio na usina
            .order_by(Cliente.nome)
            .all()
        )

        return jsonify([{"id": c.id, "nome": c.nome} for c in clientes])

    # POST: cadastra rateio com proteção contra duplicidade
    if request.method == 'POST':
        usina_id = int(request.form['usina_id'])
        cliente_id = int(request.form['cliente_id'])
        percentual = float(request.form['percentual'])
        tarifa_kwh = float(request.form['tarifa_kwh'])

        # Impede duplicidade por segurança
        existe = (
            db.session.query(Rateio.id)
            .filter(Rateio.usina_id == usina_id,
                    Rateio.cliente_id == cliente_id)
            .first()
        )
        if existe:
            flash('Este cliente já possui rateio vinculado nesta usina.', 'warning')
            return redirect(url_for('cadastrar_rateio'))

        ultimo_codigo = (
            db.session.query(db.func.max(Rateio.codigo_rateio))
            .filter(Rateio.usina_id == usina_id)
            .scalar()
        )
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
        flash('Rateio cadastrado com sucesso!', 'success')
        return redirect(url_for('cadastrar_rateio'))

    # GET normal: renderiza página    
    usinas = Usina.query.order_by(Usina.nome).all()
    return render_template('cadastrar_rateio.html', usinas=usinas)

@app.route('/listar_rateios')
@login_required
def listar_rateios():
    usinas = Usina.query.all()
    usina_id_filtro = request.args.get('usina_id', type=int)

    # Subquery que pega o maior ID de rateio por cliente + usina
    subquery = (
        db.session.query(
            Rateio.cliente_id,
            Rateio.usina_id,
            func.max(Rateio.id).label("max_id")
        )
        .group_by(Rateio.cliente_id, Rateio.usina_id)
    )

    if usina_id_filtro:
        subquery = subquery.filter(Rateio.usina_id == usina_id_filtro)

    subquery = subquery.subquery()

    # Junta com Rateio para pegar os registros completos
    rateios = (
        db.session.query(Rateio)
        .join(subquery, and_(
            Rateio.id == subquery.c.max_id
        ))
        .order_by(Rateio.usina_id, Rateio.cliente_id)
        .all()
    )

    return render_template(
        'listar_rateios.html',
        rateios=rateios,
        usinas=usinas,
        usina_id_filtro=usina_id_filtro
    )

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
        cliente.usina_id = int(request.form['usina_id'])
        cliente.email = request.form['email']
        cliente.telefone = request.form['telefone']
        cliente.email_cc = request.form.get('email_cc')
        cliente.mostrar_saldo = request.form.get('mostrar_saldo') == 'on'
        cliente.consumo_instantaneo = 'consumo_instantaneo' in request.form

        cliente.login_concessionaria = request.form.get('login_concessionaria')
        cliente.senha_concessionaria = request.form.get('senha_concessionaria')
        cliente.dia_relatorio = request.form.get('dia_relatorio', type=int)  # mantém None se vazio
        cliente.relatorio_automatico = request.form.get('relatorio_automatico') == 'on'

        cliente.ativo = request.form.get('ativo') == 'on'

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
            
            usina = Usina.query.get(usina_id)

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
            
            # ✅ custo TUSD Fio B: pega do form se a usina usa TUSD Fio B; senão 0
            custo_tusd_fio_b_form = request.form.get('custo_tusd_fio_b')  # string tipo "322,82" (preenchida via extração)
            custo_tusd_fio_b = limpar_valor(custo_tusd_fio_b_form) if (usina and usina.tusd_fio_b) else 0.0
            # print opcional:
            # print(f"[DEBUG] usina.tusd_fio_b={getattr(usina,'tusd_fio_b',None)}; custo_tusd_fio_b={custo_tusd_fio_b}")


            if cliente and cliente.consumo_instantaneo:
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
                    energia_injetada_real=energia_injetada_real,
                    custo_tusd_fio_b=custo_tusd_fio_b
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

                    # Base de consumo para receita (igual ao que você usa pra salvar na Fatura)
                    consumo_base_receita = injetado_total if (cliente and cliente.consumo_instantaneo) else consumo_usina

                    # --- RECEITA LÍQUIDA = RECEITA BRUTA - (TUSD Fio B se aplicável) ---
                    # receita bruta: consumo * tarifa_kwh, com arredondamento de 2 casas
                    receita_bruta = (Decimal(str(consumo_base_receita)) * Decimal(str(rateio.tarifa_kwh))) \
                                        .quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

                    # TUSD Fio B (já vem limpinho do form; se não for TUSD Fio B, é 0.0)
                    tusd_dec = Decimal(str(custo_tusd_fio_b)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

                    # se a usina NÃO é TUSD Fio B, garante 0
                    if not (usina and usina.tusd_fio_b):
                        tusd_dec = Decimal('0.00')

                    receita_liquida = receita_bruta - tusd_dec
                    if receita_liquida < Decimal('0.00'):
                        receita_liquida = Decimal('0.00')

                    receita_valor = float(receita_liquida)

                    # (opcional) debug
                    # print(f"[DEBUG] receita_bruta={receita_bruta}, tusd={tusd_dec}, receita_liquida={receita_liquida}")

                    receita = FinanceiroUsina(
                        usina_id=rateio.usina_id,
                        categoria_id=None,  # pode adicionar a categoria
                        data=date(referencia_ano_receita, referencia_mes_receita, 1),  # 1º dia do mês subsequente
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
    
    # === Clientes ativos SEM fatura na competência (respeitando filtros) ===
    qtd_sem_fatura = None
    clientes_sem_fatura = []
    if mes and ano:
        clientes_q = Cliente.query.filter(Cliente.ativo.is_(True))
        if usina_id:
            clientes_q = clientes_q.filter(Cliente.usina_id == usina_id)
        if cliente_id:
            clientes_q = clientes_q.filter(Cliente.id == cliente_id)

        fatura_existe = db.session.query(FaturaMensal.id).filter(
            FaturaMensal.cliente_id == Cliente.id,
            FaturaMensal.mes_referencia == mes,
            FaturaMensal.ano_referencia == ano
        ).exists()

        sem_fatura_q = clientes_q.filter(~fatura_existe)

        qtd_sem_fatura = sem_fatura_q.count()
        clientes_sem_fatura = sem_fatura_q.order_by(Cliente.nome).all()

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
        email_enviado=email_enviado,
        qtd_sem_fatura=qtd_sem_fatura,
        clientes_sem_fatura=clientes_sem_fatura
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
    valor_conta   = Decimal(str(fatura.valor_conta_neoenergia))

    if fatura.data_cadastro:
        data_base = fatura.data_cadastro.date()
    else:
        data_base = date(2025, 8, 4)

    rateio = Rateio.query.filter(
        Rateio.cliente_id == cliente.id,
        Rateio.usina_id == usina.id,
        Rateio.data_inicio <= data_base
    ).order_by(Rateio.data_inicio.desc()).first()

    tarifa_cliente = Decimal(str(rateio.tarifa_kwh)) if rateio else Decimal('0')

    # --- Cálculos principais ---
    valor_usina_bruto = consumo_usina * tarifa_cliente

    # ✅ regra TUSD Fio B na fatura atual
    tusd_ativo_atual = bool(getattr(usina, 'tusd_fio_b', False))
    custo_tusd_atual = Decimal(str(getattr(fatura, 'custo_tusd_fio_b', 0) or 0))
    if tusd_ativo_atual:
        valor_usina_liquido = valor_usina_bruto - custo_tusd_atual
        if valor_usina_liquido < Decimal('0'):
            valor_usina_liquido = Decimal('0')
    else:
        valor_usina_liquido = valor_usina_bruto

    # usa valor_usina_liquido no "com_desconto"
    com_desconto = valor_conta + valor_usina_liquido
    sem_desconto = (consumo_usina * tarifa_neoenergia_aplicada) + valor_conta - custo_tusd_atual
    economia = sem_desconto - com_desconto

    # Economia acumulada (aplica mesma regra por fatura/usina)
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
            valor_conta_ant   = Decimal(str(f.valor_conta_neoenergia))

            # tarifa do cliente permanece a mesma (sua lógica original)
            valor_usina_ant_bruto = consumo_usina_ant * tarifa_cliente

            # ✅ regra TUSD por fatura: usa a usina daquela fatura
            usina_ant = getattr(f.cliente, 'usina', None)
            tusd_ativo_ant = bool(getattr(usina_ant, 'tusd_fio_b', False)) if usina_ant else False
            custo_tusd_ant = Decimal(str(getattr(f, 'custo_tusd_fio_b', 0) or 0))

            if tusd_ativo_ant:
                valor_usina_ant_liq = valor_usina_ant_bruto - custo_tusd_ant
                if valor_usina_ant_liq < Decimal('0'):
                    valor_usina_ant_liq = Decimal('0')
            else:
                valor_usina_ant_liq = valor_usina_ant_bruto

            com_desconto_ant = valor_conta_ant + valor_usina_ant_liq
            sem_desconto_ant = (consumo_usina_ant * tarifa_aplicada_ant) + valor_conta_ant

            economia_total += (sem_desconto_ant - com_desconto_ant)

        except Exception:
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
        ficha_compensacao_img = extrair_ficha_compensacao(
        pdf_path,
        ficha_path,
        boleto_proprio=bool(getattr(usina, 'boleto_proprio', False)),
        page_select='first' if getattr(usina, 'boleto_proprio', False) else 'last'
    )
        if ficha_compensacao_img and os.path.exists(ficha_path):
            ficha_base64 = imagem_para_base64(ficha_path)
            ficha_compensacao_data_uri = f"data:image/png;base64,{ficha_base64}"

    # Logo CGR
    logo_cgr_path = os.path.abspath("static/img/logo_cgr.png").replace('\\', '/')
    logo_cgr_data_uri = f"data:image/png;base64,{imagem_para_base64(logo_cgr_path)}"

    # Logo da usina
    logo_usina_data_uri = None
    if usina.logo_url:
        nome_arquivo = (usina.logo_url or "").strip()

        logos_base = os.path.abspath(os.getenv('LOGOS_PATH', os.path.join('static', 'logos')))
        path_env   = os.path.join(logos_base, nome_arquivo)
        path_stat  = os.path.abspath(os.path.join('static', 'logos', nome_arquivo))

        chosen = None
        if os.path.exists(path_env):
            chosen = path_env
            print(f"[LOGO] usando LOGOS_PATH: {chosen}")
        elif os.path.exists(path_stat):
            chosen = path_stat
            print(f"[LOGO] usando static/logos: {chosen}")
        else:
            print(f"[LOGO] arquivo NÃO encontrado em: {path_env} nem {path_stat}")

        if chosen:
            # detecta extensão para o header do data URI (png/jpg)
            ext = os.path.splitext(chosen)[1].lower()
            mime = "png" if ext == ".png" else "jpeg"
            logo_usina_data_uri = f"data:image/{mime};base64,{imagem_para_base64(chosen)}"

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
        # ✅ expõe os valores já líquidos
        valor_usina=valor_usina_liquido,
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
    
def extrair_ficha_compensacao(
    pdf_path,
    output_path='static/ficha_compensacao.png',
    boleto_proprio=False,
    page_select=None,                 # 'first' | 'last' | int | None
    dpi_padrao=300,
    dpi_boleto=300,
    crop_padrao=(0.37, 0.75),         # topo/bottom (% da altura) - PDF “normal”
    crop_boleto=(0.608, 0.99)          # topo/bottom para boleto próprio (ajuste se precisar)
):
    """
    Recorta a ficha de compensação.
    - Se boleto_proprio=True, usa recorte alternativo e, por padrão, pega a 1ª página.
    - page_select: 'first' | 'last' | int (0-based) | None (usa heurística padrão).
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # Resolve página
    with fitz.open(pdf_path) as doc:
        n = doc.page_count
        # Se o chamador não especificar, usamos: boleto próprio -> primeira; senão -> última
        if page_select is None:
            page_select = 'first' if boleto_proprio else 'last'

        if isinstance(page_select, int):
            idx = page_select if page_select >= 0 else n + page_select
        elif str(page_select).lower() == 'first':
            idx = 0
        else:
            idx = n - 1  # 'last' default

        idx = max(0, min(idx, n - 1))

        # DPI e crop de acordo com o tipo de boleto
        dpi = dpi_boleto if boleto_proprio else dpi_padrao
        top_pct, bot_pct = crop_boleto if boleto_proprio else crop_padrao

        # Renderiza página escolhida
        page = doc.load_page(idx)
        pix = page.get_pixmap(dpi=dpi)

        tmp_path = os.path.join('static', f"temp_page_{uuid.uuid4().hex}.png")
        pix.save(tmp_path)

    # Recorte
    img = Image.open(tmp_path)
    w, h = img.size
    top = int(h * float(top_pct))
    bottom = int(h * float(bot_pct))
    if bottom <= top:  # fallback seguro
        top, bottom = int(h * 0.37), int(h * 0.75)

    ficha = img.crop((0, top, w, bottom))
    ficha.save(output_path)

    # Debug + limpeza
    print(f"[FICHA] boleto_proprio={boleto_proprio} page={idx+1} dpi={dpi} "
          f"img={w}x{h} crop=({top_pct*100:.1f}%..{bot_pct*100:.1f}%) out={output_path}")
    try:
        os.remove(tmp_path)
    except Exception:
        pass

    return output_path

def extrair_comprovante_em_imagens(pdf_path, output_prefix):
    imagens_base64 = []

    try:
        doc = fitz.open(pdf_path)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=150)
            nome_img = f"{output_prefix}_p{i+1}.jpg"
            output_path = os.path.join('static', nome_img)

            if not os.path.exists(output_path):
                pix.save(output_path)

            if os.path.exists(output_path):
                base64_img = imagem_para_base64(output_path)
                imagens_base64.append(f"data:image/jpeg;base64,{base64_img}")
    except Exception as e:
        print(f"Erro ao extrair comprovante em imagens: {e}")

    return imagens_base64

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

@app.route('/cliente_por_codigo/<codigo>', methods=['GET'])
@login_required
def cliente_por_codigo(codigo):
    # Normaliza a entrada para: somente [0-9A-Z], em maiúsculas
    cod_alnum = re.sub(r'[^0-9A-Za-z]', '', codigo or '').upper()

    if not cod_alnum:
        return jsonify({'encontrado': False, 'erro': 'codigo vazio'}), 400

    # Monta chaves candidatas:
    # 1) exatamente como veio (normalizado)
    # 2) se vier só números, tenta também com 'X' no final (ex.: 3062150 -> 3062150X)
    chaves = {cod_alnum}
    if cod_alnum.isdigit():
        chaves.add(cod_alnum + 'X')

    # Normaliza o lado do banco para [0-9A-Z] maiúsculo também
    norm_db = func.upper(func.regexp_replace(Cliente.codigo_unidade, '[^0-9A-Za-z]', '', 'g'))

    cliente = (
        db.session.query(Cliente)
        .filter(norm_db.in_(list(chaves)))
        .first()
    )

    if not cliente:
        return jsonify({'encontrado': False}), 404

    return jsonify({
        'encontrado': True,
        'cliente': {
            'id': cliente.id,
            'nome': cliente.nome,
            'codigo_unidade': cliente.codigo_unidade
        },
        'usina': {
            'id': cliente.usina.id,
            'nome': cliente.usina.nome
        }
    })

@app.route('/extrair_dados_fatura', methods=['POST'])
@login_required
def extrair_dados_fatura():
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
    
    def buscar_codigo_cliente():
        # Normaliza acentos p/ achar o rótulo mesmo se vier "CÓDIGO" ou "CODIGO"
        def norm(s: str) -> str:
            s = unicodedata.normalize('NFKD', s)
            s = ''.join(ch for ch in s if not unicodedata.category(ch).startswith('M'))
            return s.upper()

        # Aceita DV numérico OU letra (ex.: X). Mantém padrão estrito (sem espaços no meio).
        patt_dotted = re.compile(r'\b\d{1,3}(?:\.\d{3}){1,2}[-–][0-9A-Z]?\b', re.IGNORECASE)
        patt_plain  = re.compile(r'\b\d{6,7}[-–][0-9A-Z]?\b',                  re.IGNORECASE)

        def pick_one(text: str):
            # tenta pontuado primeiro, depois “seco”
            m = patt_dotted.search(text)
            if m:
                return m.group(0).upper()
            m = patt_plain.search(text)
            if m:
                return m.group(0).upper()
            return None

        def garantir_dv(code: str) -> str | None:
            """
            Se terminar em hífen (sem DV), acrescenta 'X'.
            Retorna o código (possivelmente ajustado) ou None.
            """
            if not code:
                return None
            if code.endswith('-') or code.endswith('–'):
                return code + 'X'
            return code

        # 1) Prioriza achar perto do rótulo (mesma linha e próximas 4)
        for i, linha in enumerate(linhas):
            up = norm(linha)
            if ("CODIGO" in up and "CLIENTE" in up):
                for k in range(0, 5):
                    if i + k < len(linhas):
                        trecho = linhas[i + k]
                        code = garantir_dv(pick_one(trecho))
                        if code:
                            print(f"[DEBUG] codigo_cliente (perto do rotulo): {code}")
                            return code

                # junta algumas linhas (sem quebras) caso quebre no PDF
                joined = " ".join(linhas[i:i+5])
                code = garantir_dv(pick_one(joined))
                if code:
                    print(f"[DEBUG] codigo_cliente (linhas concatenadas): {code}")
                    return code

        # 2) Fallback no texto inteiro, removendo quebras de linha
        code = garantir_dv(pick_one(texto.replace("\n", " ")))
        if code:
            print(f"[DEBUG] codigo_cliente (fallback): {code}")
            return code

        print("[DEBUG] codigo_cliente não encontrado")
        return None
    
    def buscar_custo_tusd_fio_b():
        label_re  = re.compile(r'CUSTO\s+TUSD\s+FIO\s*B', re.IGNORECASE)
        money_re  = re.compile(r'\b\d{1,3}(?:\.\d{3})*,\d{2}\b|\b\d+,\d{2}\b')
        alpha_re  = re.compile(r'[A-Za-zÀ-ÿ]')  # detecta linhas com texto (novo item/rotulo)
        scan_span = 12  # quantas linhas olhar à frente no máximo

        for i, ln in enumerate(linhas):
            if label_re.search(ln):
                # Varre as próximas linhas até achar um valor monetário ou encontrar texto (novo rótulo)
                for j, l2 in enumerate(linhas[i+1:i+1+scan_span], start=1):
                    if alpha_re.search(l2):  # chegamos em outro item/rotulo -> parar
                        break
                    m = money_re.search(l2)
                    if m:
                        br  = m.group(0)
                        dot = br.replace('.', '').replace(',', '.')
                        print(f"[DEBUG][TUSD] label@{i}; valor escolhido linha {i+j}: {br} -> {dot}")
                        return dot
                print(f"[DEBUG][TUSD] label@{i}; nenhum valor encontrado até o próximo rótulo")
                return None

        print("[DEBUG][TUSD] label não encontrado")
        return None

    # Buscar dados
    inicio_leitura, fim_leitura = buscar_datas()
    
    custo_tusd_fio_b_val = buscar_custo_tusd_fio_b()
    print(f"[DEBUG] custo_tusd_fio_b extraído: {custo_tusd_fio_b_val}")

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
        'energia_injetada_real': buscar_energia_injetada_real(),
        'codigo_cliente': buscar_codigo_cliente(),
        'custo_tusd_fio_b': buscar_custo_tusd_fio_b()
    }
    print(f"[DEBUG] codigo_cliente extraído: {dados['codigo_cliente']}")

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
                
            saldo_kwh_str = request.form.get('saldo_kwh')
            if saldo_kwh_str:
                usina.saldo_kwh = float(saldo_kwh_str.replace(',', '.'))
                
            # novo campo: TUSD Fio B
            # Se usar hidden (0) + checkbox (1), getlist retornará ['0'] ou ['0','1'].
            tusd_vals = request.form.getlist('tusd_fio_b')
            if tusd_vals:
                last_val = str(tusd_vals[-1]).strip().lower()
                usina.tusd_fio_b = last_val in ('1', 'true', 'on', 'sim')
                
            boleto_vals = request.form.getlist('boleto_proprio')
            if boleto_vals:
                last_val = str(boleto_vals[-1]).strip().lower()
                usina.boleto_proprio = last_val in ('1', 'true', 'on', 'sim')

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
        quer_aprovador = 'pode_aprovar_financeiro' in request.form

        try:
            if quer_aprovador:
                # zera todos os demais
                Usuario.query.filter(Usuario.id != usuario.id).update(
                    {Usuario.pode_aprovar_financeiro: False}
                )
                usuario.pode_aprovar_financeiro = True
            else:
                # permite ficar sem aprovador (se quiser obrigar 1 sempre, avise que adapto)
                usuario.pode_aprovar_financeiro = False

            if request.form.get('senha'):
                usuario.set_senha(request.form['senha'])

            db.session.commit()
            flash('Usuário atualizado com sucesso.', 'success')
        except Exception as e:
            db.session.rollback()
            print('Erro ao editar usuário:', e)
            flash('Erro ao salvar alterações.', 'danger')

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

    #  PARTE SOLIS
    
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

    #  PARTE KEHUA
    
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

    #  Salvar total por usina
    
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
scheduler.add_job(func=atualizar_geracao_agendada, trigger="interval", minutes=25)
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

    usinas = Usina.query.order_by(Usina.nome).all()
    categorias = CategoriaDespesa.query.order_by(CategoriaDespesa.nome).all()
    credores = Credor.query.order_by(Credor.nome).all()
    mensagem = None
    data_hoje = date.today().isoformat()

    if request.method == 'POST':
        try:
            # Campos do formulário
            usina_id = int(request.form['usina_id'])
            categoria_id = int(request.form['categoria_id'])
            credor_id = request.form.get('credor_id')
            credor_id = int(credor_id) if credor_id else None
            valor = float(request.form['valor'].replace(',', '.'))
            descricao = request.form['descricao']
            data = datetime.strptime(request.form['data'], '%Y-%m-%d').date()
            referencia_mes = int(request.form['referencia_mes'])
            referencia_ano = int(request.form['referencia_ano'])

            # Upload de comprovante
            arquivo = request.files.get('arquivo')
            comprovante_arquivo = None

            if arquivo and allowed_file(arquivo.filename):
                filename = secure_filename(arquivo.filename)
                upload_dir = app.config['UPLOAD_FOLDER']
                os.makedirs(upload_dir, exist_ok=True)
                caminho = os.path.join(upload_dir, filename)

                if os.path.exists(caminho):
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                    filename = f"{timestamp}_{filename}"
                    caminho = os.path.join(upload_dir, filename)

                arquivo.save(caminho)
                comprovante_arquivo = filename

            # Criação da despesa
            nova_despesa = FinanceiroUsina(
                usina_id=usina_id,
                categoria_id=categoria_id,
                credor_id=credor_id,
                tipo='despesa',
                valor=valor,
                descricao=descricao,
                data=data,
                referencia_mes=referencia_mes,
                referencia_ano=referencia_ano,
                comprovante_arquivo=comprovante_arquivo
            )

            db.session.add(nova_despesa)
            db.session.commit()
            mensagem = 'Despesa registrada com sucesso.'

        except Exception as e:
            db.session.rollback()
            mensagem = f'Erro ao registrar despesa: {e}'

    return render_template(
        'registrar_despesa.html',
        usinas=usinas,
        categorias=categorias,
        credores=credores,
        mensagem=mensagem,
        data_hoje=data_hoje
    )

@app.route('/financeiro')
@login_required
def financeiro():
    if not current_user.pode_acessar_financeiro:
        return "Acesso negado", 403

    # Dados para os selects
    usinas = Usina.query.order_by(Usina.nome).all()
    categorias = CategoriaDespesa.query.order_by(CategoriaDespesa.nome).all()

    # Filtros de período e entidades
    mes = request.args.get('mes', default=date.today().month, type=int)
    ano = request.args.get('ano', default=date.today().year, type=int)
    usina_id = request.args.get('usina_id', type=int)
    tipo = request.args.get('tipo')                   # 'receita' ou 'despesa'
    categoria_id = request.args.get('categoria_id', type=int)

    # Parâmetros de ordenação
    sort = request.args.get('sort', default='data_pagamento')
    direction = request.args.get('direction', default='desc')  # 'asc' ou 'desc'

    # Mapeamento seguro das colunas ordenáveis
    allowed_sorts = {
        'tipo': FinanceiroUsina.tipo,
        'usina': Usina.nome,
        'descricao': FinanceiroUsina.descricao,
        'categoria': CategoriaDespesa.nome,
        'valor': FinanceiroUsina.valor,
        'juros': FinanceiroUsina.juros,
        'referencia': FinanceiroUsina.referencia_ano,
        'data_pagamento': FinanceiroUsina.data_pagamento,
    }
    sort_col = allowed_sorts.get(sort, FinanceiroUsina.data_pagamento)

    # Query base com LEFT OUTER JOIN para incluir receitas sem usina/categoria vinculadas
    query = (
        FinanceiroUsina.query
        .options(
            joinedload(FinanceiroUsina.credor),
            joinedload(FinanceiroUsina.usina),
            joinedload(FinanceiroUsina.categoria)
        )
        .outerjoin(Usina, FinanceiroUsina.usina_id == Usina.id)
        .outerjoin(CategoriaDespesa, FinanceiroUsina.categoria_id == CategoriaDespesa.id)
        .filter(
            FinanceiroUsina.referencia_mes == mes,
            FinanceiroUsina.referencia_ano == ano
        )
    )

    # Aplica demais filtros
    if usina_id:
        query = query.filter(FinanceiroUsina.usina_id == usina_id)
    if tipo in ['receita', 'despesa']:
        query = query.filter(FinanceiroUsina.tipo == tipo)
    if categoria_id:
        query = query.filter(FinanceiroUsina.categoria_id == categoria_id)

    # Ordenação dinâmica
    if direction == 'asc':
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    registros = query.all()

    # Monta lista para o template e calcula totais
    financeiro = []
    total_receitas = Decimal('0')
    total_despesas = Decimal('0')

    for r in registros:
        valor = Decimal(str(r.valor or 0))
        juros = Decimal(str(r.juros or 0))

        financeiro.append({
            'id': r.id,
            'tipo': r.tipo,
            'usina': r.usina.nome if r.usina else 'N/A',
            'categoria': r.categoria.nome if r.categoria else '-',
            'credor': r.credor.nome if r.credor else '-',
            'descricao': r.descricao,
            'valor': valor,
            'juros': float(juros),
            'referencia': f"{r.referencia_mes:02d}/{r.referencia_ano}",
            'data_pagamento': r.data_pagamento
        })

        if r.tipo == 'receita':
            total_receitas += valor + juros
        else:
            total_despesas += valor

    return render_template(
        'financeiro.html',
        financeiro=financeiro,
        usinas=usinas,
        categorias=categorias,
        mes=mes,
        ano=ano,
        usina_id=usina_id,
        tipo=tipo,
        categoria_id=categoria_id,
        sort=sort,
        direction=direction,
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

def extensao_permitida(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/editar_despesa/<int:despesa_id>', methods=['GET', 'POST'])
@login_required
def editar_despesa(despesa_id):
    if not current_user.pode_acessar_financeiro:
        abort(403)

    despesa = FinanceiroUsina.query.get_or_404(despesa_id)
    usinas = Usina.query.order_by(Usina.nome).all()
    categorias = CategoriaDespesa.query.order_by(CategoriaDespesa.nome).all()
    credores = Credor.query.order_by(Credor.nome).all()

    if request.method == 'POST':
        despesa.usina_id = int(request.form['usina_id'])
        despesa.categoria_id = int(request.form['categoria_id'])
        cid = request.form.get('credor_id')
        despesa.credor_id = int(cid) if cid else None
        despesa.descricao = request.form['descricao']
        despesa.valor = float(request.form['valor'].replace(',', '.'))
        despesa.data = datetime.strptime(request.form['data'], '%Y-%m-%d').date()
        despesa.referencia_mes = int(request.form['referencia_mes'])
        despesa.referencia_ano = int(request.form['referencia_ano'])

        # ✔️ Verifica e processa novo comprovante
        if 'comprovante' in request.files:
            comprovante = request.files['comprovante']
            if comprovante and comprovante.filename:
                # Remove comprovante antigo, se houver
                if despesa.comprovante_arquivo:
                    antigo_path = os.path.join(app.config['UPLOAD_FOLDER'], despesa.comprovante_arquivo)
                    if os.path.exists(antigo_path):
                        os.remove(antigo_path)

                # Gera novo nome com timestamp
                extensao = secure_filename(comprovante.filename).rsplit('.', 1)[-1].lower()
                nome_arquivo = f"comprovante_{despesa.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{extensao}"

                # Salva o novo arquivo
                caminho_final = os.path.join(app.config['UPLOAD_FOLDER'], nome_arquivo)
                comprovante.save(caminho_final)

                # Atualiza no banco
                despesa.comprovante_arquivo = nome_arquivo

        db.session.commit()
        return redirect(url_for('listar_despesas'))

    return render_template(
        'editar_despesa.html',
        despesa=despesa,
        usinas=usinas,
        categorias=categorias,
        credores=credores
    )

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
    
@app.route('/excluir_despesa/<int:despesa_id>', methods=['POST'])
@login_required
def excluir_despesa(despesa_id):
    despesa = FinanceiroUsina.query.get_or_404(despesa_id)

    db.session.delete(despesa)
    db.session.commit()
    flash(f'Despesa #{despesa_id} excluída com sucesso.', 'success')

    # redireciona de volta mantendo filtros (se quiser)
    return redirect(url_for(
        'listar_despesas',
        usina_id=request.args.get('usina_id', ''),
        data_inicio=request.args.get('data_inicio', ''),
        data_fim=request.args.get('data_fim', '')
    ))

@app.route('/relatorio_financeiro', methods=['GET'])
@login_required
def relatorio_financeiro():
    if not current_user.pode_acessar_financeiro:
        return "Acesso negado", 403

    ano = request.args.get('ano', type=int, default=datetime.now().year)
    usina_id = request.args.get('usina_id', type=int)

    usinas = Usina.query.order_by(Usina.nome).all()
    anos_disponiveis = sorted({
        r[0] for r in db.session.query(db.extract('year', Geracao.data)).distinct().all()
    }, reverse=True)

    dados = []
    usinas_filtradas = [u for u in usinas if not usina_id or u.id == usina_id]

    for usina in usinas_filtradas:
        kwh_acumulado = 0
        faturado_acumulado = 0
        mes_limite = 12
        if ano == datetime.now().year:
            mes_limite = datetime.now().month - 1

        for mes in range(1, mes_limite + 1):
            geracao = db.session.query(db.func.sum(Geracao.energia_kwh)).filter(
                Geracao.usina_id == usina.id,
                db.extract('month', Geracao.data) == mes,
                db.extract('year', Geracao.data) == ano
            ).scalar() or 0

            injecao = db.session.query(db.func.sum(InjecaoMensalUsina.kwh_injetado)).filter(
                InjecaoMensalUsina.usina_id == usina.id,
                InjecaoMensalUsina.mes == mes,
                InjecaoMensalUsina.ano == ano
            ).scalar() or 0

            consumo = db.session.query(db.func.sum(FaturaMensal.consumo_usina)).join(Cliente).filter(
                Cliente.usina_id == usina.id,
                FaturaMensal.mes_referencia == mes,
                FaturaMensal.ano_referencia == ano
            ).scalar() or 0

            faturado = db.session.query(db.func.sum(FinanceiroUsina.valor)).filter(
                FinanceiroUsina.usina_id == usina.id,
                FinanceiroUsina.tipo == 'receita',
                db.extract('month', FinanceiroUsina.data) == mes,
                db.extract('year', FinanceiroUsina.data) == ano
            ).scalar() or 0

            kwh_acumulado += consumo
            faturado_acumulado += faturado or 0

            saldo_unidade = db.session.query(db.func.sum(FaturaMensal.saldo_unidade)).join(Cliente).filter(
                Cliente.usina_id == usina.id,
                FaturaMensal.mes_referencia == mes,
                FaturaMensal.ano_referencia == ano
            ).scalar() or 0

            dados.append({
                'mes': mes,
                'usina_nome': usina.nome,
                'geracao': round(geracao, 2),
                'injecao': round(injecao, 2),
                'diferenca': round(geracao - injecao, 2),
                'consumo': round(consumo, 2),
                'faturado': round(faturado or 0, 2),
                'faturado_acumulado': round(faturado_acumulado, 2),
                'saldo_unidade': round(saldo_unidade, 2),
            })

    # ✅ Agora sim, consolida após preencher os dados
    consolidacao = []
    for usina in usinas_filtradas:
        geracao_total = sum(l['geracao'] for l in dados if l['usina_nome'] == usina.nome)
        faturado_total = sum(l['faturado'] for l in dados if l['usina_nome'] == usina.nome)
        ultimo_saldo = next(
            (l['saldo_unidade'] for l in reversed(dados) if l['usina_nome'] == usina.nome),
            0
        )

        consolidacao.append({
            'usina_nome': usina.nome,
            'geracao_total': geracao_total,
            'faturado_total': faturado_total,
            'ultimo_saldo': ultimo_saldo
        })

    return render_template(
        'relatorio_financeiro.html',
        relatorio=dados,
        consolidacao=consolidacao,
        usinas=usinas,
        usina_id=usina_id,
        ano=ano,
        anos_disponiveis=anos_disponiveis
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

    total_receitas = Decimal('0')
    total_despesas = Decimal('0')
    total_saldo = Decimal('0')
    total_saldo_acumulado = Decimal('0')

    # condição equivalente para acumulados por data_pagamento até o mês/ano selecionado
    cond_dp_acum = or_(
        extract('year', FinanceiroUsina.data_pagamento) < ano,
        and_(
            extract('year', FinanceiroUsina.data_pagamento) == ano,
            extract('month', FinanceiroUsina.data_pagamento) <= mes
        )
    )

    for u in usinas:
        # — receitas pagas no mês/ano (data_pagamento)
        receitas = db.session.query(
            func.coalesce(
                func.sum(FinanceiroUsina.valor + func.coalesce(FinanceiroUsina.juros, 0)),
                0
            )
        ).filter(
            FinanceiroUsina.usina_id == u.id,
            FinanceiroUsina.tipo == 'receita',
            FinanceiroUsina.data_pagamento.isnot(None),
            extract('year', FinanceiroUsina.data_pagamento) == ano,
            extract('month', FinanceiroUsina.data_pagamento) == mes
        ).scalar()

        # — despesas pagas no mês/ano (data_pagamento)
        despesas = db.session.query(
            func.coalesce(func.sum(FinanceiroUsina.valor), 0)
        ).filter(
            FinanceiroUsina.usina_id == u.id,
            FinanceiroUsina.tipo == 'despesa',
            FinanceiroUsina.data_pagamento.isnot(None),
            extract('year', FinanceiroUsina.data_pagamento) == ano,
            extract('month', FinanceiroUsina.data_pagamento) == mes
        ).scalar()

        saldo = Decimal(receitas) - Decimal(despesas)

        # — acumulado de receitas até o mês (data_pagamento)
        receitas_acum = db.session.query(
            func.coalesce(
                func.sum(FinanceiroUsina.valor + func.coalesce(FinanceiroUsina.juros, 0)),
                0
            )
        ).filter(
            FinanceiroUsina.usina_id == u.id,
            FinanceiroUsina.tipo == 'receita',
            FinanceiroUsina.data_pagamento.isnot(None),
            cond_dp_acum
        ).scalar()

        # — acumulado de despesas até o mês (data_pagamento)
        despesas_acum = db.session.query(
            func.coalesce(func.sum(FinanceiroUsina.valor), 0)
        ).filter(
            FinanceiroUsina.usina_id == u.id,
            FinanceiroUsina.tipo == 'despesa',
            FinanceiroUsina.data_pagamento.isnot(None),
            cond_dp_acum
        ).scalar()

        saldo_acumulado = Decimal(receitas_acum) - Decimal(despesas_acum)

        resultado.append({
            'usina_id': u.id,
            'usina': u.nome,
            'receitas': receitas,
            'despesas': despesas,
            'saldo': saldo,
            'saldo_acumulado': saldo_acumulado
        })

        total_receitas += Decimal(receitas)
        total_despesas += Decimal(despesas)
        total_saldo += saldo
        total_saldo_acumulado += saldo_acumulado

    return render_template(
        'relatorio_consolidado.html',
        resultado=resultado,
        mes=mes,
        ano=ano,
        total_receitas=total_receitas,
        total_despesas=total_despesas,
        total_saldo=total_saldo,
        total_saldo_acum=total_saldo_acumulado
    )

@app.route('/autorizacao_pagamento/<int:item_id>', methods=['GET'])
@login_required
def autorizacao_pagamento(item_id):
    if not current_user.pode_acessar_financeiro:
        abort(403)

    current_date = datetime.now().strftime('%d/%m/%Y, %H:%M')
    item = FinanceiroUsina.query.get_or_404(item_id)

    if item.tipo != 'despesa':
        abort(404)

    # ⬇️ Processar comprovante (imagem ou PDF)
    comprovante_imagens = []
    if item.comprovante_arquivo:
        caminho = os.path.join(app.config['UPLOAD_FOLDER'], item.comprovante_arquivo)
        ext = item.comprovante_arquivo.lower().split('.')[-1]

        if ext == 'pdf':
            comprovante_imagens = extrair_comprovante_em_imagens(
                pdf_path=caminho,
                output_prefix=f"comprovante_{item.id}"
            )
        elif ext in ['jpg', 'jpeg', 'png']:
            if os.path.exists(caminho):
                base64_img = imagem_para_base64(caminho)
                comprovante_imagens = [f"data:image/jpeg;base64,{base64_img}"]

    return render_template(
        'autorizacao_pagamento.html',
        item=item,
        current_date=current_date,
        comprovante_imagens=comprovante_imagens
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
    mes = request.args.get('mes', default=date.today().month, type=int)
    ano = request.args.get('ano', default=date.today().year, type=int)
    usina_id = request.args.get('usina_id', type=int)
    cliente_id = request.args.get('cliente_id', type=int)

    # ----- Helpers -----
    def periodo_mes(yy: int, mm: int):
        d1 = date(yy, mm, 1)
        dF = date(yy, mm, monthrange(yy, mm)[1])
        return d1, dF

    def tarifa_aplicada_por_icms(tarifa_base: Decimal, icms: int) -> Decimal:
        if icms == 0:
            return tarifa_base * Decimal('1.2625')
        elif icms == 20:
            return tarifa_base
        else:
            return tarifa_base * Decimal('1.1023232323')

    def rateio_contratado_para_mes(cid: int, uid: int, d1: date, dF: date):
        """
        Contratado (% e tarifa) para o mês:
        1) último rateio DENTRO do mês [d1, dF]
        2) senão, último rateio ATÉ o fim do mês (<= dF)
        3) senão, PRIMEIRO rateio APÓS o início do mês (>= d1)
        (sem filtro por 'ativo', seguindo relatorio_fatura)
        """
        # 1) dentro do mês
        r = (Rateio.query
            .filter(
                Rateio.cliente_id == cid,
                Rateio.usina_id == uid,
                Rateio.data_inicio >= d1,
                Rateio.data_inicio <= dF,
            )
            .order_by(Rateio.data_inicio.desc(), Rateio.id.desc())
            .first())
        if r:
            return float(r.percentual or 0.0), Decimal(str(r.tarifa_kwh or 0))

        # 2) até o fim do mês
        r = (Rateio.query
            .filter(
                Rateio.cliente_id == cid,
                Rateio.usina_id == uid,
                Rateio.data_inicio <= dF,
            )
            .order_by(Rateio.data_inicio.desc(), Rateio.id.desc())
            .first())
        if r:
            return float(r.percentual or 0.0), Decimal(str(r.tarifa_kwh or 0))

        # 3) primeiro após o início do mês (próximo futuro)
        r = (Rateio.query
            .filter(
                Rateio.cliente_id == cid,
                Rateio.usina_id == uid,
                Rateio.data_inicio >= d1,
            )
            .order_by(Rateio.data_inicio.asc(), Rateio.id.asc())
            .first())
        if r:
            return float(r.percentual or 0.0), Decimal(str(r.tarifa_kwh or 0))

        return 0.0, Decimal('0')

    def rateio_vigente_na_data(cid: int, uid: int, data_ref: date):
        """Para economia por fatura: último rateio com data_inicio <= data_ref (sem 'ativo')."""
        return (Rateio.query
                .filter(
                    Rateio.cliente_id == cid,
                    Rateio.usina_id == uid,
                    Rateio.data_inicio <= data_ref,
                )
                .order_by(Rateio.data_inicio.desc(), Rateio.id.desc())
                .first())

    d1_mes, dF_mes = periodo_mes(ano, mes)

    # ---------- kWh injetado por usina no mês/ano ----------
    sub_injecao = (
        db.session.query(
            InjecaoMensalUsina.usina_id.label('usina_id'),
            func.coalesce(InjecaoMensalUsina.kwh_injetado, 0.0).label('kwh_injetado')
        )
        .filter(
            InjecaoMensalUsina.mes == mes,
            InjecaoMensalUsina.ano == ano
        )
        .subquery()
    )

    # ---------- Base por cliente/usina (consumo e saldo no mês) ----------
    consumo_sum_expr = func.sum(FaturaMensal.consumo_usina)
    saldo_unidade_sum = func.sum(FaturaMensal.saldo_unidade)

    query = (
        db.session.query(
            Cliente.id.label("cliente_id"),
            Cliente.nome.label("cliente"),
            Usina.id.label("usina_id"),
            Usina.nome.label("usina"),
            FaturaMensal.mes_referencia,
            FaturaMensal.ano_referencia,
            consumo_sum_expr.label("consumo_total"),
            saldo_unidade_sum.label("saldo_unidade"),
            sub_injecao.c.kwh_injetado.label("kwh_injetado"),
        )
        .join(Cliente, FaturaMensal.cliente_id == Cliente.id)
        .join(Usina, Cliente.usina_id == Usina.id)
        .join(sub_injecao, sub_injecao.c.usina_id == Usina.id, isouter=True)
        .filter(
            FaturaMensal.mes_referencia == mes,
            FaturaMensal.ano_referencia == ano
        )
    )

    if usina_id:
        query = query.filter(Cliente.usina_id == usina_id)
    if cliente_id:
        query = query.filter(Cliente.id == cliente_id)

    query = (
        query.group_by(
            Cliente.id, Cliente.nome,
            Usina.id, Usina.nome,
            FaturaMensal.mes_referencia, FaturaMensal.ano_referencia,
            sub_injecao.c.kwh_injetado,
        )
        .order_by(Cliente.nome)
    )

    base_rows = query.all()
    
    # ---------- Média de consumo (últimos 6 meses, incluindo o mês filtrado) ----------
    # Gera a lista [(ano, mes)] para a janela de 6 meses
    base_ref = date(ano, mes, 1)
    janela_6m = []
    for i in range(5, -1, -1):  # 5 meses atrás até o mês atual
        dt = base_ref - relativedelta(months=i)
        janela_6m.append((dt.year, dt.month))

    # Soma mensal por cliente dentro da janela e depois média das somas
    q_media = (
        db.session.query(
            FaturaMensal.cliente_id.label('cliente_id'),
            FaturaMensal.ano_referencia.label('ano'),
            FaturaMensal.mes_referencia.label('mes'),
            func.sum(FaturaMensal.consumo_usina).label('consumo_mes')
        )
        .join(Cliente, Cliente.id == FaturaMensal.cliente_id)
        .filter(tuple_(FaturaMensal.ano_referencia, FaturaMensal.mes_referencia).in_(janela_6m))
    )

    if usina_id:
        q_media = q_media.filter(Cliente.usina_id == usina_id)
    if cliente_id:
        q_media = q_media.filter(FaturaMensal.cliente_id == cliente_id)

    q_media = q_media.group_by(
        FaturaMensal.cliente_id,
        FaturaMensal.ano_referencia,
        FaturaMensal.mes_referencia
    )

    rows_media = q_media.all()

    cons_por_cliente = defaultdict(list)
    for rm in rows_media:
        v = float(rm.consumo_mes or 0.0)
        if v > 0:                       # <-- descarta meses com 0
            cons_por_cliente[rm.cliente_id].append(v)

    media6_por_cliente = {
        cid: (sum(vals) / len(vals)) if vals else 0.0
        for cid, vals in cons_por_cliente.items()
    }
    
    # ---------- Montagem das linhas ----------
    linhas = []
    for r in base_rows:
        cid = r.cliente_id
        uid = r.usina_id

        # Percentual do mês (com fallback para último <= fim do mês)
        pct_mes, _tarifa_mes = rateio_contratado_para_mes(cid, uid, d1_mes, dF_mes)

        # Base do contratado: injeção do mês
        kwh_base = float(r.kwh_injetado or 0.0)
        kwh_contratado = (pct_mes / 100.0) * kwh_base

        consumo_total = float(r.consumo_total or 0.0)
        diferenca_kwh = kwh_contratado - consumo_total
        percentual_dif = (diferenca_kwh / kwh_contratado * 100.0) if kwh_contratado else None

        # 1) Economia do mês (somatório por fatura) — igual ao relatorio_fatura
        faturas_mes = (FaturaMensal.query
            .filter(
                FaturaMensal.cliente_id == cid,
                FaturaMensal.mes_referencia == mes,
                FaturaMensal.ano_referencia == ano
            ).all())

        economia_mes = Decimal('0')
        for f in faturas_mes:
            tarifa_base = Decimal(str(f.tarifa_neoenergia or 0))
            t_aplicada = tarifa_aplicada_por_icms(tarifa_base, int(f.icms or 0))
            consumo = Decimal(str(f.consumo_usina or 0))

            data_base = f.data_cadastro.date() if f.data_cadastro else date(2025, 8, 4)
            rvig = rateio_vigente_na_data(cid, uid, data_base)
            tarifa_cliente = Decimal(str(rvig.tarifa_kwh)) if rvig else Decimal('0')

            economia_mes += consumo * (t_aplicada - tarifa_cliente)

        # 2) Economia acumulada (meses anteriores) com tarifa do mês corrente
        rvig_mes = (Rateio.query
                    .filter(
                        Rateio.cliente_id == cid,
                        Rateio.usina_id == uid,
                        Rateio.data_inicio <= dF_mes
                    )
                    .order_by(Rateio.data_inicio.desc(), Rateio.id.desc())
                    .first())
        tarifa_cliente_mes = Decimal(str(rvig_mes.tarifa_kwh)) if rvig_mes else Decimal('0')

        faturas_prev = (FaturaMensal.query
            .filter(
                FaturaMensal.cliente_id == cid,
                or_(
                    FaturaMensal.ano_referencia < ano,
                    and_(
                        FaturaMensal.ano_referencia == ano,
                        FaturaMensal.mes_referencia < mes
                    )
                )
            ).all())

        economia_prev = Decimal('0')
        for f in faturas_prev:
            tarifa_base_ant = Decimal(str(f.tarifa_neoenergia or 0))
            t_aplicada_ant = tarifa_aplicada_por_icms(tarifa_base_ant, int(f.icms or 0))
            consumo_ant = Decimal(str(f.consumo_usina or 0))
            economia_prev += consumo_ant * (t_aplicada_ant - tarifa_cliente_mes)

        # 3) Economia Extra (soma total, como no relatorio_fatura)
        economia_extra_total = Decimal('0')
        if 'EconomiaExtra' in globals():
            economia_extra_total = Decimal(str(
                db.session.query(func.coalesce(func.sum(EconomiaExtra.valor_extra), 0))
                .filter(EconomiaExtra.cliente_id == cid)
                .scalar() or 0
            ))

        economia_acumulada = economia_mes + economia_prev + economia_extra_total

        linhas.append({
            "cliente_id": r.cliente_id,
            "cliente": r.cliente,
            "usina_id": r.usina_id,
            "usina": r.usina,
            "percentual": pct_mes,                 # % efetivo do mês
            "mes_referencia": r.mes_referencia,
            "ano_referencia": r.ano_referencia,
            "consumo_total": consumo_total,
            "kwh_contratado": kwh_contratado,
            "diferenca_kwh": diferenca_kwh,        # contratado − consumido
            "percentual_diferenca": percentual_dif,# None se contratado == 0
            "saldo_unidade": float(r.saldo_unidade or 0),
            "economia": float(economia_mes),
            "economia_acumulada": float(economia_acumulada),
            "media_consumo_6m": media6_por_cliente.get(cid, 0.0)
        })

    # Totais
    totais = {
        "kwh_contratado": sum((x.get("kwh_contratado") or 0) for x in linhas),
        "consumo_total": sum((x.get("consumo_total")  or 0) for x in linhas),
        "diferenca_kwh": sum((x.get("kwh_contratado") or 0) - (x.get("consumo_total") or 0) for x in linhas),
        "economia": sum((x.get("economia") or 0) for x in linhas),
        "economia_acumulada": sum((x.get("economia_acumulada") or 0) for x in linhas),
        "saldo_unidade": sum((x.get("saldo_unidade") or 0) for x in linhas),
    }

    return render_template(
        'relatorio_cliente.html',
        resultados=linhas,
        mes=mes, ano=ano,
        usina_id=usina_id, cliente_id=cliente_id,
        usinas=Usina.query.order_by(Usina.nome).all(),
        clientes=Cliente.query.order_by(Cliente.nome).all(),
        totais=totais,
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
        data_referencia = date(ano, mes, 1)

        # Buscar o rateio vigente até essa data
        rateio = Rateio.query.filter(
            Rateio.cliente_id == cliente.id,
            Rateio.usina_id == usina.id,
            Rateio.data_inicio <= data_referencia
        ).order_by(Rateio.data_inicio.desc()).first()

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
    anos_disponiveis = [2024, 2025, 2026]  # pode montar dinamicamente depois se quiser.

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

# lock global para evitar concorrência do Selenium
lock_selenium = globals().get("lock_selenium") or threading.Lock()

# utilitários do Chrome/Selenium

def _running_on_container() -> bool:
    # Render/Docker: binários do Chrome + Chromedriver instalados na imagem
    return Path("/usr/bin/google-chrome").exists() and Path("/usr/bin/chromedriver").exists()

def _chrome_major_linux():
    try:
        out = subprocess.check_output(["/usr/bin/google-chrome", "--version"], text=True).strip()
        return out.split()[-1].split(".")[0]
    except Exception:
        return None

def _build_options(pasta_download: str, em_producao: bool,
                   proxy_url: str | None, user_data_dir: str):
    opts = uc.ChromeOptions()
    opts.add_argument(f"--user-data-dir={user_data_dir}")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-sync")
    opts.add_argument("--disable-translate")
    opts.add_argument("--lang=pt-BR")
    opts.add_argument("--window-size=1366,850")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/139.0.0.0 Safari/537.36")

    # Headless apenas em produção ou se HEADLESS=1
    if em_producao or (os.getenv("HEADLESS", "0") == "1"):
        opts.add_argument("--headless=new")

    if em_producao:
        opts.binary_location = "/usr/bin/google-chrome"

    prefs = {
        "download.default_directory": str(Path(pasta_download).resolve()),
        "plugins.always_open_pdf_externally": True,
        "download.prompt_for_download": False,
    }
    opts.add_experimental_option("prefs", prefs)
    return opts

def _new_driver(pasta_download: str, em_producao: bool, proxy_url: str|None, user_data_dir: str):
    opts = _build_options(pasta_download, em_producao, proxy_url, user_data_dir)

    # APLICA proxy corretamente e captura credenciais (se houver)
    proxy_creds = _apply_proxy_to_options(opts, proxy_url)

    kwargs = {"options": opts, "use_subprocess": True}
    if em_producao or _running_on_container():
        major = _chrome_major_linux()
        if major and major.isdigit():
            kwargs["version_main"] = int(major)
        kwargs["driver_executable_path"] = "/usr/bin/chromedriver"
        kwargs["browser_executable_path"] = "/usr/bin/google-chrome"

    driver = uc.Chrome(**kwargs)

    # Autenticação do proxy via CDP (para HTTP 407)
    _enable_proxy_auth_via_cdp(driver, proxy_creds)

    # (stealth extra opcional) — você já tem
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
              Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
              Object.defineProperty(navigator, 'languages', {get: () => ['pt-BR','pt']});
              Object.defineProperty(navigator, 'platform',  {get: () => 'Win32'});
              window.chrome = { runtime: {} };
            """
        })
    except Exception:
        pass

    return driver

def _hit_home_then_login(driver, URL_HOME, URL_LOGIN):
    """Akamai alivia se você passa pela home antes do login."""
    driver.get(URL_HOME)
    time.sleep(2.5)
    driver.get(URL_LOGIN)

def _apply_proxy_to_options(opts, proxy_url: str | None):
    """
    Configura --proxy-server em formato esquema://host:port e
    retorna (user, pass) se houver credenciais na URL.
    """
    if not proxy_url:
        return None
    u = urlparse(proxy_url)
    if not u.scheme or not u.hostname or not u.port:
        print(f"[PROXY] URL inválida: {proxy_url}")
        return None

    opts.add_argument(f"--proxy-server={u.scheme}://{u.hostname}:{u.port}")
    if u.username or u.password:
        return (u.username or "", u.password or "")
    return None

def _enable_proxy_auth_via_cdp(driver, creds):
    """
    Atende desafios HTTP 407 (proxy) em headless usando CDP.
    Requer undetected_chromedriver.
    """
    if not creds:
        return
    try:
        user, pwd = creds
        driver.execute_cdp_cmd("Fetch.enable", {"handleAuthRequests": True})

        def _on_auth_required(params):
            if params.get("authChallenge", {}).get("isProxy"):
                driver.execute_cdp_cmd("Fetch.continueWithAuth", {
                    "requestId": params["requestId"],
                    "authChallengeResponse": {
                        "response": "ProvideCredentials",
                        "username": user,
                        "password": pwd
                    }
                })
            else:
                driver.execute_cdp_cmd("Fetch.continueRequest", {"requestId": params["requestId"]})

        driver.add_cdp_listener("Fetch.authRequired", _on_auth_required)
    except Exception as e:
        print("[PROXY] Falha ao habilitar auth via CDP:", e)

# Função principal: baixa fatura Neoenergia

def baixar_fatura_neoenergia(cpf_cnpj, senha, codigo_unidade,
                             mes_referencia, pasta_download, api_2captcha):
    em_producao = (os.getenv("RENDER", "0") == "1") or _running_on_container()
    proxy_url = os.getenv("PROXY_URL")  # opcional, recomendado no Render
    print(f"[DEBUG] Ambiente: {'Render' if em_producao else 'Local'}")

    URL_HOME  = "https://agenciavirtual.neoenergiabrasilia.com.br/"
    URL_LOGIN = "https://agenciavirtual.neoenergiabrasilia.com.br/Account/EfetuarLogin"
    SITEKEY = "6LdmOIAbAAAAANXdHAociZWz1gqR9Qvy3AN0rJy4"

    driver = None
    user_data_dir = tempfile.mkdtemp(prefix="selenium_profile_")
    print(f"[DEBUG] Criando perfil temporário: {user_data_dir}")

    try:
        # até 2 tentativas (perfil novo ajuda a derrubar Access Denied)
        for tentativa in (1, 2):
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

            driver = _new_driver(pasta_download, em_producao, proxy_url, user_data_dir)

            print("🌐 Acessando site...")
            _hit_home_then_login(driver, URL_HOME, URL_LOGIN)
            time.sleep(3)

            html = driver.page_source[:1500]
            if "Access Denied" in html or "You don't have permission to access" in html:
                print("⚠️ Access Denied detectado. Recriando perfil...")
                shutil.rmtree(user_data_dir, ignore_errors=True)
                user_data_dir = tempfile.mkdtemp(prefix="selenium_profile_")
                continue

            # -------- login --------
            print("✍️ Preenchendo CPF e senha...")
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='CPF']"))
            ).send_keys(cpf_cnpj)
            driver.find_element(By.CSS_SELECTOR, "input[placeholder='Senha']").send_keys(senha)

            # CAPTCHA 2Captcha
            print("🎯 Enviando CAPTCHA para 2Captcha...")
            resp = requests.get(
                "http://2captcha.com/in.php",
                params={
                    "key": api_2captcha,
                    "method": "userrecaptcha",
                    "googlekey": SITEKEY,
                    "pageurl": URL_LOGIN,
                },
                timeout=30,
            )
            if not resp.text.startswith("OK|"):
                raise Exception(f"Erro ao enviar CAPTCHA: {resp.text}")
            request_id = resp.text.split("|")[1]

            print("⏳ Aguardando solução do CAPTCHA...")
            token = ""
            for _ in range(40):  # ~200s
                time.sleep(5)
                chk = requests.get(
                    "http://2captcha.com/res.php",
                    params={"key": api_2captcha, "action": "get", "id": request_id},
                    timeout=30,
                )
                if chk.text.startswith("OK|"):
                    token = chk.text.split("|")[1]
                    break
                if chk.text not in ("CAPCHA_NOT_READY", "CAPTCHA_NOT_READY"):
                    raise Exception(f"Erro no CAPTCHA: {chk.text}")
            if not token:
                raise Exception("❌ CAPTCHA não resolvido a tempo")

            print("✅ CAPTCHA resolvido!")
            driver.execute_script("""
                var el = document.getElementById('g-recaptcha-response');
                if (el) {
                    el.style.display = 'block';
                    el.value = arguments[0];
                    el.dispatchEvent(new Event('change', {bubbles:true}));
                }
            """, token)
            time.sleep(2)

            print("🚀 Clicando em entrar...")

            # 1) sair de iframes do reCAPTCHA (se houver)
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

            # 2) garantir token no FORM e acionar callbacks do site
            form = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "form[action*='EfetuarLogin'], form#loginForm, form"))
            )
            driver.execute_script("""
                const form = arguments[0], tok = arguments[1];
                let el = form.querySelector('#g-recaptcha-response') || document.getElementById('g-recaptcha-response');
                if (!el) {
                    el = document.createElement('textarea');
                    el.id = 'g-recaptcha-response';
                    el.name = 'g-recaptcha-response';
                    el.style.display = 'none';
                    form.appendChild(el);
                }
                el.value = tok;
                el.dispatchEvent(new Event('change', {bubbles:true}));

                // callbacks comuns que habilitam o submit
                if (typeof window.recaptchaCallback === 'function') { try { window.recaptchaCallback(tok); } catch(e){} }
                if (typeof window.onReCaptchaSuccess === 'function') { try { window.onReCaptchaSuccess(tok); } catch(e){} }
            """, form, token)

            # 3) localizar botão e tentar clique robusto
            btn = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((
                    By.CSS_SELECTOR,
                    "form[action*='EfetuarLogin'] button[type='submit'], form#loginForm button[type='submit'], button[type='submit']"
                ))
            )

            clicked = False
            for _ in range(3):
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                    time.sleep(0.2)
                    btn.click()
                    clicked = True
                    break
                except Exception as e1:
                    print("[CLICK] click() falhou; tentando JS click:", e1)
                    try:
                        driver.execute_script("arguments[0].click();", btn)
                        clicked = True
                        break
                    except Exception as e2:
                        print("[CLICK] JS click falhou:", e2)
                        # remove overlays/desabilitação e tenta novamente
                        driver.execute_script("""
                            try { arguments[0].removeAttribute('disabled'); } catch(e){}
                            document.querySelectorAll('.modal-backdrop,.blockUI,.overlay,.loader,[aria-busy=true]')
                                    .forEach(el => { try{ el.remove(); }catch(e){} });
                        """, btn)
                        time.sleep(0.3)

            if not clicked:
                # 4) fallback: ENTER no campo de senha ou submit do form
                try:
                    pwd = driver.find_element(By.CSS_SELECTOR, "input[type='password'], input[placeholder='Senha']")
                    pwd.send_keys(Keys.ENTER)
                except Exception:
                    driver.execute_script("arguments[0].submit();", form)

            # 5) esperar próxima tela OU erro visível
            try:
                WebDriverWait(driver, 35).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "table#unidades a.btn, table.dataTable a.btn")
                    )
                )
            except TimeoutException:
                # salva HTML/screenshot para depurar
                try:
                    Path("debug").mkdir(exist_ok=True)
                    Path("debug/login_click.html").write_text(driver.page_source, encoding="utf-8")
                    driver.save_screenshot("debug/login_click.png")
                except Exception:
                    pass

                if "Access Denied" in driver.page_source or "permission to access" in driver.page_source:
                    print("⚠️ Access Denied após login. Tentando novo perfil/proxy...")
                    shutil.rmtree(user_data_dir, ignore_errors=True)
                    user_data_dir = tempfile.mkdtemp(prefix="selenium_profile_")
                    continue

                # se houver mensagens de erro de validação, exponha
                msgs = driver.find_elements(
                    By.CSS_SELECTOR, ".alert, .text-danger, .validation-summary-errors, .validation-summary-errors li"
                )
                if msgs:
                    raise Exception(f"Falha no login: {msgs[0].text.strip()}")

                # sem pistas → propaga o timeout
                raise

            # -------- seleção da unidade (match pelo href?codigo=) --------
            print("🔍 Buscando unidade consumidora...")
            alvo = ''.join(filter(str.isdigit, str(codigo_unidade)))  # mantém zeros à esquerda
            print(f"[DEBUG] código alvo normalizado: {alvo}")

            table = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table#unidades, table.dataTable"))
            )
            WebDriverWait(driver, 30).until(
                lambda d: len(table.find_elements(By.CSS_SELECTOR, "tbody a.btn[href*='Menu?codigo=']")) > 0
            )

            links = table.find_elements(By.CSS_SELECTOR, "tbody a.btn[href*='Menu?codigo=']")
            encontrou = False
            vistos = []

            for a in links:
                href = a.get_attribute("href") or ""
                codigo_param = ""
                if "?" in href:
                    from urllib.parse import urlparse, parse_qs
                    q = parse_qs(urlparse(href).query)
                    codigo_param = (q.get("codigo", [""])[0]).strip()
                cand = ''.join(filter(str.isdigit, codigo_param))  # ex.: 030082005
                if cand:
                    vistos.append(cand)
                # ignora dígito verificador: 03008200 casa com 030082005
                if cand.startswith(alvo) or alvo.startswith(cand):
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", a)
                    time.sleep(0.3)
                    driver.execute_script("arguments[0].click();", a)
                    encontrou = True
                    break

            if not encontrou:
                # fallback por texto se mudarem o href
                for a in links:
                    text_digits = ''.join(filter(str.isdigit, a.text or ""))
                    if text_digits.startswith(alvo) or alvo.startswith(text_digits):
                        driver.execute_script("arguments[0].click();", a)
                        encontrou = True
                        break

            if not encontrou:
                print(f"[DEBUG] códigos visíveis: {vistos}")
                raise Exception(f"Unidade consumidora não encontrada (procurado: {alvo}).")

            # -------- histórico e download --------
            print("📄 Acessando histórico de consumo...")
            historico = WebDriverWait(driver, 25).until(
                EC.element_to_be_clickable((By.XPATH, "//a[contains(@href, 'HistoricoConsumo')]"))
            )
            historico.click()

            print("🔍 Procurando fatura...")
            linhas = WebDriverWait(driver, 30).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "tr"))
            )

            for linha in linhas:
                if mes_referencia in linha.text:
                    driver.execute_script("arguments[0].scrollIntoView();", linha)
                    time.sleep(0.8)
                    driver.execute_script("arguments[0].click();", linha)
                    time.sleep(1.6)

                    link = linha.find_element(By.XPATH, ".//a[contains(@href, 'SegundaVia')]")
                    driver.execute_script("arguments[0].click();", link)

                    print("⏬ Aguardando download do PDF...")
                    time.sleep(10)

                    cpf_limpo = ''.join(filter(str.isdigit, cpf_cnpj))
                    subpasta_cpf = Path(pasta_download) / cpf_limpo
                    subpasta_cpf.mkdir(parents=True, exist_ok=True)

                    arquivos_pdf = list(Path(pasta_download).glob("*.pdf"))
                    if not arquivos_pdf:
                        return False, "❌ Nenhum PDF encontrado após clique no link da fatura."

                    ultimo_pdf = max(arquivos_pdf, key=lambda f: f.stat().st_mtime)
                    nome_arquivo = f"fatura_{cpf_limpo}_{codigo_unidade}_{mes_referencia.replace('/', '_')}.pdf"
                    destino = subpasta_cpf / nome_arquivo
                    if destino.exists():
                        destino.unlink()
                    ultimo_pdf.rename(destino)

                    pasta_publica = Path("static/faturas")
                    pasta_publica.mkdir(parents=True, exist_ok=True)
                    publico = pasta_publica / nome_arquivo
                    shutil.copy2(destino, publico)

                    url_pdf = f"/static/faturas/{nome_arquivo}"
                    print(f"✅ PDF disponível em: {url_pdf}")
                    return True, url_pdf

            return False, "❌ Fatura do mês não encontrada."

        # saiu do loop sem sucesso
        return False, "❌ Bloqueio de acesso persistente. Defina PROXY_URL (proxy residencial) e tente novamente."

    except Exception as e:
        print("❌ Erro:", e)
        return False, f"❌ Erro: {e}"

    finally:
        if driver:
            try:
                driver.quit()
            except Exception as e:
                print("[WARNING] Erro ao fechar o driver:", e)
        try:
            shutil.rmtree(user_data_dir, ignore_errors=True)
        except Exception as e:
            print("[WARNING] Erro ao remover user_data_dir:", e)

# ROTA /baixar_fatura (GET/POST)

@app.route("/baixar_fatura", methods=["GET", "POST"])
def baixar_fatura():
    if request.method == "POST":
        # evita concorrência simultânea do Selenium
        if not lock_selenium.acquire(blocking=False):
            flash("⚠️ Já existe uma operação de download em andamento. Tente novamente em alguns segundos.")
            return redirect(url_for("baixar_fatura"))

        try:
            cpf   = request.form["cpf"].strip()
            senha = request.form["senha"].strip()
            codigo = request.form["codigo_unidade"].strip()
            mes    = request.form["mes_referencia"].strip()

            # chave do 2Captcha (use variável de ambiente em produção)
            captcha_key = (os.getenv("CAPTCHA_KEY") or "a8a517df68cc0cf9cf37d8e976d8be33").strip()

            # pasta base para salvar as faturas
            pasta_download = Path("data/boletos").resolve()
            pasta_download.mkdir(parents=True, exist_ok=True)

            sucesso, retorno = baixar_fatura_neoenergia(
                cpf_cnpj=cpf,
                senha=senha,
                codigo_unidade=codigo,
                mes_referencia=mes,
                pasta_download=str(pasta_download),
                api_2captcha=captcha_key,
            )

            if sucesso:
                link = request.host_url.rstrip("/") + retorno
                flash(Markup(
                    f"✅ Fatura baixada com sucesso. "
                    f"<a href='{link}' target='_blank' rel='noopener'>Clique aqui para abrir o PDF</a>"
                ))
            else:
                flash(retorno)

        finally:
            lock_selenium.release()

        return redirect(url_for("baixar_fatura"))

    # GET
    return render_template("form_baixar_fatura.html")

@app.route("/debug_ip")
def debug_ip():
    # evita concorrer com /baixar_fatura
    acquired = lock_selenium.acquire(blocking=False)
    if not acquired:
        return "Outro navegador está em execução. Tente novamente em alguns segundos.", 429

    em_producao = (os.getenv("RENDER", "0") == "1") or _running_on_container()
    proxy_url = os.getenv("PROXY_URL")
    tmp = tempfile.mkdtemp(prefix="selenium_profile_")
    d = None
    last_err = "sem erro"

    try:
        d = _new_driver(str(Path("data/boletos").resolve()), em_producao, proxy_url, tmp)

        # garante que há uma janela/aba ativa
        try:
            handles = d.window_handles
            if not handles:
                d.execute_script("window.open('about:blank','_blank');")
                WebDriverWait(d, 5).until(lambda x: len(x.window_handles) > 0)
            d.switch_to.window(d.window_handles[-1])
        except Exception as e:
            # cria nova aba como fallback
            try:
                d.execute_script("window.open('about:blank','_blank');")
                WebDriverWait(d, 5).until(lambda x: len(x.window_handles) > 0)
                d.switch_to.window(d.window_handles[-1])
            except Exception:
                return f"Erro inicializando aba: {e}", 500

        test_urls = [
            "https://api64.ipify.org?format=text",
            "https://api.ipify.org?format=text",
            "https://ifconfig.me/ip",
            "https://icanhazip.com",
        ]

        ip_txt = None
        for url in test_urls:
            try:
                d.get(url)
                # espera DOM pronto
                WebDriverWait(d, 10).until(
                    lambda x: x.execute_script("return document.readyState") == "complete"
                )
                # lê via JS (mais robusto que find_element)
                ip_txt = d.execute_script(
                    "return (document.body ? document.body.innerText : document.documentElement.innerText) || '';"
                )
                ip_txt = (ip_txt or "").strip()
                if ip_txt:
                    break
            except Exception as e:
                last_err = str(e)
                # se a janela fechou, reabre uma aba e continua
                try:
                    if not d.window_handles:
                        d.execute_script("window.open('about:blank','_blank');")
                        WebDriverWait(d, 5).until(lambda x: len(x.window_handles) > 0)
                        d.switch_to.window(d.window_handles[-1])
                except Exception:
                    pass
                continue

        if not ip_txt:
            return f"Falha ao obter IP. Último erro: {last_err}", 502

        return f"IP visto pelo navegador: {ip_txt}\nProxy: {proxy_url or 'N/A'}", 200

    except Exception as e:
        return f"Erro debug_ip: {e}", 500

    finally:
        try:
            if d:
                d.quit()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
        if acquired:
            lock_selenium.release()

@app.route('/cadastrar_credor', methods=['GET', 'POST'])
@login_required
def cadastrar_credor():
    if not current_user.pode_acessar_financeiro:
        return "Acesso negado", 403

    if request.method == 'POST':
        nome = request.form.get('nome')
        cnpj = request.form.get('cnpj') or None
        endereco = request.form.get('endereco') or None
        telefone = request.form.get('telefone') or None
        email = request.form.get('email') or None

        # Validação para submissões rápidas (via modal)
        if not nome:
            if request.accept_mimetypes.best == 'application/json':
                return jsonify({'erro': 'Nome é obrigatório'}), 400
            flash('Nome é obrigatório', 'danger')
            return redirect(url_for('cadastrar_credor'))

        if cnpj and Credor.query.filter_by(cnpj=cnpj).first():
            if request.accept_mimetypes.best == 'application/json':
                return jsonify({'erro': f'CNPJ {cnpj} já cadastrado'}), 400
            flash(f'O CNPJ {cnpj} já está cadastrado.', 'warning')
            return redirect(url_for('cadastrar_credor'))

        novo = Credor(nome=nome, cnpj=cnpj, endereco=endereco, telefone=telefone, email=email)
        db.session.add(novo)

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            if request.accept_mimetypes.best == 'application/json':
                return jsonify({'erro': 'Erro ao salvar credor. Dados inválidos ou duplicados.'}), 500
            flash('Não foi possível cadastrar o credor. Verifique os dados e tente novamente.', 'danger')
            return redirect(url_for('cadastrar_credor'))

        # ✅ Sucesso
        if request.accept_mimetypes.best == 'application/json':
            return jsonify({'id': novo.id, 'nome': novo.nome})
        flash('Credor cadastrado com sucesso!', 'success')
        return redirect(url_for('listar_credores'))

    return render_template('cadastrar_credor.html')

@app.route('/listar_credores')
@login_required
def listar_credores():
    if not current_user.pode_acessar_financeiro:
        return "Acesso negado", 403

    todos = Credor.query.order_by(Credor.nome).all()
    return render_template('listar_credores.html', credores=todos)

@app.route('/editar_credor/<int:credor_id>', methods=['GET', 'POST'])
@login_required
def editar_credor(credor_id):
    if not current_user.pode_acessar_financeiro:
        abort(403)
    credor = Credor.query.get_or_404(credor_id)

    if request.method == 'POST':
        # Atualiza campos
        credor.nome = request.form['nome']
        credor.cnpj = request.form.get('cnpj') or None
        credor.endereco = request.form.get('endereco') or None
        credor.telefone = request.form.get('telefone') or None
        credor.email = request.form.get('email') or None

        db.session.commit()
        flash(f'Credor “{credor.nome}” atualizado com sucesso.', 'success')
        return redirect(url_for('listar_credores'))

    # GET: exibe formulário pré-preechido
    return render_template('editar_credor.html', credor=credor)

@app.route('/excluir_credor/<int:credor_id>', methods=['POST'])
@login_required
def excluir_credor(credor_id):
    if not current_user.pode_acessar_financeiro:
        abort(403)
    credor = Credor.query.get_or_404(credor_id)

    db.session.delete(credor)
    db.session.commit()
    flash(f'Credor “{credor.nome}” excluído com sucesso.', 'success')
    return redirect(url_for('listar_credores'))

@app.route('/extrato_usina/<int:usina_id>')
@login_required
def extrato_usina(usina_id):
    # permissões
    if not current_user.pode_acessar_financeiro:
        abort(403)

    # parâmetros de filtro
    mes = request.args.get('mes', type=int)
    ano = request.args.get('ano', type=int)
    usina = Usina.query.get_or_404(usina_id)

    # --- Saldo inicial do mês (até o último dia do mês anterior) ---
    # 1º dia do mês corrente
    first_of_month = date(ano, mes, 1)
    # último dia do mês anterior
    prev_month_last = first_of_month - timedelta(days=1)

    # busca todos os registros pagos até prev_month_last
    prev_records = (
        FinanceiroUsina.query
        .filter(
            FinanceiroUsina.usina_id == usina_id,
            FinanceiroUsina.data_pagamento.isnot(None),
            FinanceiroUsina.data_pagamento <= prev_month_last
        )
        .all()
    )

    initial_saldo = Decimal('0')
    for r in prev_records:
        val = Decimal(str(r.valor  or 0))
        j = Decimal(str(r.juros  or 0))
        mov = (val + j) if r.tipo == 'receita' else -val
        initial_saldo += mov

    # --- Movimentações do mês corrente filtradas por data_pagamento ---
    registros = (
        FinanceiroUsina.query
        .options(
            joinedload(FinanceiroUsina.credor),
            joinedload(FinanceiroUsina.categoria)
        )
        .filter(
            FinanceiroUsina.usina_id == usina_id,
            FinanceiroUsina.data_pagamento.isnot(None),
            extract('year', FinanceiroUsina.data_pagamento) == ano,
            extract('month', FinanceiroUsina.data_pagamento) == mes
        )
        .order_by(FinanceiroUsina.data_pagamento)
        .all()
    )

    # --- Monta o extrato dia a dia com saldo acumulado ---
    extrato = []
    saldo_corrente = initial_saldo
    for r in registros:
        val = Decimal(str(r.valor  or 0))
        j = Decimal(str(r.juros  or 0))
        movimento = (val + j) if r.tipo == 'receita' else -val
        saldo_corrente += movimento

        # descrição: em despesa com credor, mostra apenas o nome do credor
        if r.tipo == 'despesa' and r.credor:
            texto = r.credor.nome
        else:
            texto = r.descricao

        extrato.append({
            'data_pagamento': r.data_pagamento,
            'tipo': r.tipo,
            'descricao': texto,
            'valor': movimento,
            'saldo': saldo_corrente
        })

    # renderiza template passando initial_saldo e extrato
    return render_template(
        'extrato_usina.html',
        usina=usina,
        extrato=extrato,
        mes=mes,
        ano=ano,
        initial_saldo=initial_saldo
    )

@app.route('/comprovantes/<path:nome_arquivo>')
@login_required
def visualizar_comprovante(nome_arquivo):
    if not current_user.pode_acessar_financeiro:
        abort(403)

    return send_from_directory(app.config['UPLOAD_FOLDER'], nome_arquivo)

@app.route('/receita_avulsa', methods=['GET', 'POST'])
@login_required
def receita_avulsa():
    usinas = Usina.query.order_by(Usina.nome).all()
    credores = Credor.query.order_by(Credor.nome).all()

    if request.method == 'POST':
        try:
            usina_id = int(request.form['usina_id'])
            data = request.form['data']
            descricao = request.form['descricao']
            valor = float(request.form['valor'])
            referencia_mes = int(request.form['referencia_mes']) if request.form['referencia_mes'] else None
            referencia_ano = int(request.form['referencia_ano']) if request.form['referencia_ano'] else None
            data_pagamento = request.form['data_pagamento'] or None
            credor_id = int(request.form['credor_id']) if request.form['credor_id'] else None

            nova_receita = FinanceiroUsina(
                usina_id=usina_id,
                tipo='receita',
                data=data,
                descricao=descricao,
                valor=valor,
                referencia_mes=referencia_mes,
                referencia_ano=referencia_ano,
                data_pagamento=data_pagamento,
                credor_id=credor_id
            )

            db.session.add(nova_receita)
            db.session.commit()
            flash("✅ Receita cadastrada com sucesso!", "success")
            return redirect(url_for('receita_avulsa'))

        except Exception as e:
            db.session.rollback()
            flash(f"❌ Erro ao cadastrar receita: {e}", "danger")

    return render_template('receita_avulsa.html', usinas=usinas, credores=credores)

@app.route('/editar_receita_avulsa/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_receita_avulsa(id):
    receita = FinanceiroUsina.query.get_or_404(id)

    if receita.tipo != 'receita':
        flash("❌ Registro não é do tipo 'receita'.", "danger")
        return redirect(url_for('relatorio_financeiro'))

    usinas = Usina.query.order_by(Usina.nome).all()
    credores = Credor.query.order_by(Credor.nome).all()

    if request.method == 'POST':
        try:
            receita.usina_id = int(request.form['usina_id'])
            receita.data = request.form['data']
            receita.descricao = request.form['descricao']
            receita.valor = float(request.form['valor'])
            receita.referencia_mes = int(request.form['referencia_mes']) if request.form['referencia_mes'] else None
            receita.referencia_ano = int(request.form['referencia_ano']) if request.form['referencia_ano'] else None
            receita.data_pagamento = request.form['data_pagamento'] or None
            receita.credor_id = int(request.form['credor_id']) if request.form['credor_id'] else None

            db.session.commit()
            flash("✅ Receita atualizada com sucesso!", "success")
            return redirect(url_for('editar_receita_avulsa', id=receita.id))
        except Exception as e:
            db.session.rollback()
            flash(f"❌ Erro ao atualizar receita: {e}", "danger")

    return render_template('receita_avulsa.html', receita=receita, usinas=usinas, credores=credores)

@app.route('/receitas_avulsas')
@login_required
def receitas_avulsas():
    if not current_user.pode_acessar_financeiro:
        return "Acesso negado", 403

    usinas = Usina.query.order_by(Usina.nome).all()
    usina_id = request.args.get('usina_id', type=int)
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')

    query = FinanceiroUsina.query.filter(
        FinanceiroUsina.tipo == 'receita',
        ~func.lower(FinanceiroUsina.descricao).like('fatura%')  # exclui descrições que começam com "fatura"
    )

    if usina_id:
        query = query.filter(FinanceiroUsina.usina_id == usina_id)
    if data_inicio:
        query = query.filter(FinanceiroUsina.data >= data_inicio)
    if data_fim:
        query = query.filter(FinanceiroUsina.data <= data_fim)

    receitas = query.order_by(FinanceiroUsina.data.desc()).all()

    return render_template('receitas_avulsas.html', receitas=receitas, usinas=usinas,
                           usina_id=usina_id, data_inicio=data_inicio, data_fim=data_fim)

@app.route('/excluir_receita_avulsa/<int:id>', methods=['POST'])
@login_required
def excluir_receita_avulsa(id):
    receita = FinanceiroUsina.query.get_or_404(id)
    if receita.tipo != 'receita':
        flash('Registro não é uma receita.', 'danger')
        return redirect(url_for('receitas_avulsas'))

    db.session.delete(receita)
    db.session.commit()
    flash('Receita excluída com sucesso.', 'success')
    return redirect(url_for('receitas_avulsas'))

def calcular_distribuicao_direta(usina, valor_total):
    distribuicoes = []
    for participacao in usina.participacoes_diretas:
        valor = valor_total * (participacao.percentual / 100)
        distribuicoes.append({
            'acionista': participacao.acionista.nome,
            'percentual': participacao.percentual,
            'valor': valor
        })
    return distribuicoes

@app.route('/participacao_direta', methods=['GET', 'POST'])
@login_required
def participacao_direta():
    usinas = Usina.query.order_by(Usina.nome).all()
    acionistas = Acionista.query.order_by(Acionista.nome).all()

    if request.method == 'POST':
        usina_id = request.form.get('usina_id', type=int)
        acionista_id = request.form.get('acionista_id', type=int)
        percentual = request.form.get('percentual', type=float)

        if not (usina_id and acionista_id and percentual):
            flash('Todos os campos são obrigatórios.', 'danger')
            return redirect(url_for('participacao_direta'))

        nova_participacao = ParticipacaoAcionistaDireta(
            usina_id=usina_id,
            acionista_id=acionista_id,
            percentual=percentual
        )

        db.session.add(nova_participacao)
        db.session.commit()
        flash('Participação direta cadastrada com sucesso!', 'success')
        return redirect(url_for('participacao_direta'))

    participacoes = ParticipacaoAcionistaDireta.query.join(Usina).join(Acionista).order_by(Usina.nome).all()
    return render_template('participacao_direta.html', usinas=usinas, acionistas=acionistas, participacoes=participacoes)

@app.route('/distribuicao_lucro_direta', methods=['GET', 'POST'])
@login_required
def distribuicao_lucro_direta():
    usinas_sem_empresa = Usina.query.outerjoin(UsinaInvestidora).filter(UsinaInvestidora.id == None).all()
    anos = list(range(2022, date.today().year + 1))

    if request.method == 'POST':
        usina_id = int(request.form['usina_id'])
        mes = int(request.form['mes'])
        ano = int(request.form['ano'])
        return redirect(url_for('distribuicao_lucro_direta_resultado', usina_id=usina_id, mes=mes, ano=ano))

    return render_template('form_distribuicao_lucro_direta.html', usinas=usinas_sem_empresa, anos=anos)

def calcular_lucro_usina(usina_id, mes, ano):
    receitas = db.session.query(func.sum(FinanceiroUsina.valor)).filter_by(
        usina_id=usina_id,
        tipo='receita',
        referencia_mes=mes,
        referencia_ano=ano
    ).scalar() or 0

    despesas = db.session.query(func.sum(FinanceiroUsina.valor)).filter_by(
        usina_id=usina_id,
        tipo='despesa',
        referencia_mes=mes,
        referencia_ano=ano
    ).scalar() or 0

    return round(receitas - despesas, 2)

@app.route('/distribuicao_lucro_direta_resultado')
@login_required
def distribuicao_lucro_direta_resultado():
    usina_id = request.args.get('usina_id', type=int)
    mes = request.args.get('mes', type=int)
    ano = request.args.get('ano', type=int)

    usina = Usina.query.get_or_404(usina_id)
    participacoes = ParticipacaoAcionistaDireta.query.filter_by(usina_id=usina_id).all()

    # Substitua pela sua lógica real de lucro
    lucro_total = calcular_lucro_usina(usina_id, mes, ano)

    distribuicoes = []
    for p in participacoes:
        valor = lucro_total * (p.percentual / 100)
        distribuicoes.append({
            'acionista': p.acionista.nome,
            'percentual': p.percentual,
            'valor': valor
        })

    return render_template(
        'resultado_distribuicao_direta.html',
        usina=usina,
        mes=mes,
        ano=ano,
        lucro_total=lucro_total,
        distribuicoes=distribuicoes
    )
    
# Rota e formulário para cadastrar participação direta
@app.route('/cadastrar_participacao_direta', methods=['GET', 'POST'])
@login_required
def cadastrar_participacao_direta():
    usinas = Usina.query.order_by(Usina.nome).all()
    acionistas = Acionista.query.order_by(Acionista.nome).all()

    if request.method == 'POST':
        usina_id = int(request.form['usina_id'])
        acionista_id = int(request.form['acionista_id'])
        percentual = float(request.form['percentual'])

        participacao = ParticipacaoAcionistaDireta(
            usina_id=usina_id,
            acionista_id=acionista_id,
            percentual=percentual
        )
        db.session.add(participacao)
        db.session.commit()
        flash("Participação cadastrada com sucesso!", "success")
        return redirect(url_for('cadastrar_participacao_direta'))

    return render_template('cadastrar_participacao_direta.html', usinas=usinas, acionistas=acionistas)

@app.route('/participacoes_diretas')
@login_required
def listar_participacoes_diretas():
    participacoes = ParticipacaoAcionistaDireta.query.join(Usina).join(Acionista).all()
    return render_template('listar_participacoes_diretas.html', participacoes=participacoes)

@app.route('/participacoes_diretas/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_participacao_direta(id):
    participacao = ParticipacaoAcionistaDireta.query.get_or_404(id)

    if request.method == 'POST':
        participacao.percentual = request.form['percentual']
        db.session.commit()
        flash("Participação atualizada com sucesso!", "success")
        return redirect(url_for('listar_participacoes_diretas'))

    return render_template('editar_participacao_direta.html', participacao=participacao)

@app.route('/participacoes_diretas/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_participacao_direta(id):
    participacao = ParticipacaoAcionistaDireta.query.get_or_404(id)
    db.session.delete(participacao)
    db.session.commit()
    flash("Participação removida com sucesso.", "success")
    return redirect(url_for('listar_participacoes_diretas'))

@app.route('/relatorio_prestacao_direta', methods=['GET'])
@login_required
def relatorio_prestacao_direta():
    usinas = Usina.query.order_by(Usina.nome).all()
    usina_id = request.args.get('usina_id', type=int)
    mes = request.args.get('mes', type=int)
    ano = request.args.get('ano', type=int) or datetime.today().year
    relatorio = None

    if usina_id:
        usina = Usina.query.get(usina_id)

        previsto = sum(p.previsao_kwh for p in usina.previsoes if (not mes or p.mes == mes) and p.ano == ano)
        realizado = sum(g.energia_kwh for g in usina.geracoes if (not mes or g.data.month == mes) and g.data.year == ano)
        eficiencia = round((realizado / previsto * 100), 2) if previsto else 0

        # fluxo financeiro
        fluxo = []
        receitas = despesas = 0
        for f in usina.financeiros:
            if (not mes or f.referencia_mes == mes) and f.referencia_ano == ano:
                if f.tipo == 'receita':
                    receitas += f.valor
                    fluxo.append({'data': f.data, 'descricao': f.descricao, 'credito': f.valor, 'debito': 0})
                elif f.tipo == 'despesa':
                    despesas += f.valor
                    fluxo.append({'data': f.data, 'descricao': f.descricao, 'credito': 0, 'debito': f.valor})

        liquido = receitas - despesas

        distribuicao = []
        participacoes = ParticipacaoAcionistaDireta.query.filter_by(usina_id=usina_id).all()
        for p in participacoes:
            valor = round(liquido * (p.percentual / 100), 2)
            distribuicao.append({
                'acionista': p.acionista.nome,
                'percentual': p.percentual,
                'valor': valor
            })

        # yield cálculo
        dias_no_mes = calendar.monthrange(ano, mes or 1)[1]
        dias_validos = len([
            g for g in usina.geracoes if g.data.month == mes and g.data.year == ano and g.energia_kwh > 0
        ])
        soma_total = sum(
            g.energia_kwh for g in usina.geracoes if g.data.month == mes and g.data.year == ano
        )
        potencia_kw = usina.potencia_kw or 0
        yield_kwp = round(soma_total / (dias_validos * (potencia_kw / dias_no_mes)), 2) if potencia_kw and dias_validos else None

        relatorio = {
            'usina': usina,
            'previsto': previsto,
            'realizado': realizado,
            'eficiencia': eficiencia,
            'fluxo': fluxo,
            'distribuicao': distribuicao,
            'yield_kwp': yield_kwp
        }

    return render_template('relatorio_prestacao_direta.html',
                           usinas=usinas,
                           usina_id=usina_id,
                           relatorio=relatorio,
                           mes=mes,
                           ano=ano,
                           ano_atual=datetime.today().year)

@app.route('/cadastrar_injecao', methods=['GET', 'POST'])
@login_required
def cadastrar_injecao():
    usinas = Usina.query.order_by(Usina.nome).all()
    ano_atual = datetime.now().year

    if request.method == 'POST':
        usina_id = request.form.get('usina_id', type=int)
        ano = request.form.get('ano', type=int)
        mes = request.form.get('mes', type=int)
        kwh_injetado = request.form.get('kwh_injetado', type=float)

        existente = InjecaoMensalUsina.query.filter_by(
            usina_id=usina_id, ano=ano, mes=mes
        ).first()
        if existente:
            flash('❌ Já existe um registro para esta usina nesse mês/ano.', 'danger')
            return redirect(url_for('cadastrar_injecao'))

        nova = InjecaoMensalUsina(
            usina_id=usina_id,
            ano=ano,
            mes=mes,
            kwh_injetado=kwh_injetado
        )
        db.session.add(nova)
        db.session.commit()
        flash('✅ Injeção cadastrada com sucesso.', 'success')
        return redirect(url_for('cadastrar_injecao'))

    return render_template('cadastrar_injecao.html', usinas=usinas, ano_atual=ano_atual)

@app.route('/relatorio_financeiro_com_perda', methods=['GET'])
@login_required
def relatorio_financeiro_com_perda():
    if not current_user.pode_acessar_financeiro:
        return "Acesso negado", 403

    usina_id = request.args.get('usina_id', type=int)
    mes_inicio = request.args.get('mes_inicio', type=int, default=1)
    ano_inicio = request.args.get('ano_inicio', type=int, default=datetime.now().year)
    mes_fim = request.args.get('mes_fim', type=int, default=datetime.now().month)
    ano_fim = request.args.get('ano_fim', type=int, default=datetime.now().year)

    data_inicio = datetime(ano_inicio, mes_inicio, 1)
    data_fim = datetime(ano_fim, mes_fim, 28)

    # limites para o filtro de data_pagamento
    janela_inicio = datetime(ano_inicio, mes_inicio, 1)
    janela_fim_exclusivo = datetime(ano_fim, mes_fim, 1) + relativedelta(months=1)

    # carrega usinas e anos
    usinas = Usina.query.order_by(Usina.nome).all()
    anos_disponiveis = sorted({
        r[0] for r in db.session.query(db.extract('year', Geracao.data)).distinct().all()
    }, reverse=True)

    # guarda o saldo original de cada usina
    saldos_originais = {u.id: float(u.saldo_kwh or 0) for u in usinas}
    dados = []
    usinas_filtradas = [u for u in usinas if not usina_id or u.id == usina_id]

    # monta a lista mês a mês
    for usina in usinas_filtradas:
        faturado_acumulado = 0.0
        data_atual = data_inicio

        while data_atual <= data_fim:
            mes, ano = data_atual.month, data_atual.year
            
            # Calcula mês e ano anteriores
            if mes == 1:
                mes_anterior = 12
                ano_anterior = ano - 2
            else:
                mes_anterior = mes - 2
                ano_anterior = ano

            # geração
            geracao = db.session.query(func.sum(Geracao.energia_kwh)).filter(
                Geracao.usina_id == usina.id,
                func.extract('month', Geracao.data) == mes_anterior,
                func.extract('year', Geracao.data) == ano_anterior
            ).scalar() or 0
            if geracao is None or (isinstance(geracao, float) and math.isnan(geracao)):
                geracao = 0

            # injeção
            injecao = db.session.query(func.sum(InjecaoMensalUsina.kwh_injetado)).filter(
                InjecaoMensalUsina.usina_id == usina.id,
                InjecaoMensalUsina.mes == mes,
                InjecaoMensalUsina.ano == ano
            ).scalar() or 0

            # consumo
            consumo = db.session.query(func.sum(FaturaMensal.consumo_usina)) \
                .join(Cliente, Cliente.id == FaturaMensal.cliente_id) \
                .filter(
                    Cliente.usina_id == usina.id,
                    FaturaMensal.mes_referencia == mes,
                    FaturaMensal.ano_referencia == ano
                ).scalar() or 0

            # faturado R$ do mês anterior (com base na referência)
            faturado = db.session.query(
                func.sum(FinanceiroUsina.valor + func.coalesce(FinanceiroUsina.juros, 0))
            ).filter(
                FinanceiroUsina.usina_id == usina.id,
                FinanceiroUsina.tipo == 'receita',
                FinanceiroUsina.referencia_mes == mes,
                FinanceiroUsina.referencia_ano == ano
            ).scalar() or 0
            faturado_acumulado += float(faturado)

            # saldo unidade
            saldo_unidade = db.session.query(func.sum(FaturaMensal.saldo_unidade)).join(Cliente).filter(
                Cliente.usina_id == usina.id,
                FaturaMensal.mes_referencia == mes,
                FaturaMensal.ano_referencia == ano
            ).scalar() or 0

            perda = geracao - injecao if injecao > 0 else 0

            dados.append({
                'mes': mes,
                'ano': ano,
                'usina_nome': usina.nome,
                'geracao': round(geracao, 2),
                'injecao': round(injecao, 2),
                'perda': round(perda, 2),
                'consumo': round(consumo, 2),
                'saldo_unidade': round(saldo_unidade, 2),
                'faturado': round(faturado, 2),
                'faturado_acumulado': round(faturado_acumulado, 2),
            })

            data_atual += relativedelta(months=1)

    # — Consolidação —
    consolidacao = []
    for usina in usinas_filtradas:
        ger_total = sum(d['geracao'] for d in dados if d['usina_nome'] == usina.nome)
        inj_total = sum(d['injecao'] for d in dados if d['usina_nome'] == usina.nome)
        perda_bruta = sum(d['perda'] for d in dados if d['usina_nome'] == usina.nome)
        saldo_kwh_orig = saldos_originais[usina.id]
        perda_liquida = perda_bruta - saldo_kwh_orig

        # faturado_total agora baseado em data_pagamento (R$ realmente pagos)
        fat_total = db.session.query(
            func.coalesce(func.sum(FinanceiroUsina.valor + func.coalesce(FinanceiroUsina.juros, 0)), 0.0)
        ).filter(
            FinanceiroUsina.usina_id == usina.id,
            FinanceiroUsina.tipo == 'receita',
            FinanceiroUsina.data_pagamento >= janela_inicio,
            FinanceiroUsina.data_pagamento < janela_fim_exclusivo
        ).scalar() or 0.0
        fat_total = float(fat_total)

        # eficiência e payback
        previsao_total = db.session.query(func.sum(PrevisaoMensal.previsao_kwh)).filter(
            PrevisaoMensal.usina_id == usina.id,
            or_(
                and_(PrevisaoMensal.ano == ano_inicio, PrevisaoMensal.mes >= mes_inicio),
                and_(PrevisaoMensal.ano == ano_fim, PrevisaoMensal.mes <= mes_fim),
                and_(PrevisaoMensal.ano > ano_inicio, PrevisaoMensal.ano < ano_fim)
            )
        ).scalar() or 0
        eficiencia = (ger_total / previsao_total * 100) if previsao_total else 0

        ultima_rateio = Rateio.query.filter_by(usina_id=usina.id).order_by(Rateio.id.desc()).first()
        tarifa_kwh = float(ultima_rateio.tarifa_kwh) if ultima_rateio else 0

        investimento = float(usina.valor_investido or 0)
        meses_validos = sum(1 for d in dados if d['usina_nome'] == usina.nome and d['faturado'] > 0)
        media_mensal = (fat_total / meses_validos) if meses_validos else 0
        meses_payback = (investimento / media_mensal) if media_mensal else 0

        linhas = [d for d in dados if d['usina_nome'] == usina.nome]
        credito_unidades = linhas[-1]['saldo_unidade'] if linhas else 0
        payback_pct = ((saldo_kwh_orig + credito_unidades) * tarifa_kwh + fat_total) / investimento * 100 if investimento else 0

        consolidacao.append({
            'usina_nome': usina.nome,
            'geracao_total': round(ger_total, 2),
            'injecao_total': round(inj_total, 2),
            'perda_total': round(perda_liquida, 2),
            'saldo_kwh': round(saldo_kwh_orig, 2),
            'ultimo_saldo': round(credito_unidades, 2),
            'faturado_total': round(fat_total, 2),   # << usado no template
            'payback_percentual': round(payback_pct, 2),
            'meses_payback': round(meses_payback, 1),
            'eficiencia': round(eficiencia, 2),
        })

    return render_template(
        'relatorio_financeiro_com_perda.html',
        relatorio=dados,
        consolidacao=consolidacao,
        usinas=usinas,
        usina_id=usina_id,
        anos_disponiveis=anos_disponiveis,
        mes_inicio=mes_inicio,
        ano_inicio=ano_inicio,
        mes_fim=mes_fim,
        ano_fim=ano_fim
    )
    
@app.route("/injecoes_mensais")
@login_required
def listar_injecoes_mensais():
    page = request.args.get("page", 1, type=int)
    usina_id = request.args.get("usina_id", type=int)
    ano = request.args.get("ano", type=int)

    query = InjecaoMensalUsina.query
    if usina_id:
        query = query.filter(InjecaoMensalUsina.usina_id == usina_id)
    if ano:
        query = query.filter(InjecaoMensalUsina.ano == ano)

    query = query.order_by(
        InjecaoMensalUsina.ano.desc(),
        InjecaoMensalUsina.mes.desc(),
        InjecaoMensalUsina.usina_id.asc()
    )

    paginacao = query.paginate(page=page, per_page=20, error_out=False)

    usinas = Usina.query.order_by(Usina.nome).all()
    anos_disponiveis = sorted(
        {r[0] for r in db.session.query(InjecaoMensalUsina.ano).distinct()},
        reverse=True
    )

    return render_template(
        "listar_injecoes_usina.html", 
        paginacao=paginacao,
        itens=paginacao.items,
        usinas=usinas,
        anos_disponiveis=anos_disponiveis,
        usina_id=usina_id,
        ano=ano,
    )


@app.route("/injecoes_mensais/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
def editar_injecao_mensal(item_id):
    item = InjecaoMensalUsina.query.get_or_404(item_id)
    usinas = Usina.query.order_by(Usina.nome).all()

    if request.method == "POST":
        try:
            item.usina_id = request.form.get("usina_id", type=int)
            item.ano = request.form.get("ano", type=int)
            item.mes = request.form.get("mes", type=int)
            item.kwh_injetado = request.form.get("kwh_injetado", type=float)

            db.session.commit()
            flash("Injeção mensal atualizada com sucesso.", "success")

            return redirect(url_for(
                "listar_injecoes_mensais",
                usina_id=request.args.get("usina_id"),
                ano=request.args.get("ano")
            ))
        except IntegrityError:
            db.session.rollback()
            flash("Já existe registro para essa combinação Usina/Ano/Mês.", "danger")
        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao salvar: {e}", "danger")

    return render_template("editar_injecao_usina.html", item=item, usinas=usinas)


@app.route("/injecoes_mensais/<int:item_id>/excluir", methods=["POST"])
@login_required
def excluir_injecao_mensal(item_id):
    item = InjecaoMensalUsina.query.get_or_404(item_id)

    try:
        db.session.delete(item)
        db.session.commit()
        flash("Registro excluído com sucesso.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao excluir: {e}", "danger")

    return redirect(url_for(
        "listar_injecoes_mensais", 
        usina_id=request.args.get("usina_id"),
        ano=request.args.get("ano")
    ))
    
@app.route("/deye")
def deye():
    # --- Config ---
    URL_BASE = "https://us1-developer.deyecloud.com"
    APP_ID   = os.getenv("DEYE_APP_ID", "202507084069006")
    APP_CHAVE = os.getenv("DEYE_APP_SECRET", "c5e239738a63d1c614e6603f8246a66b")
    USUARIO  = os.getenv("DEYE_EMAIL_OR_USER", "monitoramento@cgrenergia.com.br")
    SENHA    = os.getenv("DEYE_PASSWORD_PLAIN", "Cgr@2020")

    def sha256_texto(txt: str) -> str:
        return hashlib.sha256(txt.encode("utf-8")).hexdigest()

    # --- Token pessoal ---
    corpo = {"appSecret": APP_CHAVE, "email": USUARIO, "password": sha256_texto(SENHA)}
    resp = requests.post(f"{URL_BASE}/v1.0/account/token?appId={APP_ID}", json=corpo, timeout=30).json()
    token = resp.get("accessToken")

    # --- Buscar ID da empresa (se existir) ---
    info = requests.post(f"{URL_BASE}/v1.0/account/info", json={}, headers={"Authorization": f"bearer {token}"}, timeout=30).json()
    orgs = info.get("orgInfoList") or []
    if orgs:
        empresa_id = str(orgs[0]["companyId"])
        corpo = {"appSecret": APP_CHAVE, "email": USUARIO, "password": sha256_texto(SENHA), "companyId": empresa_id}
        resp = requests.post(f"{URL_BASE}/v1.0/account/token?appId={APP_ID}", json=corpo, timeout=30).json()
        token = resp.get("accessToken")

    # --- Listar estações ---
    dados = requests.post(f"{URL_BASE}/v1.0/station/list",
                          json={"page": 1, "size": 20},
                          headers={"Authorization": f"bearer {token}"}, timeout=30).json()
    estacoes = dados.get("stationList", [])

    return render_template("deye.html", estacoes=estacoes)

@app.route('/monitoramento/usina/<int:usina_id>', methods=['GET', 'POST'])
@login_required
def monitoramento_usina(usina_id):
    usina = Usina.query.get_or_404(usina_id)

    # --------------------- Helpers ---------------------
    def _parse_date(s, fallback=None):
        if not s:
            return fallback
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            return fallback

    def _to_float(v):
        if v is None or str(v).strip() == '':
            return None
        try:
            return float(str(v).replace(',', '.'))
        except ValueError:
            return None

    def _norm_sn_py(sn: str) -> str:
        # Upper + remove -, _ e espaço
        s = (sn or '').strip().upper()
        return s.replace('-', '').replace('_', '').replace(' ', '')

    def _norm_sn_sql(col):
        # Postgres: UPPER(regexp_replace(trim(col), '[-_ ]', '', 'g'))
        return func.upper(func.regexp_replace(func.trim(col), '[-_ ]', '', 'g'))

    # --------------------- Inversores ativos ---------------------
    inversores = (InversorCadastrado.query
                  .filter_by(usina_id=usina_id, ativo=True)
                  .order_by(InversorCadastrado.nome.asc().nullslast(),
                            InversorCadastrado.inverter_sn.asc())
                  .all())

    # --------------------- POST ---------------------
    if request.method == 'POST':
        action = request.form.get('action')

        # 1) Cadastro/atualização rápida do inversor
        if action == 'cad_inversor':
            inverter_sn_raw = (request.form.get('inverter_sn') or '')
            inverter_sn = _norm_sn_py(inverter_sn_raw)
            nome = (request.form.get('nome') or '').strip()
            potencia_kw = _to_float(request.form.get('potencia_kw'))

            if not inverter_sn:
                flash('Informe o Serial (inverter_sn).', 'warning')
                return redirect(url_for('monitoramento_usina', usina_id=usina_id))

            inv = (InversorCadastrado.query
                   .filter_by(usina_id=usina_id, inverter_sn=inverter_sn)
                   .first())
            if not inv:
                inv = InversorCadastrado(
                    usina_id=usina_id,
                    inverter_sn=inverter_sn,
                    nome=nome or None,
                    potencia_kw=potencia_kw,
                    ativo=True
                )
                db.session.add(inv)
            else:
                inv.nome = nome or inv.nome
                if potencia_kw is not None:
                    inv.potencia_kw = potencia_kw
                inv.ativo = True

            # Vinculação retroativa por SN normalizado
            norm_val = _norm_sn_py(inverter_sn)
            (GeracaoInversor.query
             .filter(
                 GeracaoInversor.usina_id == usina_id,
                 _norm_sn_sql(GeracaoInversor.inverter_sn) == _norm_sn_sql(literal(norm_val)),
                 or_(GeracaoInversor.inversor_id.is_(None),
                     GeracaoInversor.inversor_id != inv.id)
             )
             .update({'inversor_id': inv.id,
                      'inverter_sn': inverter_sn}, synchronize_session=False))

            db.session.commit()
            flash('Inversor cadastrado/atualizado e gerações vinculadas por SN.', 'success')
            return redirect(url_for('monitoramento_usina', usina_id=usina_id))

        # 2) Lançamento diário do monitoramento (um registro por dia por SN nesta tela)
        if action == 'salvar_monitoramento':
            raw_sn = (request.form.get('inverter_sn') or '').strip()
            if not raw_sn:
                flash('Selecione um inversor cadastrado.', 'warning')
                return redirect(url_for('monitoramento_usina', usina_id=usina_id))

            inverter_sn = _norm_sn_py(raw_sn)
            data_ref = _parse_date(request.form.get('data'), date.today())

            etoday = _to_float(request.form.get('etoday'))
            online = request.form.get('online') == 'on'
            comunicando = request.form.get('comunicando') == 'on'
            mensagem_erro = (request.form.get('mensagem_erro') or '').strip() or None

            inv = (InversorCadastrado.query
                   .filter_by(usina_id=usina_id, inverter_sn=inverter_sn, ativo=True)
                   .first())

            # UPSERT Monitoramento (1/dia por SN nesta tela)
            reg = (Monitoramento.query
                   .filter_by(usina_id=usina_id, inverter_sn=inverter_sn, data=data_ref)
                   .first())
            if not reg:
                reg = Monitoramento(usina_id=usina_id,
                                    inverter_sn=inverter_sn,
                                    data=data_ref)
                db.session.add(reg)

            reg.etoday = etoday
            reg.online = online
            reg.comunicando = comunicando
            reg.mensagem_erro = mensagem_erro
            if inv and inv.potencia_kw is not None:
                reg.potencia_kw = inv.potencia_kw

            # Vincular/espelhar em GeracaoInversor
            gi = (GeracaoInversor.query
                  .filter_by(usina_id=usina_id, inverter_sn=inverter_sn, data=data_ref)
                  .first())
            if gi is None:
                gi = GeracaoInversor(
                    usina_id=usina_id,
                    inverter_sn=inverter_sn,
                    data=data_ref,
                    etoday=etoday
                )
                db.session.add(gi)
            else:
                if etoday is not None:
                    gi.etoday = etoday

            if inv:
                gi.inversor_id = inv.id
                norm_val = _norm_sn_py(inverter_sn)
                (GeracaoInversor.query
                 .filter(
                     GeracaoInversor.usina_id == usina_id,
                     _norm_sn_sql(GeracaoInversor.inverter_sn) == _norm_sn_sql(literal(norm_val)),
                     or_(GeracaoInversor.inversor_id.is_(None),
                         GeracaoInversor.inversor_id != inv.id)
                 )
                 .update({'inversor_id': inv.id,
                          'inverter_sn': inverter_sn}, synchronize_session=False))

            db.session.commit()
            flash('Monitoramento salvo e gerações vinculadas por SN.', 'success')

            # preserva filtros principais no redirect
            return redirect(url_for('monitoramento_usina',
                                    usina_id=usina_id,
                                    view=request.args.get('view', 'ultimos'),
                                    data=request.args.get('data', ''),
                                    data_tab=request.args.get('data_tab', ''),
                                    data_ini=request.args.get('data_ini', ''),
                                    data_fim=request.args.get('data_fim', '')))

    # --------------------- GET: filtros/visões ---------------------
    view = request.args.get('view', 'ultimos')  # 'ultimos' | 'diario'
    data_ref = _parse_date(request.args.get('data'), date.today())

    # TABELA do topo (filtro independente)
    data_tab_ref = _parse_date(request.args.get('data_tab'), date.today())

    # Registros do topo (do dia específico) - mais recente primeiro por SN
    registros_tab = (Monitoramento.query
        .filter(Monitoramento.usina_id == usina_id,
                Monitoramento.data == data_tab_ref)
        .order_by(Monitoramento.inverter_sn.asc(),
                  Monitoramento.id.desc())  # último inserido primeiro
        .all())

    # Histórico e mais recente por SN (em memória)
    historico_por_sn = {}
    latest_por_sn = {}
    for r in registros_tab:
        historico_por_sn.setdefault(r.inverter_sn, []).append(r)
        if r.inverter_sn not in latest_por_sn:
            latest_por_sn[r.inverter_sn] = r  # já é o mais recente nessa ordenação

    # ========= MAIS RECENTE por SN NO DIA (via subselect max(id)) =========
    sub_ult_por_id = (db.session.query(
                        Monitoramento.inverter_sn.label('sn'),
                        func.max(Monitoramento.id).label('max_id')
                     )
                     .filter(Monitoramento.usina_id == usina_id,
                             Monitoramento.data == data_tab_ref)
                     .group_by(Monitoramento.inverter_sn)
                     .subquery())

    latest_rows = (db.session.query(Monitoramento.id, Monitoramento.inverter_sn)
                   .join(sub_ult_por_id,
                         and_(Monitoramento.inverter_sn == sub_ult_por_id.c.sn,
                              Monitoramento.id == sub_ult_por_id.c.max_id))
                   .filter(Monitoramento.usina_id == usina_id,
                           Monitoramento.data == data_tab_ref)
                   .all())

    # IDs atuais (1 por SN)
    latest_ids = {row.id for row in latest_rows}
    
    # Pega, para cada SN, o primeiro etoday não-nulo do dia (ordem: mais recente -> mais antigo)
    latest_etoday_por_sn = {}
    for sn, lst in historico_por_sn.items():  # lst já está em ordem decrescente (id desc)
        val = next((x.etoday for x in lst if x.etoday is not None), None)
        latest_etoday_por_sn[sn] = val

    # --- ordenação: primeiro os "atuais", depois os "antigos" ---
    atuais = [r for r in registros_tab if r.id in latest_ids]
    antigos = [r for r in registros_tab if r.id not in latest_ids]

    # dentro de cada grupo, ordena por eToday (desc), depois None
    atuais_sorted = sorted(atuais, key=lambda r: (r.etoday is None, -(r.etoday or 0.0)))
    antigos_sorted = sorted(antigos, key=lambda r: (r.etoday is None, -(r.etoday or 0.0)))

    registros_tab_sorted = atuais_sorted + antigos_sorted

    # --- índice da usina no dia (apenas snapshots atuais por SN) ---
    peso_com, peso_onl, peso_prod = 0.40, 0.40, 0.20
    atuais = [r for r in registros_tab if r.id in latest_ids]
    n = len(atuais)
    score_sum = 0.0
    for r in atuais:
        etoday_eff = latest_etoday_por_sn.get(r.inverter_sn)  # <- usa o valor efetivo do dia
        s  = peso_com * (1.0 if bool(getattr(r, 'comunicando', False)) else 0.0)
        s += peso_onl  * (1.0 if bool(getattr(r, 'online', False))       else 0.0)
        s += peso_prod * (1.0 if ((etoday_eff or 0.0) > 0) else 0.0)
        score_sum += s
    indice_usina_pct = round(100.0 * (score_sum / n), 1) if n else 0.0

    # Visão "diário" ou "últimos" (cards + tabela principal)
    if view == 'diario':
        registros = (Monitoramento.query
                     .filter(Monitoramento.usina_id == usina_id,
                             Monitoramento.data == data_ref)
                     .order_by(Monitoramento.inverter_sn.asc())
                     .all())
    else:
        sub_ult = (db.session.query(
                        Monitoramento.inverter_sn,
                        func.max(Monitoramento.data).label('max_data')
                   )
                   .filter(Monitoramento.usina_id == usina_id)
                   .group_by(Monitoramento.inverter_sn)
                   .subquery())
        registros = (db.session.query(Monitoramento)
                     .join(sub_ult, and_(
                         Monitoramento.inverter_sn == sub_ult.c.inverter_sn,
                         Monitoramento.data == sub_ult.c.max_data
                     ))
                     .filter(Monitoramento.usina_id == usina_id)
                     .order_by(Monitoramento.inverter_sn.asc())
                     .all())

    total = len(inversores)
    online_cnt = sum(1 for r in registros if bool(getattr(r, 'online', False)))
    comunicando_cnt = sum(1 for r in registros if bool(getattr(r, 'comunicando', False)))

    # --------------------- Gráficos / Comparação ---------------------
    data_ini = _parse_date(request.args.get('data_ini'), data_ref)
    data_fim = _parse_date(request.args.get('data_fim'), data_ref)
    if data_ini > data_fim:
        data_ini, data_fim = data_fim, data_ini

    inv_sns = request.args.getlist('inv')
    if not inv_sns:
        inv_sns = [i.inverter_sn for i in inversores]

    def daterange(d1, d2):
        cur = d1
        while cur <= d2:
            yield cur
            cur += timedelta(days=1)

    labels_datas = [d for d in daterange(data_ini, data_fim)]
    labels_fmt = [d.strftime('%d/%m') for d in labels_datas]

    mon_periodo = []
    if inv_sns:
        mon_periodo = (Monitoramento.query
                       .filter(Monitoramento.usina_id == usina_id,
                               Monitoramento.data >= data_ini,
                               Monitoramento.data <= data_fim,
                               Monitoramento.inverter_sn.in_(inv_sns))
                       .order_by(Monitoramento.inverter_sn.asc(), Monitoramento.data.asc())
                       .all())

    mapa = defaultdict(dict)  # {sn: {date: etoday}}
    pot_por_sn = {i.inverter_sn: (i.potencia_kw or None) for i in inversores}
    for r in mon_periodo:
        mapa[r.inverter_sn][r.data] = float(r.etoday or 0.0)

    chart_series, cumul_por_sn, media_por_sn, max_por_sn = [], {}, {}, {}
    for sn in inv_sns:
        valores = [mapa[sn].get(d, 0.0) for d in labels_datas]
        cumul = sum(valores)
        cumul_por_sn[sn] = cumul
        media_por_sn[sn] = (cumul / len(labels_datas)) if labels_datas else 0.0
        max_por_sn[sn] = max(valores) if valores else 0.0
        chart_series.append({"label": sn, "data": valores})

    top_ordenado = sorted(cumul_por_sn.items(), key=lambda x: x[1], reverse=True)
    top_labels = [sn for sn, _ in top_ordenado]
    top_data = [val for _, val in top_ordenado]

    radar_labels = ['Média (kWh/dia)', 'Máximo diário (kWh)', 'Geração total (kWh)']
    radar_series = [{"label": sn,
                     "data": [media_por_sn.get(sn, 0.0),
                              max_por_sn.get(sn, 0.0),
                              cumul_por_sn.get(sn, 0.0)]}
                    for sn in inv_sns]

    scatter_points = []
    for sn in inv_sns:
        pot = pot_por_sn.get(sn)
        if pot is not None:
            scatter_points.append({"x": float(pot),
                                   "y": float(media_por_sn.get(sn, 0.0)),
                                   "label": sn})

    kpi_periodo = {
        "dias": len(labels_datas),
        "total_periodo_kwh": round(sum(top_data), 3) if top_data else 0.0,
        "melhor_sn": top_labels[0] if top_labels else None,
        "melhor_total_kwh": round(top_data[0], 3) if top_data else 0.0
    }

    return render_template('monitoramento_usina.html',
                           usina=usina,
                           # tabela do topo
                           registros_tab=registros_tab,
                           registros_tab_sorted=registros_tab_sorted,
                           data_tab_ref=data_tab_ref,
                           latest_ids=latest_ids,              # usado no HTML (mostrar eToday só no mais recente)
                           latest_etoday_por_sn=latest_etoday_por_sn,
                           indice_usina_pct=indice_usina_pct,
                           # visão/cards
                           registros=registros,
                           inversores=inversores,
                           view=view,
                           data_ref=data_ref,
                           total=total,
                           online_cnt=online_cnt,
                           comunicando_cnt=comunicando_cnt,
                           # gráficos/comparação
                           data_ini=data_ini, data_fim=data_fim,
                           inv_sns=inv_sns,
                           chart_labels=labels_fmt,
                           chart_series=chart_series,
                           top_labels=top_labels, top_data=top_data,
                           radar_labels=radar_labels, radar_series=radar_series,
                           scatter_points=scatter_points,
                           kpi_periodo=kpi_periodo)
    
@app.route('/monitoramento')
@login_required
def monitoramento_index():
    usinas = Usina.query.order_by(Usina.nome).all()
    return render_template('monitoramento_index.html', usinas=usinas)

@app.route('/usinas/<int:usina_id>/inversores/novo', methods=['GET', 'POST'], endpoint='cadastrar_inversor_usina')
@login_required
def cadastrar_inversor_usina(usina_id):
    usina = Usina.query.get_or_404(usina_id)

    import re
    def _to_float_br_local(v):
        if v is None:
            return None
        s = str(v).strip()
        if s == '':
            return None
        if ',' in s:
            s = re.sub(r'\.(?=\d{3}(?:\D|$))', '', s)
            s = s.replace(',', '.')
        try:
            return float(s)
        except ValueError:
            return None

    if request.method == 'POST':
        inverter_sn = (request.form.get('inverter_sn') or '').strip()
        nome = (request.form.get('nome') or '').strip()
        potencia_kw = _to_float_br_local(request.form.get('potencia_kw'))

        if not inverter_sn:
            flash('Informe o Serial (inverter_sn).', 'warning')
            return _render_inversor_cadastrar(usina, form_data=request.form)

        existente = (InversorCadastrado.query
                     .filter_by(usina_id=usina.id, inverter_sn=inverter_sn)
                     .first())
        if existente:
            flash('Já existe um inversor com este serial nesta usina.', 'danger')
            return _render_inversor_cadastrar(usina, form_data=request.form)

        inv = InversorCadastrado(
            usina_id=usina.id,
            inverter_sn=inverter_sn,
            nome=nome or None,
            potencia_kw=potencia_kw,
            ativo=True
        )
        db.session.add(inv)
        db.session.commit()
        flash('Inversor cadastrado com sucesso!', 'success')
        return redirect(url_for('cadastrar_inversor_usina', usina_id=usina.id))

    # GET
    return _render_inversor_cadastrar(usina, form_data={})


def _render_inversor_cadastrar(usina, form_data):
    # lista de inversores
    inversores = (InversorCadastrado.query
                  .filter_by(usina_id=usina.id)
                  .order_by(InversorCadastrado.ativo.desc(),
                            InversorCadastrado.nome.asc().nullslast(),
                            InversorCadastrado.inverter_sn.asc())
                  .all())

    # contagem de gerações SEM vínculo por SN (desta usina)
    rows = (db.session.query(GeracaoInversor.inverter_sn,
                             func.count(GeracaoInversor.id))
            .filter(GeracaoInversor.usina_id == usina.id,
                    GeracaoInversor.inversor_id.is_(None))
            .group_by(GeracaoInversor.inverter_sn)
            .all())
    contagem_sem_vinculo = {sn: qtd for sn, qtd in rows}

    # serials existentes em geracoes SEM vinculo (para a seção extra)
    sn_sem_vinculo = sorted(contagem_sem_vinculo.keys())

    return render_template('inversor_cadastrar.html',
                           usina=usina,
                           form_data=form_data,
                           inversores=inversores,
                           contagem_sem_vinculo=contagem_sem_vinculo,
                           sn_sem_vinculo=sn_sem_vinculo)


# 2) Vincular TODAS as gerações (dessa usina) cujo SN == SN do inversor escolhido
@app.post('/usinas/<int:usina_id>/inversores/<int:inv_id>/vincular-por-sn')
@login_required
def vincular_geracoes_por_sn(usina_id, inv_id):
    usina = Usina.query.get_or_404(usina_id)
    inv = InversorCadastrado.query.filter_by(id=inv_id, usina_id=usina.id).first_or_404()

    # normaliza SN do cadastro
    sn_oficial = (inv.inverter_sn or '').strip()
    if not sn_oficial:
        flash('Serial do inversor inválido.', 'danger')
        return redirect(url_for('cadastrar_inversor_usina', usina_id=usina.id))

    # Atualiza TODAS as gerações da usina cujo SN "pareça" com o oficial
    # (TRIM/UPPER) e também onde já há vínculo diferente.
    atualizadas = (GeracaoInversor.query
        .filter(
            GeracaoInversor.usina_id == usina.id,
            or_(
                func.upper(func.trim(GeracaoInversor.inverter_sn)) == func.upper(func.trim(sn_oficial)),
                # opcional: trate variações comuns (troca de -/_/espaços)
                func.upper(func.replace(func.replace(func.trim(GeracaoInversor.inverter_sn), '-', ''), '_', ''))
                   == func.upper(func.replace(func.replace(sn_oficial.strip(), '-', ''), '_', ''))
            )
        )
        .update({
            GeracaoInversor.inversor_id: inv.id,
            # espelha o SN "oficial" para manter consistência
            GeracaoInversor.inverter_sn: sn_oficial
        }, synchronize_session=False))

    db.session.commit()
    flash(f'Vinculadas {atualizadas} gerações ao inversor {sn_oficial}.', 'success')
    return redirect(url_for('cadastrar_inversor_usina', usina_id=usina.id))


@app.post('/usinas/<int:usina_id>/inversores/auto-vincular-por-sn')
@login_required
def auto_vincular_por_sn(usina_id):
    usina = Usina.query.get_or_404(usina_id)
    inversores = InversorCadastrado.query.filter_by(usina_id=usina.id).all()

    total = 0
    for inv in inversores:
        sn_oficial = (inv.inverter_sn or '').strip()
        if not sn_oficial:
            continue

        qtd = (GeracaoInversor.query
            .filter(
                GeracaoInversor.usina_id == usina.id,
                or_(
                    func.upper(func.trim(GeracaoInversor.inverter_sn)) == func.upper(func.trim(sn_oficial)),
                    func.upper(func.replace(func.replace(func.trim(GeracaoInversor.inverter_sn), '-', ''), '_', ''))
                       == func.upper(func.replace(func.replace(sn_oficial, '-', ''), '_', ''))
                )
            )
            .update({
                GeracaoInversor.inversor_id: inv.id,
                GeracaoInversor.inverter_sn: sn_oficial
            }, synchronize_session=False))
        total += (qtd or 0)

    db.session.commit()
    flash(f'Auto-vinculação concluída. {total} gerações vinculadas por SN.', 'success')
    return redirect(url_for('cadastrar_inversor_usina', usina_id=usina.id))


@app.post('/usinas/<int:usina_id>/inversores/<int:inv_id>/desvincular-por-sn')
@login_required
def desvincular_geracoes_por_sn(usina_id, inv_id):
    usina = Usina.query.get_or_404(usina_id)
    inv = InversorCadastrado.query.filter_by(id=inv_id, usina_id=usina.id).first_or_404()

    sn_oficial = (inv.inverter_sn or '').strip()
    atualizadas = (GeracaoInversor.query
        .filter(
            GeracaoInversor.usina_id == usina.id,
            func.upper(func.trim(GeracaoInversor.inverter_sn)) == func.upper(func.trim(sn_oficial)),
            GeracaoInversor.inversor_id == inv.id
        )
        .update({GeracaoInversor.inversor_id: None}, synchronize_session=False))

    db.session.commit()
    flash(f'Desvinculadas {atualizadas} gerações do inversor {sn_oficial}.', 'warning')
    return redirect(url_for('cadastrar_inversor_usina', usina_id=usina.id))
    
@app.route('/usinas/<int:usina_id>/inversores/<int:inv_id>/editar', methods=['GET', 'POST'], endpoint='editar_inversor_usina')
@login_required
def editar_inversor_usina(usina_id, inv_id):
    usina = Usina.query.get_or_404(usina_id)
    inv = InversorCadastrado.query.filter_by(id=inv_id, usina_id=usina_id).first_or_404()

    def _to_float_br_local(v):
        if v is None: return None
        s = str(v).strip()
        if not s: return None
        if ',' in s:
            s = re.sub(r'\.(?=\d{3}(?:\D|$))', '', s)
            s = s.replace(',', '.')
        try: return float(s)
        except ValueError: return None

    if request.method == 'POST':
        inv.nome = (request.form.get('nome') or '').strip() or None
        inv.potencia_kw = _to_float_br_local(request.form.get('potencia_kw'))
        # Serial não editado aqui para não “descolar” dos monitoramentos existentes
        db.session.commit()
        flash('Inversor atualizado!', 'success')
        return redirect(url_for('cadastrar_inversor_usina', usina_id=usina.id))

    form_data = {
        'inverter_sn': inv.inverter_sn,
        'nome': inv.nome or '',
        'potencia_kw': f"{inv.potencia_kw:.3f}".replace('.', ',') if inv.potencia_kw is not None else ''
    }
    return render_template('inversor_editar.html', usina=usina, inv=inv, form_data=form_data)

@app.route('/usinas/<int:usina_id>/inversores/<int:inv_id>/status', methods=['POST'], endpoint='alterar_status_inversor_usina')
@login_required
def alterar_status_inversor_usina(usina_id, inv_id):
    inv = InversorCadastrado.query.filter_by(id=inv_id, usina_id=usina_id).first_or_404()
    inv.ativo = not inv.ativo
    db.session.commit()
    flash('Status alterado!', 'success')
    return redirect(url_for('cadastrar_inversor_usina', usina_id=usina_id))

@app.route('/usinas/<int:usina_id>/inversores/<int:inv_id>/excluir', methods=['POST'], endpoint='excluir_inversor_usina')
@login_required
def excluir_inversor_usina(usina_id, inv_id):
    inv = InversorCadastrado.query.filter_by(id=inv_id, usina_id=usina_id).first_or_404()
    db.session.delete(inv)
    db.session.commit()
    flash('Inversor excluído!', 'success')
    return redirect(url_for('cadastrar_inversor_usina', usina_id=usina_id))

@app.route('/usinas/<int:usina_id>/geracao', methods=['GET', 'POST'], endpoint='inserir_geracao_inversor')
@login_required
def inserir_geracao_inversor(usina_id):
    usina = Usina.query.get_or_404(usina_id)

    # inversores (use ativo=True se quiser restringir)
    inversores = (InversorCadastrado.query
                  .filter_by(usina_id=usina_id)
                  .order_by(InversorCadastrado.nome.asc().nullslast(),
                            InversorCadastrado.inverter_sn.asc())
                  .all())
    pot_por_sn = {inv.inverter_sn: (inv.potencia_kw or None) for inv in inversores}

    # helper número BR -> float
    def _to_float_br_local(v):
        if v is None: return None
        s = str(v).strip()
        if not s: return None
        if ',' in s:
            s = re.sub(r'\.(?=\d{3}(?:\D|$))', '', s)
            s = s.replace(',', '.')
        try: return float(s)
        except ValueError: return None

    # ----------------------- POST: lançamento manual (um dia) -----------------------
    if request.method == 'POST':
        data_str = request.form.get('data') or ''
        try:
            data_ref = datetime.strptime(data_str, '%Y-%m-%d').date() if data_str else date.today()
        except ValueError:
            data_ref = date.today()

        inverter_sn = (request.form.get('inverter_sn') or '').strip()
        if not inverter_sn:
            flash('Selecione um inversor.', 'warning')
            return redirect(url_for('inserir_geracao_inversor', usina_id=usina_id, data=data_ref.strftime('%Y-%m-%d')))

        etoday = _to_float_br_local(request.form.get('etoday'))
        if etoday is None:
            flash('Informe um valor válido para eToday.', 'warning')
            return redirect(url_for('inserir_geracao_inversor', usina_id=usina_id, data=data_ref.strftime('%Y-%m-%d')))

        # upsert por (usina, inversor, data)
        reg = (Monitoramento.query
               .filter_by(usina_id=usina_id, inverter_sn=inverter_sn, data=data_ref)
               .first())
        if not reg:
            reg = Monitoramento(usina_id=usina_id, inverter_sn=inverter_sn, data=data_ref)
            db.session.add(reg)
        reg.etoday = etoday

        pot = pot_por_sn.get(inverter_sn)
        if pot is not None:
            reg.potencia_kw = pot

        db.session.commit()
        flash('Geração salva com sucesso!', 'success')
        return redirect(url_for('inserir_geracao_inversor', usina_id=usina_id, data=data_ref.strftime('%Y-%m-%d')))

    # ----------------------- GET: filtros -----------------------
    data_str = request.args.get('data') or ''
    data_ini_str = request.args.get('data_ini') or ''
    data_fim_str = request.args.get('data_fim') or ''

    data_ref = None
    data_ini = None
    data_fim = None

    if data_str:
        try:
            data_ref = datetime.strptime(data_str, '%Y-%m-%d').date()
        except ValueError:
            data_ref = date.today()
    else:
        if data_ini_str:
            try: data_ini = datetime.strptime(data_ini_str, '%Y-%m-%d').date()
            except ValueError: data_ini = None
        if data_fim_str:
            try: data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
            except ValueError: data_fim = None
        if data_ini and not data_fim: data_fim = data_ini
        if data_fim and not data_ini: data_ini = data_fim
    if not data_ref and not (data_ini and data_fim):
        data_ref = date.today()

    # ----------------------- SYNC inline (apenas com vínculo) -----------------------
    if hasattr(GeracaoInversor, 'inversor_id'):
        if data_ref:
            di, df = data_ref, data_ref
        else:
            di, df = data_ini, data_fim

        # agrega por (data, SN) apenas gerações VINCULADAS
        gi_rows = (db.session.query(
                        GeracaoInversor.data.label('data'),
                        GeracaoInversor.inverter_sn.label('sn'),
                        func.sum(GeracaoInversor.etoday).label('etoday_sum')
                   )
                   .filter(
                        GeracaoInversor.usina_id == usina_id,
                        GeracaoInversor.inversor_id.isnot(None),
                        GeracaoInversor.data >= di,
                        GeracaoInversor.data <= df
                   )
                   .group_by(GeracaoInversor.data, GeracaoInversor.inverter_sn)
                   .all())

        count_updates = 0
        for row in gi_rows:
            d = row.data
            sn = (row.sn or '').strip()
            if not sn:
                continue

            reg = (Monitoramento.query
                   .filter_by(usina_id=usina_id, inverter_sn=sn, data=d)
                   .first())
            if not reg:
                reg = Monitoramento(usina_id=usina_id, inverter_sn=sn, data=d)
                db.session.add(reg)

            reg.etoday = float(row.etoday_sum or 0.0)

            pot = pot_por_sn.get(sn)
            if pot is not None:
                reg.potencia_kw = pot

            count_updates += 1

        if count_updates:
            if di == df:
                flash(f'Sincronizados {count_updates} registro(s) vinculados em {di.strftime("%d/%m/%Y")}.', 'info')
            else:
                flash(f'Sincronizados {count_updates} registro(s) vinculados de {di.strftime("%d/%m/%Y")} a {df.strftime("%d/%m/%Y")}.', 'info')

        db.session.commit()

    # monta a lista para exibição
    if data_ref:
        registros_dia = (Monitoramento.query
                         .filter(Monitoramento.usina_id == usina_id,
                                 Monitoramento.data == data_ref)
                         .order_by(Monitoramento.inverter_sn.asc())
                         .all())
        cadastrados_cnt = len(inversores)
        registrados_cnt = len({r.inverter_sn for r in registros_dia})
        soma_etoday = sum((r.etoday or 0.0) for r in registros_dia)

        return render_template('geracao_inversor.html',
                               usina=usina,
                               data_ref=data_ref,
                               data_ini=None, data_fim=None,
                               inversores=inversores,
                               registros_dia=registros_dia,
                               cadastrados_cnt=cadastrados_cnt,
                               registrados_cnt=registrados_cnt,
                               soma_etoday=soma_etoday)
    else:
        registros_periodo = (Monitoramento.query
                             .filter(Monitoramento.usina_id == usina_id,
                                     Monitoramento.data >= data_ini,
                                     Monitoramento.data <= data_fim)
                             .order_by(Monitoramento.data.asc(),
                                       Monitoramento.inverter_sn.asc())
                             .all())
        cadastrados_cnt = len(inversores)
        registrados_cnt = len({(r.data, r.inverter_sn) for r in registros_periodo})
        soma_etoday = sum((r.etoday or 0.0) for r in registros_periodo)

        return render_template('geracao_inversor.html',
                               usina=usina,
                               data_ref=None,
                               data_ini=data_ini, data_fim=data_fim,
                               inversores=inversores,
                               registros_dia=registros_periodo,
                               cadastrados_cnt=cadastrados_cnt,
                               registrados_cnt=registrados_cnt,
                               soma_etoday=soma_etoday)

@app.route('/usinas/<int:usina_id>/analise-diaria', methods=['GET', 'POST'], endpoint='analise_diaria')
@login_required
def analise_diaria(usina_id):
    usina = Usina.query.get_or_404(usina_id)

    # Data de referência (GET ou POST mantém o mesmo comportamento)
    data_str = request.values.get('data') or ''
    try:
        data_ref = datetime.strptime(data_str, '%Y-%m-%d').date() if data_str else date.today()
    except ValueError:
        data_ref = date.today()

    # Inversores ativos
    inversores = (InversorCadastrado.query
                  .filter_by(usina_id=usina_id, ativo=True)
                  .order_by(InversorCadastrado.nome.asc().nullslast(),
                            InversorCadastrado.inverter_sn.asc())
                  .all())

    # POST: criar um novo status (múltiplas vezes ao dia)
    if request.method == 'POST':
        inverter_sn   = (request.form.get('inverter_sn') or '').strip()
        if not inverter_sn:
            flash('Selecione um inversor.', 'warning')
            return redirect(url_for('analise_diaria', usina_id=usina_id, data=data_ref.strftime('%Y-%m-%d')))

        online        = bool(request.form.get('online'))
        comunicando   = bool(request.form.get('comunicando'))
        mensagem_erro = (request.form.get('mensagem_erro') or '').strip() or None

        # Hora do registro (HH:MM)
        hora_str = request.form.get('hora') or ''
        try:
            hora = datetime.strptime(hora_str, '%H:%M').time() if hora_str else datetime.now().time()
        except ValueError:
            hora = datetime.now().time()

        coletado_em = datetime.combine(data_ref, hora)

        # Último ping (datetime-local: YYYY-MM-DDTHH:MM)
        up_str = request.form.get('ultimo_ping_dt') or ''
        try:
            ultimo_ping = datetime.strptime(up_str, '%Y-%m-%dT%H:%M') if up_str else None
        except ValueError:
            ultimo_ping = None

        # Cria um novo registro (NÃO faz upsert por dia, permite vários)
        reg = Monitoramento(
            usina_id=usina_id,
            inverter_sn=inverter_sn,
            data=data_ref,
            online=online,
            comunicando=comunicando,
            mensagem_erro=mensagem_erro,
            coletado_em=coletado_em,
            ultimo_ping=ultimo_ping
        )

        # puxa potência do cadastro se houver
        inv = next((i for i in inversores if i.inverter_sn == inverter_sn), None)
        if inv and inv.potencia_kw is not None:
            reg.potencia_kw = inv.potencia_kw

        db.session.add(reg)
        db.session.commit()
        flash('Status registrado com sucesso!', 'success')
        return redirect(url_for('analise_diaria', usina_id=usina_id, data=data_ref.strftime('%Y-%m-%d')))

    # Carrega TODOS os registros do dia para a usina (podem existir vários por inversor)
    regs_do_dia = (Monitoramento.query
                   .filter(Monitoramento.usina_id == usina_id,
                           Monitoramento.data == data_ref)
                   .order_by(Monitoramento.inverter_sn.asc(),
                             Monitoramento.coletado_em.desc().nullslast(),
                             Monitoramento.id.desc())
                   .all())

    # Mapa: inverter_sn -> ÚLTIMO registro do dia (o mais recente)
    reg_por_sn = {}
    # Histórico por SN
    historico_por_sn = {}
    for r in regs_do_dia:
        historico_por_sn.setdefault(r.inverter_sn, []).append(r)
        if r.inverter_sn not in reg_por_sn:
            reg_por_sn[r.inverter_sn] = r  # primeiro da lista já é o mais recente pelo order_by

    return render_template(
        'analise_diaria.html',
        usina=usina,
        inversores=inversores,
        data_ref=data_ref,
        reg_por_sn=reg_por_sn,           # usado para exibir "o estado atual" por inversor
        historico_por_sn=historico_por_sn # usado para exibir o histórico do dia
    )
    
@app.route('/empresa/cadastrar', methods=['GET','POST'], endpoint='cadastrar_empresa_operacional')
@login_required
def cadastrar_empresa_operacional():
    if request.method == 'POST':
        nome = request.form.get('nome')
        cnpj = request.form.get('cnpj')
        endereco = request.form.get('endereco')
        telefone = request.form.get('telefone')
        email = request.form.get('email')
        responsavel = request.form.get('responsavel')

        if not nome:
            flash('O nome da empresa é obrigatório.', 'danger')
            return redirect(url_for('cadastrar_empresa_operacional'))

        if cnpj and Empresa.query.filter_by(cnpj=cnpj).first():
            flash('Já existe uma empresa cadastrada com esse CNPJ.', 'warning')
            return redirect(url_for('cadastrar_empresa_operacional'))

        db.session.add(Empresa(
            nome=nome, cnpj=cnpj, endereco=endereco,
            telefone=telefone, email=email, responsavel=responsavel
        ))
        db.session.commit()
        flash('Empresa cadastrada com sucesso!', 'success')
        return redirect(url_for('listar_empresas_operacional'))

    return render_template('empresas_cadastrar.html')

@app.route('/empresa', methods=['GET'], endpoint='listar_empresas_operacional')
@login_required
def listar_empresas_operacional():  # EMPRESA OPERACIONAL
    empresas = Empresa.query.order_by(Empresa.nome).all()
    return render_template('empresas_listar.html', empresas=empresas)

# EDITAR EMPRESA OPERACIONAL
@app.route('/empresa/<int:empresa_id>/editar', methods=['GET', 'POST'], endpoint='editar_empresa_operacional')
@login_required
def editar_empresa_operacional(empresa_id):
    e = db.session.get(Empresa, empresa_id)
    if not e:
        abort(404)

    if request.method == 'POST':
        nome = request.form.get('nome')
        cnpj = request.form.get('cnpj') or None
        endereco = request.form.get('endereco')
        telefone = request.form.get('telefone')
        email = request.form.get('email')
        responsavel = request.form.get('responsavel')

        if not nome:
            flash('O nome da empresa é obrigatório.', 'danger')
            return redirect(url_for('editar_empresa_operacional', empresa_id=e.id))

        # Evita CNPJ duplicado (se alterado)
        if cnpj and cnpj != e.cnpj and Empresa.query.filter_by(cnpj=cnpj).first():
            flash('Já existe uma empresa com esse CNPJ.', 'warning')
            return redirect(url_for('editar_empresa_operacional', empresa_id=e.id))

        e.nome = nome
        e.cnpj = cnpj
        e.endereco = endereco
        e.telefone = telefone
        e.email = email
        e.responsavel = responsavel

        db.session.commit()
        flash('Empresa atualizada com sucesso!', 'success')
        return redirect(url_for('listar_empresas_operacional'))

    return render_template('empresas_editar.html', e=e)

# EXCLUIR EMPRESA OPERACIONAL
@app.route('/empresa/<int:empresa_id>/excluir', methods=['POST'], endpoint='excluir_empresa_operacional')
@login_required
def excluir_empresa_operacional(empresa_id):
    e = db.session.get(Empresa, empresa_id)
    if not e:
        abort(404)

    db.session.delete(e)
    db.session.commit()
    flash('Empresa excluída com sucesso.', 'success')
    return redirect(url_for('listar_empresas_operacional'))

def _parse_decimal_br(s):
    if not s: return None
    try:
        return Decimal(s.replace('.', '').replace(',', '.'))
    except InvalidOperation:
        return None

def _parse_date(s):
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None

ALLOWED_EXTS = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif'}

def _allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename.lower())[1]
    return ext in ALLOWED_EXTS

def _ensure_comprovantes_dir() -> str:
    base_dir = os.environ.get('COMPROVANTES_PATH') or '/data/uploads'
    os.makedirs(base_dir, exist_ok=True)
    return base_dir

def _unique_name(filename: str) -> str:
    safe = secure_filename(filename)
    ts = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
    return f'{ts}_{safe}'

def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def _to_int_ids(values):
    return [int(x) for x in values if str(x).isdigit()]

def _getlist_either(req, base):
    """Lê getlist tanto com quanto sem '[]' no name."""
    vals = req.getlist(base)
    if not vals:
        vals = req.getlist(base + '[]')
    return vals

def _getlist_files_either(req_files, *names):
    """Retorna lista de FileStorage do primeiro nome encontrado."""
    for n in names:
        lst = req_files.getlist(n)
        if lst:
            return lst
    return []

def _save_multi_files(files):
    """
    Salva múltiplos arquivos em /comprovantes e retorna lista de dicts:
      { 'filename': <salvo>, 'original_name': <original> }
    Ignora silenciosamente entradas vazias ou com extensão não permitida.
    """
    saved = []
    if not files:
        return saved

    base_dir = _ensure_comprovantes_dir()
    for f in files:
        if not f or not getattr(f, 'filename', None):
            continue
        if not _allowed_file(f.filename):
            # aqui pode dar flash/abortar se preferir
            continue

        unique_name = _unique_name(f.filename)
        abs_path = os.path.join(base_dir, unique_name)
        try:
            f.save(abs_path)
            saved.append({
                'filename': unique_name,
                'original_name': f.filename
            })
        except Exception as e:
            print('Falha ao salvar arquivo múltiplo:', e)
            # remova os já salvos e aborte
    return saved

@app.route('/empresa/financeiro/lancar', methods=['GET', 'POST'], endpoint='empresa_financeiro_lancar')
@login_required
def empresa_financeiro_lancar():
    # Listas auxiliares para o formulário (GET e também usados em caso de erro)
    empresas = Empresa.query.order_by(Empresa.nome.asc()).all()
    contas_all = CaixaBanco.query.order_by(CaixaBanco.nome.asc()).all()
    centros_all = CentroCusto.query.order_by(CentroCusto.empresa_id.asc(), CentroCusto.codigo.asc()).all()
    planos_all = PlanoFinanceiro.query.filter_by(ativo=True).order_by(PlanoFinanceiro.nome.asc()).all()
    credores_all = Credor.query.order_by(Credor.nome.asc()).all()
    clientes_op_all = ClienteOperacional.query.filter_by(ativo=True).order_by(ClienteOperacional.nome.asc()).all()

    if request.method == 'POST':
        form = request.form

        # Campos básicos
        empresa_id = form.get('empresa_id', type=int)
        tipo = (form.get('tipo') or '').lower().strip()                 # 'receita' | 'despesa'
        descricao = (form.get('descricao') or '').strip()
        data_tit = _parse_date(form.get('data'))                            # emissão
        valor_tot = _parse_decimal_br(form.get('valor'))
        status = (form.get('status') or 'pendente').lower().strip()       # 'pendente'|'pago'|'recebido'
        data_venc_base = _parse_date(form.get('data_vencimento'))                 # venc. 1ª parcela (ou data pgto/rec.)
        conta_id = form.get('conta_id', type=int)
        numero_documento = (form.get('numero_documento') or '').strip() or None

        # Credor (obrigatório para DESPESA)
        credor_id = form.get('credor_id', type=int)
        credor    = db.session.get(Credor, credor_id) if (credor_id and tipo == 'despesa') else None

        # Cliente operacional
        cliente_operacional_id = form.get('cliente_operacional_id', type=int)
        cliente_operacional = None
        if tipo == 'receita' and cliente_operacional_id:
            cliente_operacional = db.session.get(ClienteOperacional, cliente_operacional_id)
            if not cliente_operacional:
                flash('Cliente operacional inválido.', 'danger')
                return redirect(url_for('empresa_financeiro_lancar'))

        # Multiseleção + parcelas
        planos_ids_raw = _getlist_either(form, 'planos_financeiros_ids')
        centros_ids_raw = _getlist_either(form, 'centros_custos_ids')
        planos_ids = _to_int_ids(planos_ids_raw)
        centros_ids = _to_int_ids(centros_ids_raw)

        parcelas_qtd = form.get('parcelas_qtd', type=int) or 1
        if parcelas_qtd < 1:
            parcelas_qtd = 1

        # Validações
        emp = db.session.get(Empresa, empresa_id) if empresa_id else None
        if not emp:
            flash('Selecione uma empresa válida.', 'danger')
            return redirect(url_for('empresa_financeiro_lancar'))

        if tipo not in ('receita', 'despesa'):
            flash('Tipo inválido.', 'danger')
            return redirect(url_for('empresa_financeiro_lancar'))

        if tipo == 'despesa' and not credor:
            flash('Selecione um credor válido para despesas.', 'danger')
            return redirect(url_for('empresa_financeiro_lancar'))

        if not descricao:
            flash('Descrição é obrigatória.', 'danger')
            return redirect(url_for('empresa_financeiro_lancar'))

        if not data_tit:
            flash('Data do título inválida.', 'danger')
            return redirect(url_for('empresa_financeiro_lancar'))

        if not valor_tot or valor_tot <= 0:
            flash('Valor inválido.', 'danger')
            return redirect(url_for('empresa_financeiro_lancar'))

        if status not in ('pendente', 'pago', 'recebido'):
            flash('Status inválido.', 'danger')
            return redirect(url_for('empresa_financeiro_lancar'))

        if not planos_ids:
            flash('Selecione ao menos um Plano Financeiro.', 'warning')
            return redirect(url_for('empresa_financeiro_lancar'))

        if not centros_ids:
            flash('Selecione ao menos um Centro de Custo.', 'warning')
            return redirect(url_for('empresa_financeiro_lancar'))

        conta = db.session.get(CaixaBanco, conta_id) if conta_id else None
        if conta and conta.empresa_id != empresa_id:
            flash('A conta selecionada não pertence à empresa.', 'danger')
            return redirect(url_for('empresa_financeiro_lancar'))

        ok_centros = {c.id for c in CentroCusto.query.filter(
            CentroCusto.id.in_(centros_ids),
            CentroCusto.empresa_id == empresa_id
        ).all()}
        if len(ok_centros) != len(centros_ids):
            flash('Há centro(s) de custo que não pertencem à empresa selecionada.', 'danger')
            return redirect(url_for('empresa_financeiro_lancar'))

        ativos_ids = {p.id for p in PlanoFinanceiro.query.filter(
            PlanoFinanceiro.id.in_(planos_ids),
            PlanoFinanceiro.ativo.is_(True)
        ).all()}
        if len(ativos_ids) != len(planos_ids):
            flash('Há plano(s) financeiros inválidos ou inativos.', 'danger')
            return redirect(url_for('empresa_financeiro_lancar'))

        if not data_venc_base:
            data_venc_base = data_tit

        # Upload múltiplo (com compat para campo único)
        files_up = _getlist_files_either(request.files, 'comprovantes[]', 'comprovantes', 'comprovante')
        saved_files = _save_multi_files(files_up)
        first_filename = saved_files[0]['filename'] if saved_files else None

        # Valores por plano (verifica soma bate com total)
        valores_por_plano = {}
        soma_planos = Decimal('0.00')
        for pid in planos_ids:
            raw = form.get(f'valor_plano[{pid}]')
            dec = _parse_decimal_br(raw) if raw is not None else None
            if dec is None or dec < 0:
                flash(f'Valor inválido para o plano #{pid}.', 'danger')
                return redirect(url_for('empresa_financeiro_lancar'))
            dec = _q2(dec)
            valores_por_plano[pid] = dec
            soma_planos += dec

        if _q2(soma_planos) != _q2(Decimal(valor_tot)):
            flash('A soma dos valores por plano deve ser igual ao Valor (R$) total.', 'danger')
            return redirect(url_for('empresa_financeiro_lancar'))

        # Função para rateio correto com ajuste do resto na última parcela
        def ratear(total_dec: Decimal, partes: int):
            if partes <= 0: return []
            base = _q2(total_dec / Decimal(partes))
            lst = [base] * partes
            diff = total_dec - sum(lst)
            if diff != Decimal('0.00'):
                lst[-1] = _q2(lst[-1] + diff)
            return lst

        try:
            criados = 0
            partes_por_plano = len(centros_ids) * parcelas_qtd

            # Para anexar só no primeiro título, capture este id:
            first_titulo_id = None

            for pid in planos_ids:
                total_plano = valores_por_plano[pid]
                if partes_por_plano <= 0:
                    continue

                valores_partes = ratear(total_plano, partes_por_plano)
                idx_val = 0

                for cid in centros_ids:
                    for parc in range(parcelas_qtd):
                        valor_parte = valores_partes[idx_val]; idx_val += 1
                        data_venc_parc = data_venc_base + relativedelta(months=parc)

                        titulo = FinanceiroEmpresa(
                            empresa_id=empresa_id,
                            data=data_tit,
                            tipo=tipo,
                            descricao=(descricao if parcelas_qtd == 1 else f"{descricao} ({parc+1}/{parcelas_qtd})"),
                            valor=valor_parte,
                            status=status,
                            data_vencimento=data_venc_parc,
                            conta_id=conta.id if conta else None,
                            plano_financeiro_id=pid,
                            centro_custo_id=cid,
                            credor_id=(credor.id if credor else None),
                            cliente_operacional_id=(cliente_operacional.id if cliente_operacional else None),
                            aprovado=False,
                            numero_documento=numero_documento,
                            comprovante_arquivo=first_filename  # compat com campo único
                        )
                        db.session.add(titulo)
                        db.session.flush()  # garante titulo.id

                        if first_titulo_id is None:
                            first_titulo_id = titulo.id

                        # Anexos: replicar todos os uploads em CADA título criado
                        for sf in saved_files:
                            db.session.add(FinanceiroAnexo(
                                titulo_id=titulo.id,
                                tipo='titulo',
                                filename=sf['filename'],
                                original_name=sf.get('original_name')
                            ))                        

                        # Movimento de caixa (se conta e já quitado)
                        if conta and status in ('pago', 'recebido'):
                            db.session.add(MovimentoCaixaBanco(
                                conta_id=conta.id,
                                data=data_venc_parc,
                                tipo='saida' if tipo == 'despesa' else 'entrada',
                                descricao=f'{tipo.capitalize()} - {titulo.descricao}',
                                valor=valor_parte,
                                origem='financeiro_empresa',
                                referencia_id=titulo.id
                            ))

                        criados += 1

            db.session.commit()
            flash(f'Lançamento(s) criado(s) com sucesso: {criados}.', 'success')
            return redirect(url_for('empresa_financeiro_listar'))

        except Exception as e:
            db.session.rollback()
            print('Erro ao salvar lançamento(s) financeiro(s) da empresa:', e)
            # remover arquivos recém-salvos se quiser reverter
            flash('Erro ao salvar lançamento.', 'danger')
            return redirect(url_for('empresa_financeiro_lancar'))

    # GET
    return render_template(
        'empresa_financeiro_lancar.html',
        empresas=empresas,
        contas_all=contas_all,
        centros_all=centros_all,
        planos_all=planos_all,
        credores_all=credores_all,
        clientes_operacionais_all=clientes_op_all,  # para select de cliente em receitas (opcional)
    )
    
@app.route('/empresa/financeiro/<int:lanc_id>/editar', methods=['GET', 'POST'], endpoint='empresa_financeiro_editar')
@login_required
def empresa_financeiro_editar(lanc_id):
    titulo = db.session.get(FinanceiroEmpresa, lanc_id)
    if not titulo:
        flash('Lançamento não encontrado.', 'warning')
        return redirect(url_for('empresa_financeiro_listar'))

    # Se já aprovado, não permite salvar alterações
    if request.method == 'POST' and titulo.aprovado:
        flash('Este lançamento já foi aprovado e não pode mais ser editado.', 'warning')
        return redirect(url_for('empresa_financeiro_editar', lanc_id=lanc_id, next=request.form.get('next','')))

    # coleções para selects
    empresas = Empresa.query.order_by(Empresa.nome.asc()).all()
    contas_all = CaixaBanco.query.order_by(CaixaBanco.nome.asc()).all()
    centros_all = CentroCusto.query.order_by(CentroCusto.empresa_id.asc(), CentroCusto.codigo.asc()).all()
    planos_all = PlanoFinanceiro.query.filter_by(ativo=True).order_by(PlanoFinanceiro.nome.asc()).all()
    credoresent = Credor.query.order_by(Credor.nome.asc()).all()

    if request.method == 'GET':
        return render_template(
            'empresa_financeiro_editar.html',
            titulo=titulo,
            empresas=empresas,
            contas_all=contas_all,
            centros_all=centros_all,
            planos_all=planos_all,
            credoresent=credoresent,
        )

    # POST (salvar alterações)
    form = request.form

    empresa_id = form.get('empresa_id', type=int)
    tipo = (form.get('tipo') or '').lower()                 # 'receita' | 'despesa'
    descricao = (form.get('descricao') or '').strip()
    data_tit = _parse_date(form.get('data'))                    # emissão
    valor = _parse_decimal_br(form.get('valor'))
    status = (form.get('status') or 'pendente').lower()       # 'pendente' | 'pago' | 'recebido'
    data_venc = _parse_date(form.get('data_vencimento')) or _parse_date(form.get('data_pagamento'))
    conta_id = form.get('conta_id', type=int)
    numero_documento = (form.get('numero_documento') or '').strip() or None
    plano_financeiro_id = form.get('plano_financeiro_id', type=int)
    centro_custo_id = form.get('centro_custo_id', type=int)

    # credor (obrigatório para despesa)
    credor_id = form.get('credor_id', type=int) if tipo == 'despesa' else None
    if tipo == 'despesa' and not credor_id:
        flash('Selecione um credor para despesas.', 'warning')
        return redirect(url_for('empresa_financeiro_editar', lanc_id=lanc_id, next=form.get('next','')))
    credor = db.session.get(Credor, credor_id) if credor_id else None
    if tipo == 'despesa' and not credor:
        flash('Credor inválido.', 'danger')
        return redirect(url_for('empresa_financeiro_editar', lanc_id=lanc_id, next=form.get('next','')))

    # Validações básicas
    emp = db.session.get(Empresa, empresa_id) if empresa_id else None
    if not emp:
        flash('Selecione uma empresa válida.', 'danger')
        return redirect(url_for('empresa_financeiro_editar', lanc_id=lanc_id, next=form.get('next','')))

    if tipo not in ('receita','despesa'):
        flash('Tipo inválido.', 'danger')
        return redirect(url_for('empresa_financeiro_editar', lanc_id=lanc_id, next=form.get('next','')))

    if not descricao:
        flash('Descrição é obrigatória.', 'danger')
        return redirect(url_for('empresa_financeiro_editar', lanc_id=lanc_id, next=form.get('next','')))

    if not data_tit:
        flash('Data do título inválida.', 'danger')
        return redirect(url_for('empresa_financeiro_editar', lanc_id=lanc_id, next=form.get('next','')))

    if not valor or valor <= 0:
        flash('Valor inválido.', 'danger')
        return redirect(url_for('empresa_financeiro_editar', lanc_id=lanc_id, next=form.get('next','')))

    if status not in ('pendente','pago','recebido'):
        flash('Status inválido.', 'danger')
        return redirect(url_for('empresa_financeiro_editar', lanc_id=lanc_id, next=form.get('next','')))

    # Se marcado como pago/recebido e sem vencimento, usa a data do título
    if status in ('pago','recebido') and not data_venc:
        data_venc = data_tit

    conta = db.session.get(CaixaBanco, conta_id) if conta_id else None
    if conta and conta.empresa_id != empresa_id:
        flash('A conta selecionada não pertence à empresa.', 'danger')
        return redirect(url_for('empresa_financeiro_editar', lanc_id=lanc_id, next=form.get('next','')))

    centro = db.session.get(CentroCusto, centro_custo_id) if centro_custo_id else None
    if centro and centro.empresa_id != empresa_id:
        flash('O centro de custo selecionado não pertence à empresa.', 'danger')
        return redirect(url_for('empresa_financeiro_editar', lanc_id=lanc_id, next=form.get('next','')))

    plano = db.session.get(PlanoFinanceiro, plano_financeiro_id) if plano_financeiro_id else None
    if plano and (hasattr(plano, 'ativo') and not plano.ativo):
        flash('O plano financeiro selecionado está inativo.', 'danger')
        return redirect(url_for('empresa_financeiro_editar', lanc_id=lanc_id, next=form.get('next','')))

    # ARQUIVOS
    # 1) Campo "legado" (substitui arquivo único antigo do título)
    novo_file_legado = request.files.get('comprovante')  # <input name="comprovante">
    novo_legado_filename, abs_novo_legado, abs_antigo_legado = None, None, None

    # 2) Novos anexos múltiplos (tabela financeiro_anexos)
    novos_anexos_files = request.files.getlist('comprovantes[]')  # <input multiple name="comprovantes[]">
    anexos_salvos = []  # [(abs_path, filename, original_name)]

    # 3) Remoção de anexos existentes (checkboxes no form)
    remover_ids = []
    try:
        remover_ids = [int(x) for x in (form.getlist('remover_anexo_ids[]') or [])]
    except Exception:
        remover_ids = []

    try:
        base_dir = _ensure_comprovantes_dir()

        # -- Trata arquivo "legado"
        if novo_file_legado and novo_file_legado.filename:
            if not _allowed_file(novo_file_legado.filename):
                flash('Tipo de arquivo não permitido no comprovante único. Envie PDF/JPG/PNG/GIF/WEBP/HEIC.', 'warning')
                return redirect(url_for('empresa_financeiro_editar', lanc_id=lanc_id, next=form.get('next','')))
            novo_legado_filename = _unique_name(novo_file_legado.filename)
            abs_novo_legado = os.path.join(base_dir, novo_legado_filename)
            novo_file_legado.save(abs_novo_legado)
            if titulo.comprovante_arquivo:
                abs_antigo_legado = os.path.join(base_dir, os.path.basename(titulo.comprovante_arquivo))

        # -- Salva novos anexos múltiplos
        for f in (novos_anexos_files or []):
            if not f or not f.filename:
                continue
            if not _allowed_file(f.filename):
                # se algum for inválido, aborta cedo
                flash(f'Arquivo não permitido: {f.filename}', 'warning')
                # limpa os que já salvei nesta requisição
                for ap, _, _ in anexos_salvos:
                    try: os.remove(ap)
                    except Exception: pass
                # também limpa o legado recém salvo
                if abs_novo_legado and os.path.isfile(abs_novo_legado):
                    try: os.remove(abs_novo_legado)
                    except Exception: pass
                return redirect(url_for('empresa_financeiro_editar', lanc_id=lanc_id, next=form.get('next','')))
            unique = _unique_name(f.filename)
            abs_path = os.path.join(base_dir, unique)
            f.save(abs_path)
            anexos_salvos.append((abs_path, unique, f.filename))

        # Atualizações no banco
        # detectar movimento já existente
        mov_exist = MovimentoCaixaBanco.query.filter_by(
            origem='financeiro_empresa', referencia_id=titulo.id
        ).first()

        # Atualiza campos do título
        titulo.empresa_id = empresa_id
        titulo.tipo = tipo
        titulo.descricao = descricao
        titulo.data = data_tit
        titulo.valor = valor
        titulo.status = status
        titulo.data_vencimento = data_venc
        titulo.conta_id = conta.id if conta else None
        titulo.plano_financeiro_id = plano_financeiro_id
        titulo.centro_custo_id = centro_custo_id
        titulo.numero_documento = numero_documento
        titulo.credor_id = credor_id if tipo == 'despesa' else None

        # aplica arquivo único legado (se enviado)
        if novo_legado_filename:
            titulo.comprovante_arquivo = novo_legado_filename

        # Remove anexos marcados
        if remover_ids:
            for ax in FinanceiroAnexo.query.filter(
                FinanceiroAnexo.id.in_(remover_ids),
                FinanceiroAnexo.titulo_id == titulo.id
            ).all():
                # tenta apagar do disco também
                try:
                    ap = os.path.join(base_dir, os.path.basename(ax.filename))
                    if os.path.isfile(ap): os.remove(ap)
                except Exception:
                    pass
                db.session.delete(ax)

        # Insere novos anexos
        for _, fn, orig in anexos_salvos:
            db.session.add(FinanceiroAnexo(
                titulo_id=titulo.id,
                tipo='titulo',
                filename=fn,
                original_name=orig
            ))

        # sincroniza movimento de caixa
        if status in ('pago','recebido') and conta:
            valor_mov = (valor or Decimal('0')) + (titulo.juros or Decimal('0'))
            if mov_exist:
                mov_exist.conta_id = conta.id
                mov_exist.data = data_venc or data_tit
                mov_exist.tipo = 'saida' if tipo == 'despesa' else 'entrada'
                mov_exist.descricao = f'{tipo.capitalize()} - {descricao}'
                mov_exist.valor = valor_mov
            else:
                mov_novo = MovimentoCaixaBanco(
                    conta_id=conta.id,
                    data=data_venc or data_tit,
                    tipo='saida' if tipo == 'despesa' else 'entrada',
                    descricao=f'{tipo.capitalize()} - {descricao}',
                    valor=valor_mov,
                    origem='financeiro_empresa',
                    referencia_id=titulo.id
                )
                db.session.add(mov_novo)
        else:
            if mov_exist:
                db.session.delete(mov_exist)

        db.session.commit()

        # limpa arquivo antigo legado (se substituído)
        if abs_antigo_legado and os.path.isfile(abs_antigo_legado):
            try: os.remove(abs_antigo_legado)
            except Exception: pass

        flash('Lançamento atualizado com sucesso!', 'success')
        next_url = form.get('next') or url_for('empresa_financeiro_listar')
        return redirect(next_url)

    except Exception as e:
        db.session.rollback()
        print('Erro ao atualizar lançamento:', e)
        # rollback dos arquivos recém salvos
        if abs_novo_legado and os.path.isfile(abs_novo_legado):
            try: os.remove(abs_novo_legado)
            except Exception: pass
        for ap, _, _ in anexos_salvos:
            try: os.remove(ap)
            except Exception: pass
        flash('Erro ao salvar alterações.', 'danger')
        return redirect(url_for('empresa_financeiro_editar', lanc_id=lanc_id, next=form.get('next','')))
    
@app.route('/uploads/comprovantes/<path:filename>', methods=['GET'], endpoint='download_comprovante')
@login_required
def download_comprovante(filename):
    if not filename or '/' in filename or '..' in filename:
        abort(400)
    base = current_app.config.get('COMPROVANTES_DIR') or os.getenv('COMPROVANTES_PATH') or '/data/uploads'
    fpath = os.path.join(base, os.path.basename(filename))
    if not os.path.isfile(fpath):
        abort(404)

    import mimetypes
    mime, _ = mimetypes.guess_type(fpath)
    # abra no navegador; mude para as_attachment=True se quiser baixar
    return send_from_directory(base, os.path.basename(filename), as_attachment=False, mimetype=mime)
    
@app.route('/empresa/financeiro/anexo/<int:anexo_id>', methods=['GET'], endpoint='download_anexo')
@login_required
def download_anexo(anexo_id):
    # Busca o anexo
    anexo = db.session.get(FinanceiroAnexo, anexo_id)
    if not anexo:
        abort(404)

    # dá pra garantir que o título existe
    titulo = db.session.get(FinanceiroEmpresa, anexo.titulo_id)
    if not titulo:
        abort(404)

    # Caminho seguro do arquivo
    base_dir = (
        current_app.config.get('COMPROVANTES_DIR')
        or os.getenv('COMPROVANTES_PATH')
        or '/data/uploads'
    )
    safe_name = os.path.basename(anexo.filename or '')
    if not safe_name:
        abort(404)

    fpath = os.path.join(base_dir, safe_name)
    if not os.path.isfile(fpath):
        abort(404)

    import mimetypes
    mime, _ = mimetypes.guess_type(fpath)

    # Entrega inline (navegador tenta abrir)
    return send_from_directory(base_dir, safe_name, as_attachment=False, mimetype=mime)
    
@app.route('/empresa/financeiro', methods=['GET'], endpoint='empresa_financeiro_listar')
@login_required
def empresa_financeiro_listar():
    # Filtros (querystring)
    empresa_id = request.args.get('empresa_id', type=int)
    tipo = (request.args.get('tipo') or '').lower()            # receita|despesa
    status = (request.args.get('status') or '').lower()          # pendente|pago|recebido
    aprovado = request.args.get('aprovado')                        # 'sim'|'nao'|None
    plano_id = request.args.get('plano_id', type=int)
    centro_id = request.args.get('centro_id', type=int)
    data_ini = _parse_date(request.args.get('data_ini'))
    data_fim = _parse_date(request.args.get('data_fim'))           # inclusive
    q = (request.args.get('q') or '').strip()

    # Ordenação
    sort = (request.args.get('sort') or '').strip()
    dir_ = (request.args.get('dir')  or 'desc').lower()
    if dir_ not in ('asc', 'desc'):
        dir_ = 'desc'

    # Listas auxiliares
    empresas = Empresa.query.order_by(Empresa.nome.asc()).all()
    planos_all = PlanoFinanceiro.query.filter_by(ativo=True).order_by(PlanoFinanceiro.nome.asc()).all()
    centros_all = CentroCusto.query.order_by(CentroCusto.empresa_id.asc(), CentroCusto.codigo.asc()).all()
    contas_all = CaixaBanco.query.order_by(CaixaBanco.nome.asc()).all()

    # Query base com onclause explícito (evita AmbiguousForeignKeysError)
    qry = (
        db.session.query(FinanceiroEmpresa)
        .join(Empresa, Empresa.id == FinanceiroEmpresa.empresa_id)
        .outerjoin(PlanoFinanceiro, PlanoFinanceiro.id == FinanceiroEmpresa.plano_financeiro_id)
        .outerjoin(CentroCusto, CentroCusto.id == FinanceiroEmpresa.centro_custo_id)
        .outerjoin(CaixaBanco, CaixaBanco.id == FinanceiroEmpresa.conta_id)
        .outerjoin(Credor, Credor.id == FinanceiroEmpresa.credor_id)
        .outerjoin(FinanceiroAnexo, FinanceiroAnexo.titulo_id == FinanceiroEmpresa.id)
        .options(
            joinedload(FinanceiroEmpresa.empresa),
            joinedload(FinanceiroEmpresa.plano_financeiro),
            joinedload(FinanceiroEmpresa.centro_custo),
            joinedload(FinanceiroEmpresa.conta),
            joinedload(FinanceiroEmpresa.credor),
            joinedload(FinanceiroEmpresa.anexos)
        )
    )

    # Aplicar filtros
    if empresa_id:
        qry = qry.filter(FinanceiroEmpresa.empresa_id == empresa_id)
    if tipo in ('receita', 'despesa'):
        qry = qry.filter(FinanceiroEmpresa.tipo == tipo)
    if status in ('pendente', 'pago', 'recebido'):
        qry = qry.filter(FinanceiroEmpresa.status == status)
    if aprovado == 'sim':
        qry = qry.filter(FinanceiroEmpresa.aprovado.is_(True))
    elif aprovado == 'nao':
        qry = qry.filter(FinanceiroEmpresa.aprovado.is_(False))
    if plano_id:
        qry = qry.filter(FinanceiroEmpresa.plano_financeiro_id == plano_id)
    if centro_id:
        qry = qry.filter(FinanceiroEmpresa.centro_custo_id == centro_id)
    if data_ini:
        qry = qry.filter(FinanceiroEmpresa.data >= data_ini)
    if data_fim:
        qry = qry.filter(FinanceiroEmpresa.data <= data_fim)
    if q:
        like = f'%{q}%'
        qry = qry.filter(or_(
            FinanceiroEmpresa.descricao.ilike(like),
            FinanceiroEmpresa.numero_documento.ilike(like),
            Credor.nome.ilike(like),
            FinanceiroAnexo.original_name.ilike(like),
            FinanceiroAnexo.filename.ilike(like)
        )).distinct()

    # Ordenação
    # Whitelist de colunas
    colmap = {
        'data_vencimento': FinanceiroEmpresa.data_vencimento,
        'valor': FinanceiroEmpresa.valor,
        'status': FinanceiroEmpresa.status,
        'aprovado': FinanceiroEmpresa.aprovado,
    }
    order_col = colmap.get(sort)

    if order_col is None:
        # padrão: por data_vencimento DESC (NULLS LAST), depois id DESC
        qry = qry.order_by(
            FinanceiroEmpresa.data_vencimento.desc().nullslast(),
            FinanceiroEmpresa.id.desc()
        )
    else:
        if dir_ == 'asc':
            primary = order_col.asc()
        else:
            primary = order_col.desc()

        # Para data_vencimento, manter NULLS LAST para leitura mais natural
        if order_col.key == 'data_vencimento':
            primary = primary.nullslast()

        # amarra desempate por id desc/asc
        secondary = FinanceiroEmpresa.id.asc() if dir_ == 'asc' else FinanceiroEmpresa.id.desc()

        qry = qry.order_by(primary, secondary)

    # Execução
    itens = qry.all()

    # TOTAIS (mesmos filtros)
    base_receita = db.session.query(func.coalesce(func.sum(
        case((FinanceiroEmpresa.tipo == 'receita', FinanceiroEmpresa.valor), else_=0)
    ), 0))
    base_despesa = db.session.query(func.coalesce(func.sum(
        case((FinanceiroEmpresa.tipo == 'despesa', FinanceiroEmpresa.valor), else_=0)
    ), 0))

    def aplicar_filtros(base_q):
        if empresa_id: base_q = base_q.filter(FinanceiroEmpresa.empresa_id == empresa_id)
        if tipo in ('receita','despesa'): base_q = base_q.filter(FinanceiroEmpresa.tipo == tipo)
        if status in ('pendente','pago','recebido'): base_q = base_q.filter(FinanceiroEmpresa.status == status)
        if aprovado == 'sim': base_q = base_q.filter(FinanceiroEmpresa.aprovado.is_(True))
        elif aprovado == 'nao': base_q = base_q.filter(FinanceiroEmpresa.aprovado.is_(False))
        if plano_id: base_q = base_q.filter(FinanceiroEmpresa.plano_financeiro_id == plano_id)
        if centro_id: base_q = base_q.filter(FinanceiroEmpresa.centro_custo_id == centro_id)
        if data_ini: base_q = base_q.filter(FinanceiroEmpresa.data >= data_ini)
        if data_fim: base_q = base_q.filter(FinanceiroEmpresa.data <= data_fim)
        if q:
            like = f'%{q}%'
            base_q = base_q.filter(or_(
                FinanceiroEmpresa.descricao.ilike(like),
                FinanceiroEmpresa.numero_documento.ilike(like)
            ))
        return base_q

    total_receitas = aplicar_filtros(base_receita).scalar()
    total_despesas = aplicar_filtros(base_despesa).scalar()
    saldo = (total_receitas or 0) - (total_despesas or 0)

    return render_template(
        'empresa_financeiro_listar.html',
        itens=itens,
        empresas=empresas, planos_all=planos_all, centros_all=centros_all,
        contas_all=contas_all,
        empresa_id=empresa_id, tipo=tipo, status=status, aprovado=aprovado,
        plano_id=plano_id, centro_id=centro_id, data_ini=data_ini, data_fim=data_fim,
        q=q, sort=sort, dir=dir_,
        total_receitas=total_receitas, total_despesas=total_despesas, saldo=saldo
    )
    
@app.route('/empresa/financeiro/<int:lanc_id>/atualizar-status-data', methods=['POST'], endpoint='empresa_financeiro_atualizar_status_data')
@login_required
def empresa_financeiro_atualizar_status_data(lanc_id):
    titulo = db.session.get(FinanceiroEmpresa, lanc_id)
    if not titulo:
        flash('Lançamento não encontrado.', 'warning')
        return redirect(url_for('empresa_financeiro_listar'))

    if titulo.aprovado is None:
        titulo.aprovado = False

    pode_editar_campos = bool(titulo.aprovado) and ((titulo.status or '').lower() == 'pendente')

    novo_status = (request.form.get('status') or '').lower().strip()
    if novo_status not in ('pendente', 'pago', 'recebido'):
        flash('Status inválido.', 'danger')
        return redirect(request.form.get('next') or url_for('empresa_financeiro_listar'))

    req_data_liq  = request.form.get('data_liquidado')
    nova_data_liq = _parse_date(req_data_liq) if req_data_liq else None

    req_juros = (request.form.get('juros') or '').strip()
    novo_juros = _parse_decimal_br(req_juros) if req_juros else None
    if novo_juros is None:
        novo_juros = Decimal('0.00')

    # upload do comprovante de BAIXA (único campo no form)
    comp_file = request.files.get('comprovante_pgto')
    novo_comp_filename, abs_novo_comp, abs_comp_antigo = None, None, None
    if comp_file and comp_file.filename:
        if not _allowed_file(comp_file.filename):
            flash('Tipo de arquivo não permitido. Envie PDF/JPG/PNG/GIF/WEBP/HEIC.', 'warning')
            return redirect(request.form.get('next') or url_for('empresa_financeiro_listar'))
        try:
            base_dir = _ensure_comprovantes_dir()
            novo_comp_filename = _unique_name(comp_file.filename)
            abs_novo_comp = os.path.join(base_dir, novo_comp_filename)
            comp_file.save(abs_novo_comp)

            # Se já havia comprovante de BAIXA, prepara remoção depois do commit (compat)
            antigo = getattr(titulo, 'comprovante_baixa_arquivo', None)
            if antigo:
                abs_comp_antigo = os.path.join(base_dir, os.path.basename(antigo))
        except Exception as e:
            print('Erro ao salvar comprovante de pagamento:', e)
            flash('Falha ao salvar o comprovante de pagamento.', 'danger')
            return redirect(request.form.get('next') or url_for('empresa_financeiro_listar'))

    # movimento já existente?
    mov_exist = MovimentoCaixaBanco.query.filter_by(
        origem='financeiro_empresa', referencia_id=titulo.id
    ).first()

    try:
        if not pode_editar_campos and novo_status != 'pendente':
            flash('Não é permitido atualizar este lançamento por aqui.', 'warning')
            # rollback de arquivo novo salvo, se houve
            if abs_novo_comp and os.path.isfile(abs_novo_comp):
                try: os.remove(abs_novo_comp)
                except Exception: pass
            return redirect(request.form.get('next') or url_for('empresa_financeiro_listar'))

        titulo.status = novo_status

        if pode_editar_campos:
            if novo_status in ('pago', 'recebido'):
                titulo.data_liquidado = nova_data_liq or titulo.data
            else:
                titulo.data_liquidado = None
            titulo.juros = novo_juros

            # aplica o novo comprovante de BAIXA no campo compat + registra em financeiro_anexos
            if novo_comp_filename:
                titulo.comprovante_baixa_arquivo = novo_comp_filename
                db.session.add(FinanceiroAnexo(
                    titulo_id=titulo.id,
                    tipo='baixa',
                    filename=novo_comp_filename,
                    original_name=comp_file.filename
                ))

        # sincroniza movimento de caixa pelo total (valor + juros)
        if titulo.status in ('pago', 'recebido') and titulo.conta_id:
            data_mov = titulo.data_liquidado or titulo.data
            valor_total = (titulo.valor or Decimal('0')) + (titulo.juros or Decimal('0'))
            if mov_exist:
                mov_exist.conta_id = titulo.conta_id
                mov_exist.data = data_mov
                mov_exist.tipo = 'saida' if titulo.tipo == 'despesa' else 'entrada'
                mov_exist.descricao = f'{titulo.tipo.capitalize()} - {titulo.descricao}'
                mov_exist.valor = valor_total
            else:
                db.session.add(MovimentoCaixaBanco(
                    conta_id=titulo.conta_id,
                    data=data_mov,
                    tipo='saida' if titulo.tipo == 'despesa' else 'entrada',
                    descricao=f'{titulo.tipo.capitalize()} - {titulo.descricao}',
                    valor=valor_total,
                    origem='financeiro_empresa',
                    referencia_id=titulo.id
                ))
        else:
            if mov_exist:
                db.session.delete(mov_exist)

        db.session.commit()

        # remove o comprovante antigo (se foi substituído)
        if abs_comp_antigo and os.path.isfile(abs_comp_antigo):
            try: os.remove(abs_comp_antigo)
            except Exception: pass

        flash('Status/liquidação/juros atualizados com sucesso.', 'success')

    except Exception as e:
        db.session.rollback()
        print('Erro ao atualizar status/liquidação/juros:', e)

        # se salvamos arquivo novo e deu erro, apaga-o
        if abs_novo_comp and os.path.isfile(abs_novo_comp):
            try: os.remove(abs_novo_comp)
            except Exception: pass

        flash('Erro ao atualizar status/liquidação.', 'danger')

    return redirect(request.form.get('next') or url_for('empresa_financeiro_listar'))
    
@app.route('/empresa/financeiro/<int:lanc_id>/toggle-aprovado', methods=['POST'], endpoint='empresa_financeiro_toggle_aprovado')
@login_required
def empresa_financeiro_toggle_aprovado(lanc_id):
    # só quem é aprovador pode usar
    if not getattr(current_user, 'pode_aprovar_financeiro', False):
        flash('Você não tem permissão para aprovar lançamentos.', 'warning')
        next_url = request.form.get('next') or request.referrer or url_for('empresa_financeiro_listar')
        return redirect(next_url)

    lanc = db.session.get(FinanceiroEmpresa, lanc_id)
    if not lanc:
        flash('Lançamento não encontrado.', 'warning')
        return redirect(url_for('empresa_financeiro_listar'))

    try:
        lanc.aprovado = not bool(lanc.aprovado)
        db.session.commit()
        flash('Lançamento aprovado.' if lanc.aprovado else 'Lançamento reprovado.', 'success')
    except Exception as e:
        db.session.rollback()
        print('Erro ao alternar aprovação:', e)
        flash('Erro ao salvar aprovação.', 'danger')

    next_url = request.form.get('next') or request.referrer or url_for('empresa_financeiro_listar')
    return redirect(next_url)

@app.route('/clientes_operacionais/novo', methods=['GET', 'POST'])
@login_required
def cadastrar_cliente_operacional():
    empresas = Empresa.query.order_by(Empresa.nome).all()

    if request.method == 'POST':
        empresa_id = request.form.get('empresa_id')
        nome = request.form.get('nome')
        cpf_cnpj = request.form.get('cpf_cnpj')
        endereco = request.form.get('endereco')
        email = request.form.get('email')
        telefone = request.form.get('telefone')

        if not nome or not empresa_id:
            flash('Nome e empresa são obrigatórios.', 'danger')
            return redirect(url_for('cadastrar_cliente_operacional'))

        try:
            empresa_id = int(empresa_id)
        except (TypeError, ValueError):
            flash('Empresa inválida.', 'danger')
            return redirect(url_for('cadastrar_cliente_operacional')) 

        novo_cliente = ClienteOperacional(
            empresa_id=empresa_id,
            nome=nome.strip(),
            cpf_cnpj=cpf_cnpj.strip() if cpf_cnpj else None,
            endereco=endereco.strip() if endereco else None,
            email=email.strip() if email else None,
            telefone=telefone.strip() if telefone else None,
            ativo=True,
            criado_em=datetime.now()
        )

        try:
            db.session.add(novo_cliente)
            db.session.commit()
            flash('Cliente cadastrado com sucesso!', 'success')
            return redirect(url_for('listar_clientes_operacionais'))
        except IntegrityError as ie:
            db.session.rollback()
            flash('Já existe um cliente com este CPF/CNPJ nesta empresa.', 'warning')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar cliente: {e}', 'danger')

    return render_template('cadastrar_clientes_operacionais.html', empresas=empresas)

@app.route('/clientes_operacionais')
@login_required
def listar_clientes_operacionais():
    clientes = ClienteOperacional.query.order_by(ClienteOperacional.nome).all()
    return render_template('listar_clientes_operacionais.html', clientes=clientes)

@app.route('/clientes_operacionais/<int:cliente_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_cliente_operacional(cliente_id):
    cliente = ClienteOperacional.query.get_or_404(cliente_id)
    empresas = Empresa.query.order_by(Empresa.nome).all()

    if request.method == 'POST':
        empresa_id = request.form.get('empresa_id')
        nome = request.form.get('nome')
        cpf_cnpj = request.form.get('cpf_cnpj')
        endereco = request.form.get('endereco')
        email = request.form.get('email')
        telefone = request.form.get('telefone')
        ativo = True if request.form.get('ativo') == 'on' else False

        if not nome or not empresa_id:
            flash('Nome e empresa são obrigatórios.', 'danger')
            return redirect(url_for('editar_cliente_operacional', cliente_id=cliente.id))

        try:
            cliente.empresa_id = int(empresa_id)
        except (TypeError, ValueError):
            flash('Empresa inválida.', 'danger')
            return redirect(url_for('editar_cliente_operacional', cliente_id=cliente.id))

        cliente.nome = nome.strip()
        cliente.cpf_cnpj = cpf_cnpj.strip() if cpf_cnpj else None
        cliente.endereco = endereco.strip() if endereco else None
        cliente.email = email.strip() if email else None
        cliente.telefone = telefone.strip() if telefone else None
        cliente.ativo = ativo
        cliente.atualizado_em = datetime.now()

        try:
            db.session.commit()
            flash('Cliente atualizado com sucesso!', 'success')
            return redirect(url_for('listar_clientes_operacionais'))
        except IntegrityError:
            db.session.rollback()
            flash('Já existe um cliente com este CPF/CNPJ nesta empresa.', 'warning')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao salvar alterações: {e}', 'danger')

    return render_template('editar_clientes_operacionais.html', cliente=cliente, empresas=empresas)

@app.route('/clientes_operacionais/<int:cliente_id>/excluir', methods=['POST'])
@login_required
def excluir_cliente_operacional(cliente_id):
    cliente = ClienteOperacional.query.get_or_404(cliente_id)

    try:
        db.session.delete(cliente)
        db.session.commit()
        flash('Cliente excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir: {e}', 'danger')

    return redirect(url_for('listar_clientes_operacionais'))

@app.route('/centros_custos/novo', methods=['GET', 'POST'])
@login_required
def cadastrar_centro_custo():
    empresas = Empresa.query.order_by(Empresa.nome).all()

    if request.method == 'POST':
        empresa_id = request.form.get('empresa_id')
        cliente_id = request.form.get('cliente_id')
        codigo = request.form.get('codigo')
        nome = request.form.get('nome')
        cpf_cnpj = request.form.get('cpf_cnpj')
        endereco = request.form.get('endereco')
        telefone = request.form.get('telefone')
        email = request.form.get('email')

        # validação básica
        if not empresa_id or not cliente_id or not codigo or not nome:
            flash('Empresa, Cliente, Código e Nome são obrigatórios.', 'danger')
            return redirect(url_for('cadastrar_centro_custo'))

        try:
            empresa_id_int = int(empresa_id)
            cliente_id_int = int(cliente_id)
        except (TypeError, ValueError):
            flash('Empresa ou Cliente inválidos.', 'danger')
            return redirect(url_for('cadastrar_centro_custo'))

        # garantir que o cliente pertence à empresa
        cliente = ClienteOperacional.query.get(cliente_id_int)
        if not cliente or cliente.empresa_id != empresa_id_int:
            flash('Cliente não pertence à empresa selecionada.', 'danger')
            return redirect(url_for('cadastrar_centro_custo'))

        novo_centro = CentroCusto(
            empresa_id=empresa_id_int,
            cliente_id=cliente_id_int,
            codigo=codigo.strip(),
            nome=nome.strip(),
            cpf_cnpj=cpf_cnpj.strip() if cpf_cnpj else None,
            endereco=endereco.strip() if endereco else None,
            telefone=telefone.strip() if telefone else None,
            email=email.strip() if email else None,
            ativo=True,
            criado_em=datetime.now()
        )

        try:
            db.session.add(novo_centro)
            db.session.commit()
            flash('Centro de Custo cadastrado com sucesso!', 'success')
            return redirect(url_for('listar_centros_custos'))
        except IntegrityError:
            db.session.rollback()
            flash('Já existe um Centro com este CÓDIGO nesta empresa.', 'warning')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar centro de custo: {e}', 'danger')

    # GET: só renderiza o form
    return render_template('cadastrar_centro_custo.html', empresas=empresas)

@app.route('/centros_custos')
@login_required
def listar_centros_custos():
    empresa_id = request.args.get('empresa_id', type=int)
    empresas = Empresa.query.order_by(Empresa.nome).all()

    query = (CentroCusto.query
             .join(Empresa, CentroCusto.empresa_id == Empresa.id))
    if empresa_id:
        query = query.filter(CentroCusto.empresa_id == empresa_id)

    centros = query.order_by(CentroCusto.nome).all()
    return render_template('listar_centros_custos.html',
                           centros=centros, empresas=empresas, empresa_id=empresa_id)

@app.route('/centros_custos/<int:cc_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_centro_custo(cc_id):
    cc = CentroCusto.query.get_or_404(cc_id)
    empresas = Empresa.query.order_by(Empresa.nome).all()
    # filtrar clientes por empresa no HTML com JS
    clientes = ClienteOperacional.query.order_by(ClienteOperacional.nome).all()

    if request.method == 'POST':
        empresa_id = request.form.get('empresa_id')
        cliente_id = request.form.get('cliente_id')
        codigo = request.form.get('codigo')
        nome = request.form.get('nome')
        cpf_cnpj = request.form.get('cpf_cnpj')
        endereco = request.form.get('endereco')
        telefone = request.form.get('telefone')
        email = request.form.get('email')
        ativo = True if request.form.get('ativo') == 'on' else False

        if not empresa_id or not cliente_id or not codigo or not nome:
            flash('Empresa, Cliente, Código e Nome são obrigatórios.', 'danger')
            return redirect(url_for('editar_centro_custo', cc_id=cc.id))

        try:
            cc.empresa_id = int(empresa_id)
            cc.cliente_id = int(cliente_id)
        except (TypeError, ValueError):
            flash('Empresa ou Cliente inválidos.', 'danger')
            return redirect(url_for('editar_centro_custo', cc_id=cc.id))

        cc.codigo = codigo.strip()
        cc.nome = nome.strip()
        cc.cpf_cnpj = cpf_cnpj.strip() if cpf_cnpj else None
        cc.endereco = endereco.strip() if endereco else None
        cc.telefone = telefone.strip() if telefone else None
        cc.email = email.strip() if email else None
        cc.ativo = ativo
        cc.atualizado_em = datetime.now()

        try:
            db.session.commit()
            flash('Centro de Custo atualizado!', 'success')
            return redirect(url_for('listar_centros_custos'))
        except IntegrityError:
            db.session.rollback()
            flash('Já existe este CÓDIGO nesta empresa.', 'warning')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao salvar: {e}', 'danger')

    return render_template('editar_centro_custo.html',
                           cc=cc, empresas=empresas, clientes=clientes)

@app.route('/centros_custos/<int:cc_id>/excluir', methods=['POST'])
@login_required
def excluir_centro_custo(cc_id):
    cc = CentroCusto.query.get_or_404(cc_id)
    try:
        db.session.delete(cc)
        db.session.commit()
        flash('Centro de Custo excluído.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir: {e}', 'danger')
    return redirect(url_for('listar_centros_custos'))

@app.route('/api/empresas/<int:empresa_id>/clientes', methods=['GET'])
@login_required
def api_clientes_por_empresa(empresa_id):
    clientes = (ClienteOperacional.query
                .filter_by(empresa_id=empresa_id, ativo=True)
                .order_by(ClienteOperacional.nome)
                .with_entities(ClienteOperacional.id, ClienteOperacional.nome)
                .all())
    return jsonify([{"id": c.id, "nome": c.nome} for c in clientes])

@app.route('/planos_financeiros/novo', methods=['GET', 'POST'])
@login_required
def cadastrar_plano_financeiro():
    if request.method == 'POST':
        nome = request.form.get('nome')
        descricao = request.form.get('descricao')
        ativo = True if request.form.get('ativo') == 'on' else True

        if not nome:
            flash('O nome do plano é obrigatório.', 'danger')
            return redirect(url_for('cadastrar_plano_financeiro'))

        plano = PlanoFinanceiro(
            nome=nome.strip(),
            descricao=descricao.strip() if descricao else None,
            ativo=ativo
        )
        try:
            db.session.add(plano)
            db.session.commit()
            flash('Plano financeiro cadastrado com sucesso!', 'success')
            return redirect(url_for('listar_planos_financeiros'))
        except IntegrityError:
            db.session.rollback()
            flash('Já existe um plano financeiro com esse nome.', 'warning')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar plano: {e}', 'danger')

    return render_template('cadastrar_plano_financeiro.html')

@app.route('/planos_financeiros')
@login_required
def listar_planos_financeiros():
    planos = PlanoFinanceiro.query.order_by(PlanoFinanceiro.nome).all()
    return render_template('listar_planos_financeiros.html', planos=planos)
    
@app.route('/planos_financeiros/<int:plano_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_plano_financeiro(plano_id):
    plano = PlanoFinanceiro.query.get_or_404(plano_id)

    if request.method == 'POST':
        nome = request.form.get('nome')
        descricao = request.form.get('descricao')
        ativo = True if request.form.get('ativo') == 'on' else False

        if not nome:
            flash('O nome do plano é obrigatório.', 'danger')
            return redirect(url_for('editar_plano_financeiro', plano_id=plano.id))

        plano.nome = nome.strip()
        plano.descricao = descricao.strip() if descricao else None
        plano.ativo = ativo

        try:
            db.session.commit()
            flash('Plano atualizado com sucesso!', 'success')
            return redirect(url_for('listar_planos_financeiros'))
        except IntegrityError:
            db.session.rollback()
            flash('Já existe um plano financeiro com esse nome.', 'warning')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao salvar alterações: {e}', 'danger')

    return render_template('editar_plano_financeiro.html', plano=plano)

@app.route('/planos_financeiros/<int:plano_id>/excluir', methods=['POST'])
@login_required
def excluir_plano_financeiro(plano_id):
    plano = PlanoFinanceiro.query.get_or_404(plano_id)
    try:
        db.session.delete(plano)
        db.session.commit()
        flash('Plano financeiro excluído.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir: {e}', 'danger')
    return redirect(url_for('listar_planos_financeiros'))

@app.route('/empresa/conta_bancaria/cadastrar', methods=['GET', 'POST'], endpoint='empresa_conta_bancaria_cadastrar')
@login_required
def empresa_conta_bancaria_cadastrar():
    empresas = Empresa.query.order_by(Empresa.nome.asc()).all()

    if request.method == 'POST':
        empresa_id = request.form.get('empresa_id', type=int)
        nome = (request.form.get('nome') or '').strip()
        tipo = (request.form.get('tipo') or '').strip()
        saldo_inicial = _parse_decimal_br(request.form.get('saldo_inicial'))
        agencia = (request.form.get('agencia') or '').strip() or None
        conta = (request.form.get('conta') or '').strip() or None
        banco = (request.form.get('banco') or '').strip() or None

        # Validações básicas
        emp = db.session.get(Empresa, empresa_id) if empresa_id else None
        if not emp:
            flash('Selecione uma empresa válida.', 'danger')
            return redirect(url_for('empresa_conta_bancaria_cadastrar'))
        if not nome:
            flash('O nome da conta é obrigatório.', 'danger')
            return redirect(url_for('empresa_conta_bancaria_cadastrar'))
        if not tipo:
            flash('Informe o tipo da conta.', 'danger')
            return redirect(url_for('empresa_conta_bancaria_cadastrar'))

        try:
            conta_banco = CaixaBanco(
                empresa_id=empresa_id,
                nome=nome,
                tipo=tipo,
                saldo_inicial=saldo_inicial or 0,
                saldo_atual=saldo_inicial or 0,
                agencia=agencia,
                conta=conta,
                banco=banco
            )
            db.session.add(conta_banco)
            db.session.commit()
            flash('Conta bancária cadastrada com sucesso!', 'success')
            return redirect(url_for('empresa_contas_listar'))
        except Exception as e:
            db.session.rollback()
            print('Erro ao cadastrar conta bancária:', e)
            flash('Erro ao salvar os dados bancários.', 'danger')
            return redirect(url_for('empresa_conta_bancaria_cadastrar'))

    return render_template('empresa_conta_bancaria_cadastrar.html', empresas=empresas)

# LISTAR CONTAS BANCÁRIAS (com filtros)
@app.route('/empresa/contas', methods=['GET'], endpoint='empresa_contas_listar')
@login_required
def empresa_contas_listar():
    empresa_id = request.args.get('empresa_id', type=int)
    q = (request.args.get('q') or '').strip()

    empresas = Empresa.query.order_by(Empresa.nome.asc()).all()

    qry = CaixaBanco.query
    if empresa_id:
        qry = qry.filter(CaixaBanco.empresa_id == empresa_id)
    if q:
        ilike = f'%{q}%'
        qry = qry.filter(
            db.or_(
                CaixaBanco.nome.ilike(ilike),
                CaixaBanco.banco.ilike(ilike),
                CaixaBanco.agencia.ilike(ilike),
                CaixaBanco.conta.ilike(ilike),
            )
        )

    contas = qry.order_by(CaixaBanco.empresa_id.asc(), CaixaBanco.nome.asc()).all()

    return render_template(
        'empresa_contas_listar.html',
        empresas=empresas,
        contas=contas,
        empresa_id=empresa_id,
        q=q
    )

# EDITAR CONTA BANCÁRIA
@app.route('/empresa/conta_bancaria/<int:conta_id>/editar', methods=['GET', 'POST'], endpoint='empresa_conta_bancaria_editar')
@login_required
def empresa_conta_bancaria_editar(conta_id):
    conta = db.session.get(CaixaBanco, conta_id)
    if not conta:
        flash('Conta não encontrada.', 'warning')
        return redirect(url_for('empresa_contas_listar'))

    empresas = Empresa.query.order_by(Empresa.nome.asc()).all()

    if request.method == 'POST':
        empresa_id = request.form.get('empresa_id', type=int)
        nome = (request.form.get('nome') or '').strip()
        tipo = (request.form.get('tipo') or '').strip()
        banco = (request.form.get('banco') or '').strip() or None
        agencia = (request.form.get('agencia') or '').strip() or None
        conta_num = (request.form.get('conta') or '').strip() or None
        saldo_inicial = _parse_decimal_br(request.form.get('saldo_inicial'))
        saldo_atual = _parse_decimal_br(request.form.get('saldo_atual'))

        emp = db.session.get(Empresa, empresa_id) if empresa_id else None
        if not emp:
            flash('Selecione uma empresa válida.', 'danger')
            return redirect(url_for('empresa_conta_bancaria_editar', conta_id=conta.id))
        if not nome:
            flash('O nome da conta é obrigatório.', 'danger')
            return redirect(url_for('empresa_conta_bancaria_editar', conta_id=conta.id))
        if not tipo:
            flash('Informe o tipo da conta.', 'danger')
            return redirect(url_for('empresa_conta_bancaria_editar', conta_id=conta.id))

        try:
            conta.empresa_id = empresa_id
            conta.nome = nome
            conta.tipo = tipo
            conta.banco = banco
            conta.agencia = agencia
            conta.conta = conta_num
            if saldo_inicial is not None:
                conta.saldo_inicial = saldo_inicial
            if saldo_atual is not None:
                conta.saldo_atual = saldo_atual

            db.session.commit()
            flash('Conta atualizada com sucesso!', 'success')
            return redirect(url_for('empresa_contas_listar', empresa_id=empresa_id))
        except Exception as e:
            db.session.rollback()
            print('Erro ao editar conta bancária:', e)
            flash('Erro ao salvar alterações.', 'danger')
            return redirect(url_for('empresa_conta_bancaria_editar', conta_id=conta.id))

    return render_template('empresa_conta_bancaria_editar.html', conta=conta, empresas=empresas)


# EXCLUIR CONTA BANCÁRIA (impede exclusão se houver movimentos)
@app.route('/empresa/conta_bancaria/<int:conta_id>/excluir', methods=['POST'], endpoint='empresa_conta_bancaria_excluir')
@login_required
def empresa_conta_bancaria_excluir(conta_id):
    conta = db.session.get(CaixaBanco, conta_id)
    if not conta:
        flash('Conta não encontrada.', 'warning')
        return redirect(url_for('empresa_contas_listar'))

    # Verifica movimentos vinculados
    tem_mov = db.session.query(
        db.exists().where(MovimentoCaixaBanco.conta_id == conta.id)
    ).scalar()

    if tem_mov:
        flash('Não é possível excluir: a conta possui movimentos registrados.', 'warning')
        return redirect(url_for('empresa_contas_listar', empresa_id=conta.empresa_id))

    try:
        db.session.delete(conta)
        db.session.commit()
        flash('Conta excluída com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        print('Erro ao excluir conta bancária:', e)
        flash('Erro ao excluir a conta.', 'danger')

    return redirect(url_for('empresa_contas_listar'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
