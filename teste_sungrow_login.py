import requests
import json
from urllib.parse import urljoin

# =============================================================================
# CONFIGURAÇÕES
# =============================================================================

BASE_URL = "https://gateway.isolarcloud.com.hk"  # Datacenter HK

# DADOS DA APLICAÇÃO (Sungrow Developer)
APP_KEY    = "EBE1031E3B716CA93B03CFC3E4093768"       # ex: "EBE1031E3B716CA93B03CFC3E4093768"
SECRET_KEY = "fx52xkkzcey2vecrnkr5v433sjhfa0df"    # ex: "fx52xkkzcey2vecrnkr5v433sjhfa0df"

# CONTA iSolarCloud
USER_ACCOUNT  = "monitoramento@cgrenergia.com.br"      # ex: "monitoramento@cgrenergia.com.br"
USER_PASSWORD = "Cgr@3021"      # ex: "Cgr@3021"

# Nome da usina que você quer consultar
PLANT_NAME_TO_FIND = "5056 Controller"


# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================

def post_to_sungrow(path, payload, method_name, add_auth=None):
    """
    Envia POST para a API Sungrow com:
      - appkey SEMPRE no body
      - token, user_id, org_id se add_auth for um dict com esses campos
      - SECRET_KEY no header (x-access-key)
    """
    url = urljoin(BASE_URL, path)

    body = {
        "appkey": APP_KEY,
    }
    if add_auth:
        body.update({
            "token":   add_auth["token"],
            "user_id": add_auth["user_id"],
            "org_id":  add_auth["org_id"],
        })
    if payload:
        body.update(payload)

    headers = {
        "Content-Type": "application/json",
        "x-access-key": SECRET_KEY,
    }

    print(f"\n>> {method_name}")
    print("URL:", url)
    print("Payload enviado:")
    print(json.dumps(body, indent=2, ensure_ascii=False))

    resp = requests.post(url, json=body, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if str(data.get("result_code")) != "1":
        print(f"❌ {method_name} FALHOU. Código: {data.get('result_code')}, Msg: {data.get('result_msg')}")
        print("Resposta completa:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return None

    print(f"✅ {method_name} OK.")
    return data.get("result_data") or {}


def login():
    """
    Faz login e retorna dict com token, user_id, org_id.
    """
    payload = {
        "user_account":  USER_ACCOUNT,
        "user_password": USER_PASSWORD,
        # appkey já será adicionado em post_to_sungrow
    }

    data = post_to_sungrow(
        "/openapi/login",
        payload=payload,
        method_name="LOGIN",
        add_auth=None,   # login não envia token
    )
    if not data:
        return None

    token   = data.get("token")
    user_id = data.get("user_id")
    org_id  = data.get("user_master_org_id")

    if not token:
        print("❌ Login retornou sem token.")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return None

    print(f"Token (parcial): {token[:15]}...")
    print(f"user_id = {user_id}, org_id = {org_id}")

    return {
        "token": token,
        "user_id": user_id,
        "org_id": org_id,
    }


def get_plant_energy(auth, plant_name):
    """
    Busca a usina pelo nome e retorna today_energy e curr_power.
    Usa o endpoint: /openapi/getPowerStationList
    """
    payload = {
        "curPage": 1,
        "size": 50,
        "ps_name": plant_name,
        "ps_type": "1,3,4,5,6,7,8,9,10,12",
        "valid_flag": "1,2,3",
        "share_type": "0,1,2",
    }

    data = post_to_sungrow(
        "/openapi/getPowerStationList",
        payload=payload,
        method_name="GET_PLANT_LIST",
        add_auth=auth,
    )
    if not data:
        return None

    # normalmente vem em "pageList"
    plants = None
    if isinstance(data, list):
        plants = data
    else:
        plants = data.get("pageList") or data.get("list") or data.get("ps_list")
        if plants is None:
            # fallback: primeira chave que seja lista
            for k, v in data.items():
                if isinstance(v, list):
                    plants = v
                    break
    if not plants:
        print("⚠️ Nenhuma usina encontrada com esse filtro.")
        return None

    print("\n=== USINAS ENCONTRADAS ===")
    for p in plants:
        cap = None
        if isinstance(p.get("total_capcity"), dict):
            cap = p["total_capcity"].get("value")
        print(f"- ps_id={p.get('ps_id')} | nome={p.get('ps_name')} | capacidade={cap} kWp")

    # Vamos pegar a primeira
    plant = plants[0]
    ps_id   = plant.get("ps_id")
    ps_name = plant.get("ps_name")

    today_energy = plant.get("today_energy", {})
    curr_power   = plant.get("curr_power", {})

    today_kwh = float(today_energy.get("value", 0) or 0)
    curr_kw   = float(curr_power.get("value", 0) or 0)

    print("\n=== DADOS DE GERAÇÃO (NÍVEL USINA) ===")
    print(f"Usina: {ps_name} (ps_id={ps_id})")
    print(f" - Geração hoje (today_energy): {today_kwh} {today_energy.get('unit', 'kWh')}")
    print(f" - Potência atual (curr_power): {curr_kw} {curr_power.get('unit', 'kW')}")
    print("=======================================")

    return {
        "ps_id": ps_id,
        "ps_name": ps_name,
        "today_energy_kwh": today_kwh,
        "today_energy_unit": today_energy.get("unit"),
        "curr_power_kw": curr_kw,
        "curr_power_unit": curr_power.get("unit"),
    }


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    try:
        auth = login()
        if not auth:
            raise SystemExit("Login falhou, encerrando.")

        result = get_plant_energy(auth, PLANT_NAME_TO_FIND)
        if not result:
            raise SystemExit("Não foi possível obter dados da usina.")

    except Exception as e:
        print(f"\n❌ Erro inesperado: {e}")

