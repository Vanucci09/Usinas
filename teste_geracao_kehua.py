import os
from fortlev_solar_sdk import FortlevSolarClient

def testar_e_exibir_orcamentos():
    # 1. Recupera as credenciais do seu ambiente
    username = os.getenv("FORTLEV_SOLAR_USERNAME")
    password = os.getenv("FORTLEV_SOLAR_PWD")
    
    if not username or not password:
        print("❌ Erro: Variáveis de ambiente não configuradas.")
        return

    # 2. Inicializa o cliente no modo DEV
    client = FortlevSolarClient(env="DEV")
    
    try:
        print(f"🔐 Autenticando: {username}...")
        client.authenticate(username=username, pwd=password)
        print("✅ Autenticado com sucesso!")
        print("-" * 110)

        # 3. Solicita os orçamentos
        # Ajustei para os parâmetros que você usou no último teste
        print("🔍 Consultando opções de kits para 2.5 kWp em Brasília...")
        orcamentos = client.orders(power=2.5, voltage="220", phase=1)

        if not orcamentos:
            print("⚠️ Nenhuma opção encontrada para estes parâmetros.")
            return

        # 4. Cabeçalho da Tabela
        print(f"{'OPÇÃO':<5} | {'PREÇO FINAL':<15} | {'POTÊNCIA':<8} | {'INVERSOR PRINCIPAL':<40} | {'MÓDULOS'}")
        print("-" * 110)

        # 5. Loop para processar e mostrar cada Order
        for idx, order in enumerate(orcamentos):
            inversor_nome = "N/A"
            detalhe_modulo = "N/A"
            
            # Navega pelos componentes para identificar o que é inversor e o que é placa
            # Pegamos o primeiro kit (pv_kits[0]) de cada ordem
            for item in order.pv_kits[0].pv_kit_components:
                comp = item.component
                if comp.family == 'inverter':
                    inversor_nome = comp.name
                elif comp.family == 'module':
                    detalhe_modulo = f"{item.quantity}x {comp.name}"

            # Formatação de saída
            print(f"{idx + 1:<5} | R$ {order.final_price:>12.2f} | {order.power:<6.2f} kWp | {inversor_nome[:40]:<40} | {detalhe_modulo}")

        print("-" * 110)
        print(f"✅ Total de {len(orcamentos)} opções processadas.")

    except Exception as e:
        print(f"❌ Ocorreu um erro: {e}")

if __name__ == "__main__":
    testar_e_exibir_orcamentos()