import requests
import logging

# Configurações básicas
LOGIN_URL = "https://energy.kehua.com/necp/login/northboundLogin"
REALTIME_URL = "https://energy.kehua.com/necp/monitor/getDeviceRealtimeData"

USUARIO = "monitoramento@cgrenergia.com"
SENHA = "12345678"

def obter_token():
    logging.info("🔐 Fazendo login na API Kehua...")
    payload = {
        "username": USUARIO,
        "password": SENHA,
        "locale": "en"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(LOGIN_URL, data=payload, headers=headers)
    r.raise_for_status()
    resp = r.json()
    token = resp.get("token") or r.headers.get("Authorization")
    return token

def consultar_geracao_realtime(token, device_id):
    headers = {
        "Authorization": token,
        "Content-Type": "application/x-www-form-urlencoded",
        "clienttype": "web"
    }

    payload = {
        "stationId": "31080",
        "companyId": "757",
        "areaCode": "903",
        "deviceId": device_id,
        "deviceType": "00010001",
        "templateId": "1041"
    }

    r = requests.post(REALTIME_URL, headers=headers, data=payload)
    r.raise_for_status()
    json_resp = r.json()

    if json_resp.get("code") == "0":
        data = json_resp.get("data", {})
        print(f"\n📟 Inversor {device_id}:")
        print(f"📈 dayElec (Energia do dia): {data.get('dayElec')} kWh")
        print(f"⚡ gridActivePower (Potência ativa): {data.get('gridActivePower')} kW")
        print(f"🔋 pvActivePower (Potência PV): {data.get('pvActivePower')} kW")
        return data
    else:
        print(f"⚠️ Erro ao consultar dados: {json_resp}")
        return None

if __name__ == "__main__":
    token = obter_token()
    if token:
        consultar_geracao_realtime(token, "551521000050N1100078")
    else:
        print("❌ Token não obtido.")
