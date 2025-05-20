import sqlite3
from flask import Flask, render_template, request, redirect, url_for
from datetime import date
from calendar import monthrange
import os
import pandas as pd
from werkzeug.utils import secure_filename
import openpyxl

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Inicializa o banco de dados (executa apenas uma vez)
def init_db():
    with sqlite3.connect('usinas.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS usinas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cc TEXT NOT NULL,
            nome TEXT NOT NULL,
            previsao_mensal REAL
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS geracoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usina_id INTEGER,
            data TEXT,
            energia_kwh REAL,
            FOREIGN KEY (usina_id) REFERENCES usinas(id)
        )''')
        conn.commit()

@app.route('/')
def index():
    return redirect(url_for('cadastrar_usina'))

@app.route('/producao_mensal/<int:usina_id>/<int:ano>/<int:mes>')
def producao_mensal(usina_id, ano, mes):
    with sqlite3.connect('usinas.db') as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        usina_nome = cursor.execute("SELECT nome FROM usinas WHERE id = ?", (usina_id,)).fetchone()[0]
        cursor.execute("""
            SELECT data, energia_kwh 
            FROM geracoes 
            WHERE usina_id = ? AND strftime('%Y-%m', data) = ?
            ORDER BY data
        """, (usina_id, f"{ano:04d}-{mes:02d}"))
        resultados = cursor.fetchall()

        dias_mes = monthrange(ano, mes)[1]
        totais = [0] * dias_mes
        detalhes = []
        soma = 0

        for data_str, energia in resultados:
            dia = int(data_str[-2:])
            totais[dia - 1] = energia
            soma += energia
            detalhes.append({'data': data_str, 'energia_kwh': energia})

        dias_com_dado = len(resultados)
        media_diaria = soma / dias_com_dado if dias_com_dado > 0 else 0
        previsao_total = round(media_diaria * dias_mes, 2)

        usinas = cursor.execute("SELECT id, nome FROM usinas").fetchall()

    return render_template('producao_mensal.html',
                           usina_nome=usina_nome,
                           usina_id=usina_id,
                           ano=ano,
                           mes=mes,
                           usinas=usinas,
                           meses=[str(i+1) for i in range(dias_mes)],
                           totais=totais,
                           detalhes=detalhes,
                           previsao_total=previsao_total,
                           media_diaria=round(media_diaria, 2),
                           soma_total=soma)

@app.route('/cadastrar_usina', methods=['GET', 'POST'])
def cadastrar_usina():
    if request.method == 'POST':
        cc = request.form['cc']
        nome = request.form['nome']
        previsao_mensal = request.form['previsao_mensal']
        with sqlite3.connect('usinas.db') as conn:
            conn.execute("INSERT INTO usinas (cc, nome, previsao_mensal) VALUES (?, ?, ?)", (cc, nome, previsao_mensal))
            conn.commit()
        return redirect(url_for('cadastrar_usina'))
    return render_template('cadastrar_usina.html')

@app.route('/cadastrar_geracao', methods=['GET', 'POST'])
def cadastrar_geracao():
    with sqlite3.connect('usinas.db') as conn:
        conn.row_factory = sqlite3.Row
        usinas = conn.execute("SELECT * FROM usinas").fetchall()

    if request.method == 'POST':
        usina_id = request.form['usina_id']
        data = request.form['data']
        energia = request.form['energia']

        with sqlite3.connect('usinas.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM geracoes WHERE usina_id = ? AND data = ?", (usina_id, data))
            existente = cursor.fetchone()

            if existente:
                return render_template('cadastrar_geracao.html', usinas=usinas,
                                       mensagem="Já existe um registro para esta usina nesta data.")

            cursor.execute("INSERT INTO geracoes (usina_id, data, energia_kwh) VALUES (?, ?, ?)",
                           (usina_id, data, energia))
            conn.commit()
        return redirect(url_for('cadastrar_geracao'))

    return render_template('cadastrar_geracao.html', usinas=usinas)

@app.route('/listar_geracoes')
def listar_geracoes():
    data_inicio_default = date.today().replace(day=1).isoformat()
    data_fim_default = date.today().isoformat()

    usinas = []
    geracoes = []

    with sqlite3.connect('usinas.db') as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        usinas = cursor.execute("SELECT * FROM usinas").fetchall()

        data_inicio = request.args.get('data_inicio', data_inicio_default)
        data_fim = request.args.get('data_fim', data_fim_default)
        usina_id = request.args.get('usina_id')

        query = '''
            SELECT g.id, u.nome, g.data, g.energia_kwh
            FROM geracoes g
            JOIN usinas u ON g.usina_id = u.id
            WHERE g.data BETWEEN ? AND ?
        '''
        params = [data_inicio, data_fim]

        if usina_id:
            query += " AND u.id = ?"
            params.append(usina_id)

        query += " ORDER BY g.data ASC"
        geracoes = cursor.execute(query, params).fetchall()

    return render_template(
        'listar_geracoes.html',
        geracoes=geracoes,
        usinas=usinas,
        data_inicio_default=data_inicio_default,
        data_fim_default=data_fim_default
    )

@app.route('/editar_geracao/<int:id>', methods=['GET', 'POST'])
def editar_geracao(id):
    with sqlite3.connect('usinas.db') as conn:
        cursor = conn.cursor()

        if request.method == 'POST':
            nova_energia = request.form['energia']
            cursor.execute("UPDATE geracoes SET energia_kwh = ? WHERE id = ?", (nova_energia, id))
            conn.commit()
            return redirect(url_for('listar_geracoes'))

        cursor.execute('''
            SELECT g.id, u.nome, g.data, g.energia_kwh
            FROM geracoes g
            JOIN usinas u ON g.usina_id = u.id
            WHERE g.id = ?
        ''', (id,))
        geracao = cursor.fetchone()

    return render_template('editar_geracao.html', geracao=geracao)

@app.route('/excluir_geracao/<int:id>', methods=['GET'])
def excluir_geracao(id):
    with sqlite3.connect('usinas.db') as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM geracoes WHERE id = ?", (id,))
        conn.commit()
    return redirect(url_for('listar_geracoes'))

@app.route('/consulta')
def consulta():
    usina_id = request.args.get('usina_id', '')
    data_inicio = request.args.get('data_inicio', date.today().replace(day=1).isoformat())
    data_fim = request.args.get('data_fim', date.today().isoformat())

    with sqlite3.connect('usinas.db') as conn:
        cursor = conn.cursor()

        query = '''
            SELECT u.id, u.nome, u.previsao_mensal, g.data, g.energia_kwh
            FROM geracoes g
            JOIN usinas u ON g.usina_id = u.id
            WHERE g.data BETWEEN ? AND ?
        '''
        params = [data_inicio, data_fim]

        if usina_id:
            query += " AND u.id = ?"
            params.append(usina_id)

        query += " ORDER BY g.data ASC"
        resultados = cursor.execute(query, params).fetchall()
        usinas = conn.execute("SELECT * FROM usinas").fetchall()

    total = 0
    data = []
    dias = []
    geracoes = []
    previsoes = []

    for id_usina, nome, previsao_mensal, data_geracao, energia in resultados:
        dias_no_mes = monthrange(int(data_geracao[:4]), int(data_geracao[5:7]))[1]
        previsao_diaria = previsao_mensal / dias_no_mes
        producao_negativa = energia < previsao_diaria

        data.append({
            'nome': nome,
            'data': data_geracao,
            'energia_kwh': energia,
            'previsao_diaria': previsao_diaria,
            'producao_negativa': producao_negativa,
        })

        dias.append(data_geracao)
        geracoes.append(energia)
        previsoes.append(previsao_diaria)
        total += energia

    return render_template(
        'consulta.html',
        resultados=data,
        total=total,
        usinas=usinas,
        usina_id=usina_id,
        data_inicio=data_inicio,
        data_fim=data_fim,
        dias=dias,
        geracoes=geracoes,
        previsoes=previsoes
    )

def formato_brasileiro(valor):
    return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

app.jinja_env.filters['formato_brasileiro'] = formato_brasileiro

@app.route('/importar_planilha', methods=['GET', 'POST'])
def importar_planilha():
    mensagem = ''
    with sqlite3.connect('usinas.db') as conn:
        conn.row_factory = sqlite3.Row
        usinas = conn.execute("SELECT * FROM usinas").fetchall()

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
                    with sqlite3.connect('usinas.db') as conn:
                        cursor = conn.cursor()
                        inseridos = 0
                        duplicados = 0

                        for _, linha in df.iterrows():
                            data = str(linha['data'])[:10]
                            energia = linha['energia_kwh']
                            cursor.execute("SELECT id FROM geracoes WHERE usina_id = ? AND data = ?", (usina_id, data))
                            if cursor.fetchone():
                                duplicados += 1
                                continue

                            cursor.execute("INSERT INTO geracoes (usina_id, data, energia_kwh) VALUES (?, ?, ?)",
                                           (usina_id, data, energia))
                            inseridos += 1
                        conn.commit()

                    mensagem = f"{inseridos} registros inseridos. {duplicados} ignorados por já existirem."
            except Exception as e:
                mensagem = f"Erro ao processar a planilha: {str(e)}"
        else:
            mensagem = "Envie um arquivo .xlsx ou .xls válido."

    return render_template('importar_planilha.html', mensagem=mensagem, usinas=usinas)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
