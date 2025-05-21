import sqlite3
from app import app, db, Usina

# Conecta ao SQLite
conn = sqlite3.connect('usinas.db')
cursor = conn.cursor()

with app.app_context():
    try:
        # Testar conexão com o PostgreSQL via SQLAlchemy
        engine = db.get_engine()
        conn_pg = engine.connect()
        print("Conexão ao banco SQLAlchemy OK")
        conn_pg.close()
    except Exception as e:
        print("Erro na conexão:", e)

    # Migra usinas
    cursor.execute("SELECT * FROM usinas")
    for row in cursor.fetchall():
        nova_usina = Usina(id=row[0], cc=row[1], nome=row[2], previsao_mensal=row[3])
        db.session.merge(nova_usina)

    db.session.commit()

conn.close()
print("Migração das usinas concluída.")
