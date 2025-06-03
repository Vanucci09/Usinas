from flask import Flask, render_template, request, redirect, url_for, jsonify, make_response, send_file
from datetime import date, datetime, timedelta
from calendar import monthrange
import os
import pandas as pd
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import Numeric, text, func, extract
from decimal import Decimal, ROUND_HALF_UP
import fitz
from PIL import Image
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user


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

class Geracao(db.Model):
    __tablename__ = 'geracoes'
    id = db.Column(db.Integer, primary_key=True)
    usina_id = db.Column(db.Integer, db.ForeignKey('usinas.id'))
    data = db.Column(db.Date, nullable=False)
    energia_kwh = db.Column(db.Float)

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
    
class Usuario(db.Model, UserMixin):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String, nullable=False)
    email = db.Column(db.String, unique=True, nullable=False)
    senha_hash = db.Column(db.String, nullable=False)
    pode_cadastrar_geracao = db.Column(db.Boolean, default=False)
    pode_cadastrar_cliente = db.Column(db.Boolean, default=False)
    pode_cadastrar_fatura = db.Column(db.Boolean, default=False)

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
def cadastrar_usina():
    if request.method == 'POST':
        cc = request.form['cc']
        nome = request.form['nome']
        potencia = request.form['potencia']
        ano_atual = date.today().year

        nova_usina = Usina(cc=cc, nome=nome, potencia_kw=potencia)
        db.session.add(nova_usina)
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

    return render_template('cadastrar_usina.html')

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
        ano_faturamento_liquido=ano_liquido
    )


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
def cadastrar_rateio():
    usinas = Usina.query.all()
    clientes = Cliente.query.all()

    if request.method == 'POST':
        usina_id = request.form['usina_id']
        cliente_id = request.form['cliente_id']
        percentual = float(request.form['percentual'])
        tarifa_kwh = float(request.form['tarifa_kwh'])

        rateio = Rateio(usina_id=usina_id, cliente_id=cliente_id,
                        percentual=percentual, tarifa_kwh=tarifa_kwh)
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
            cliente_id = int(request.form['cliente_id'])
            usina_id = int(request.form['usina_id'])
            mes = int(request.form['mes'])
            ano = int(request.form['ano'])

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

            identificador = f"{cliente_id}-{mes:02d}-{ano}"

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
                mensagem = 'Fatura cadastrada com sucesso.'
        except Exception as e:
            db.session.rollback()
            mensagem = f"Erro ao salvar fatura: {str(e)}"

    return render_template('faturamento.html', usinas=usinas, clientes=clientes, mensagem=mensagem)

@app.route('/clientes_por_usina/<int:usina_id>')
def clientes_por_usina(usina_id):
    clientes = Cliente.query.filter_by(usina_id=usina_id).all()
    return jsonify([{'id': c.id, 'nome': c.nome} for c in clientes])

