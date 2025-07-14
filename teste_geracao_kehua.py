import requests
import logging
from dotenv import load_dotenv
import os

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

LOGIN_URL = "https://energy.kehua.com/necp/login/northboundLogin"
REALTIME_URL = "https://energy.kehua.com/necp/monitor/getDeviceRealtimeData"

USUARIO = os.getenv("KEHUA_USERNAME", "monitoramento@cgrenergia.com")
SENHA = os.getenv("KEHUA_PASSWORD", "12345678")

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
    logging.info("📦 Resposta JSON: %s", resp)
    token = resp.get("token") or r.headers.get("Authorization")
    return token

def consultar_geracao_realtime(token):
    headers = {
        "Authorization": token,
        "Content-Type": "application/x-www-form-urlencoded",
        "clienttype": "web"
    }

    payload = {
        "stationId": "31080",
        "companyId": "757",
        "areaCode": "903",
        "deviceId": "16872",
        "deviceType": "00010001",
        "templateId": "1041"
    }

    r = requests.post(REALTIME_URL, headers=headers, data=payload)
    r.raise_for_status()
    json_resp = r.json()

    if json_resp.get("code") == "0":
        logging.info("✅ Geração em tempo real obtida com sucesso!")
        print(json_resp)
    else:
        logging.warning("⚠️ Código de resposta: %s - %s", json_resp.get("code"), json_resp.get("message"))

if __name__ == "__main__":
    token = obter_token()
    if token:
        consultar_geracao_realtime(token)
    else:
        logging.error("❌ Token não obtido.")
