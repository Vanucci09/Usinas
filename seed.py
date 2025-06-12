from app import app, db, CategoriaDespesa

with app.app_context():
    categorias = [
        "Demanda", "Manutenção", "Seguro", "Contabilidade", "Terreno",
        "Gestão", "Imposto", "Internet", "Co working", "Diversos",
        "Tx Bancárias", "Fundo Reserva"
    ]

    for nome in categorias:
        if not CategoriaDespesa.query.filter_by(nome=nome).first():
            db.session.add(CategoriaDespesa(nome=nome))

    db.session.commit()
    print("Categorias inseridas com sucesso.")