@app.route('/faturas')
def listar_faturas():
    usina_id = request.args.get('usina_id', type=int)
    mes = request.args.get('mes', type=int)
    ano = request.args.get('ano', type=int)

    query = FaturaMensal.query.join(Cliente).join(Usina)

    if usina_id:
        query = query.filter(Usina.id == usina_id)
    if mes:
        query = query.filter(FaturaMensal.mes_referencia == mes)
    if ano:
        query = query.filter(FaturaMensal.ano_referencia == ano)

    faturas = query.order_by(FaturaMensal.ano_referencia.desc(), FaturaMensal.mes_referencia.desc()).all()
    usinas = Usina.query.all()
    anos = sorted({f.ano_referencia for f in FaturaMensal.query.all()}, reverse=True)

    return render_template('listar_faturas.html', faturas=faturas, usinas=usinas, anos=anos,
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

@app.route('/relatorio/<int:fatura_id>')
def relatorio_fatura(fatura_id):
    
    fatura = FaturaMensal.query.get_or_404(fatura_id)
    cliente = Cliente.query.get(fatura.cliente_id)
    usina = Usina.query.get(cliente.usina_id)

    # Tarifas e dados da fatura atual
    tarifa_base = Decimal(str(fatura.tarifa_neoenergia))
    tarifa_neoenergia_aplicada = tarifa_base if fatura.icms == 20 else tarifa_base * Decimal('1.1023232323')
    consumo_usina = Decimal(str(fatura.consumo_usina))
    valor_conta = Decimal(str(fatura.valor_conta_neoenergia))

    # Tarifa do cliente
    rateio = Rateio.query.filter_by(cliente_id=cliente.id, usina_id=usina.id).first()
    tarifa_cliente = Decimal(str(rateio.tarifa_kwh)) if rateio else Decimal('0')

    # Economia da fatura atual
    valor_usina = consumo_usina * tarifa_cliente
    com_desconto = valor_conta + valor_usina
    sem_desconto = consumo_usina * tarifa_neoenergia_aplicada + valor_conta
    economia = sem_desconto - com_desconto

    # Buscar todas as faturas anteriores do mesmo cliente (exceto a atual)
    faturas_anteriores = FaturaMensal.query.filter(
        FaturaMensal.cliente_id == cliente.id,
        FaturaMensal.id != fatura.id,
        (FaturaMensal.ano_referencia < fatura.ano_referencia) |
        ((FaturaMensal.ano_referencia == fatura.ano_referencia) &
         (FaturaMensal.mes_referencia < fatura.mes_referencia))
    ).all()

    # Somar a economia de cada fatura anterior
    economia_total = Decimal('0')
    for f in faturas_anteriores:
        try:
            tarifa_base_ant = Decimal(str(f.tarifa_neoenergia))
            tarifa_aplicada_ant = tarifa_base_ant if f.icms == 20 else tarifa_base_ant * Decimal('1.1023232323')
            consumo_usina_ant = Decimal(str(f.consumo_usina))
            valor_conta_ant = Decimal(str(f.valor_conta_neoenergia))

            valor_usina_ant = consumo_usina_ant * tarifa_cliente
            com_desconto_ant = valor_conta_ant + valor_usina_ant
            sem_desconto_ant = consumo_usina_ant * tarifa_aplicada_ant + valor_conta_ant

            economia_ant = sem_desconto_ant - com_desconto_ant
            economia_total += economia_ant
        except Exception as e:
            continue  # Ignora se algum dado estiver incompleto

    economia_acumulada = economia + economia_total

    # Ficha de compensação, se houver
    pasta_boletos = os.getenv('BOLETOS_PATH', '/data/boletos')
    pdf_path = os.path.join(pasta_boletos, f"boleto_{fatura.id}.pdf")
    ficha_path = f"static/ficha_compensacao_{fatura.id}.png"

    ficha_compensacao_img = None
    if os.path.exists(pdf_path):
        ficha_compensacao_img = extrair_ficha_compensacao(pdf_path, ficha_path)

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
        ficha_compensacao_img=ficha_compensacao_img
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
def upload_boleto():
    faturas = FaturaMensal.query.order_by(
        FaturaMensal.ano_referencia.desc(), FaturaMensal.mes_referencia.desc()
    ).all()
    mensagem = ''

    if request.method == 'POST':
        fatura_id = request.form.get('fatura_id')
        arquivo = request.files.get('boleto_pdf')

        if not fatura_id or not arquivo:
            mensagem = "Selecione uma fatura e envie um arquivo."
        elif not arquivo.filename.lower().endswith('.pdf'):
            mensagem = "O arquivo deve ser um PDF."
        else:
            # Lê da variável de ambiente (ou usa '/data/boletos' por padrão)
            pasta_boletos = os.getenv('BOLETOS_PATH', '/data/boletos')
            os.makedirs(pasta_boletos, exist_ok=True)

            nome_arquivo = f"boleto_{fatura_id}.pdf"
            caminho = os.path.join(pasta_boletos, nome_arquivo)
            arquivo.save(caminho)

            mensagem = f"Boleto da fatura {fatura_id} enviado com sucesso."

    return render_template('upload_boleto.html', faturas=faturas, mensagem=mensagem)

@app.route('/excluir_fatura/<int:id>', methods=['POST'])
def excluir_fatura(id):
    fatura = FaturaMensal.query.get_or_404(id)
    db.session.delete(fatura)
    db.session.commit()
    return redirect(url_for('listar_faturas'))

@app.route('/extrair_dados_fatura', methods=['POST'])
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

        db.session.commit()
        return redirect(url_for('editar_previsoes', usina_id=usina.id, ano=ano))

    # Preenche os valores existentes no formulário
    previsoes = {p.mes: p.previsao_kwh for p in PrevisaoMensal.query.filter_by(usina_id=usina.id, ano=ano).all()}

    return render_template(
        'editar_previsoes.html',
        usina=usina,
        previsoes=previsoes,
        ano=ano
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

        novo_usuario = Usuario(
            nome=nome,
            email=email,
            pode_cadastrar_geracao=pode_geracao,
            pode_cadastrar_cliente=pode_cliente,
            pode_cadastrar_fatura=pode_fatura
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


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
