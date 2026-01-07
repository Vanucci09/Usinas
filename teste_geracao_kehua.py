import os
import json
import time
import random
import requests
from datetime import date
from typing import Dict, Any, Optional, List


BASE_URL = "https://energy.kehua.com.cn"
TIMEOUT = 25

AUTH_CACHE_FILE = "kehua_auth.json"

MAX_RETRIES = 5
BACKOFF_BASE = 0.8
BACKOFF_CAP = 15.0


# === Endpoints que você já confirmou no curl ===
STATION_TYPE_ENDPOINT = "/necp/server-maintenance/station/listStationType"

# === Endpoint típico para listar usinas (já usamos antes) ===
STATION_LIST_ENDPOINT = "/necp/server-maintenance/station/listStationByPage"

# === Lista de candidatos para "geração hoje" / realtime (varia muito por conta da Kehua) ===
ENERGY_ENDPOINTS = [
    "/necp/monitor/station/getStationRealtimeData",
    "/necp/monitor/station/getStationRealTimeData",
    "/necp/monitor/station/getStationStatistics",
    "/necp/monitor/station/getTodayEnergy",
    "/necp/monitor/station/getEnergyToday",
    "/necp/monitor/station/getStationEnergy",
    "/necp/monitor/report/getStationEnergyCurve",
    "/necp/monitor/report/getEnergyCurve",
]


# ============================================================
# EXCEPTIONS
# ============================================================
class KehuaError(Exception):
    pass

class KehuaAuthExpired(KehuaError):
    pass

class KehuaSystemBusy(KehuaError):
    pass


# ============================================================
# AUTH CACHE
# ============================================================
def load_auth_from_cache() -> Optional[Dict[str, str]]:
    if not os.path.exists(AUTH_CACHE_FILE):
        return None
    try:
        with open(AUTH_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        token = (data.get("token") or "").strip()
        sign = (data.get("sign") or "").strip()
        if token and sign:
            return {"token": token, "sign": sign}
        return None
    except Exception:
        return None

def save_auth_to_cache(token: str, sign: str):
    with open(AUTH_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"token": token, "sign": sign, "saved_at": time.time()}, f, ensure_ascii=False, indent=2)

def get_auth_interactive() -> Dict[str, str]:
    print("\n⚠️ Preciso de um token/sign válido.")
    print("Pegue no DevTools (Network → Headers) da requisição do portal Kehua.\n")
    token = input("authorization (KEHUA_TOKEN): ").strip()
    sign = input("sign (KEHUA_SIGN): ").strip()
    if not token or not sign:
        raise SystemExit("❌ Token/sign vazios. Abortei.")
    save_auth_to_cache(token, sign)
    print(f"✅ Salvo em {AUTH_CACHE_FILE}.")
    return {"token": token, "sign": sign}


# ============================================================
# CLIENT
# ============================================================
class KehuaClient:
    def __init__(self, token: str, sign: str):
        self.token = token
        self.sign = sign
        self.session = requests.Session()
        self._apply_headers()

    def _apply_headers(self):
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Connection": "keep-alive",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",

            "Origin": BASE_URL,
            "Referer": BASE_URL + "/customerAgent",

            # ESSENCIAIS
            "authorization": self.token,
            "clientType": "web",
            "locale": "pt-BR",
            "web_version": "3.0.4",
            "sign": self.sign,

            # para form
            "Content-Type": "application/x-www-form-urlencoded",
        })

        # Também pode mandar token como cookie (igual seu curl), ajuda em alguns cenários:
        self.session.cookies.set("token", self.token)

    def update_auth(self, token: str, sign: str):
        self.token = token
        self.sign = sign
        self._apply_headers()

    def _sleep_backoff(self, attempt: int):
        delay = min(BACKOFF_CAP, BACKOFF_BASE * (2 ** (attempt - 1)))
        jitter = random.uniform(0, delay * 0.25)
        time.sleep(delay + jitter)

    def request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = BASE_URL + path

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if method.upper() == "GET":
                    r = self.session.get(url, params=payload or {}, timeout=TIMEOUT)
                else:
                    # Kehua usa muito x-www-form-urlencoded
                    r = self.session.post(url, data=payload or {}, timeout=TIMEOUT)

                if r.status_code >= 500:
                    if attempt < MAX_RETRIES:
                        self._sleep_backoff(attempt)
                        continue
                    raise KehuaError(f"HTTP {r.status_code}: {r.text[:300]}")

                data = r.json()
                code = str(data.get("code"))
                msg = data.get("message") or data.get("msg") or ""

                # Seu erro original
                if code == "111005":
                    raise KehuaAuthExpired(msg or "Autenticação expirada")

                # Sistema ocupado
                if code == "120000":
                    if attempt < MAX_RETRIES:
                        self._sleep_backoff(attempt)
                        continue
                    raise KehuaSystemBusy(msg or "Sistema ocupado")

                return data

            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt < MAX_RETRIES:
                    self._sleep_backoff(attempt)
                    continue
                raise KehuaError(f"Falha de rede: {e}")

        raise KehuaError("Falha inesperada")

    # --------------------------------------------------------
    # API METHODS
    # --------------------------------------------------------
    def list_station_types(self) -> List[Dict[str, Any]]:
        resp = self.request("POST", STATION_TYPE_ENDPOINT, payload={})
        # geralmente vem em resp["data"]
        data = resp.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return []

    def list_stations(self, page_size: int = 50) -> List[Dict[str, Any]]:
        payload = {
            "pageNumber": 1,
            "pageSize": page_size,
            "stationName": "",
            "stationType": "",
            "stationStatus": "",
            "customerId": "",
            "addressTag": "",
            "companyName": "",
            "applicationScenario": "",
        }
        resp = self.request("POST", STATION_LIST_ENDPOINT, payload=payload)
        return resp["data"]["result"]

    def try_energy_endpoints(self, station: Dict[str, Any]) -> List[Dict[str, Any]]:
        station_id = station.get("stationId")
        today = date.today().strftime("%Y-%m-%d")

        payloads = [
            {"stationId": station_id},
            {"stationId": station_id, "date": today},
            {"stationId": station_id, "day": today},
            {"stationId": station_id, "startDate": today, "endDate": today},
        ]

        hits = []
        for ep in ENERGY_ENDPOINTS:
            for payload in payloads:
                try:
                    resp = self.request("POST", ep, payload=payload)
                    txt = json.dumps(resp, ensure_ascii=False).lower()
                    print(f"[OK] {ep} | payload={payload}")

                    if any(k in txt for k in ["energy", "kwh", "elec", "power", "yield", "today"]):
                        hits.append({"endpoint": ep, "payload": payload, "response": resp})

                except KehuaSystemBusy:
                    print(f"[BUSY] {ep}")
                except KehuaAuthExpired:
                    print(f"[AUTH EXPIRED] {ep}")
                    return hits
                except Exception as e:
                    print(f"[ERR] {ep} | {e}")

        return hits


# ============================================================
# BOOTSTRAP
# ============================================================
def build_client() -> KehuaClient:
    token = (os.getenv("KEHUA_TOKEN") or "").strip()
    sign = (os.getenv("KEHUA_SIGN") or "").strip()
    if token and sign:
        return KehuaClient(token, sign)

    cached = load_auth_from_cache()
    if cached:
        print(f"✅ Auth carregada do cache: {AUTH_CACHE_FILE}")
        return KehuaClient(cached["token"], cached["sign"])

    auth = get_auth_interactive()
    return KehuaClient(auth["token"], auth["sign"])


def main():
    client = build_client()

    # 1) tipos
    print("== LISTANDO TIPOS DE USINA (listStationType) ==")
    try:
        types_ = client.list_station_types()
    except KehuaAuthExpired as e:
        print(f"⚠️ {e} — vou pedir token/sign novo e tentar de novo.")
        auth = get_auth_interactive()
        client.update_auth(auth["token"], auth["sign"])
        types_ = client.list_station_types()

    print(f"Tipos retornados: {len(types_)}")
    for t in types_[:20]:
        print("-", t)

    # 2) usinas
    print("\n== LISTANDO USINAS (listStationByPage) ==")
    try:
        stations = client.list_stations()
    except KehuaAuthExpired as e:
        print(f"⚠️ {e} — vou pedir token/sign novo e tentar de novo.")
        auth = get_auth_interactive()
        client.update_auth(auth["token"], auth["sign"])
        stations = client.list_stations()

    print(f"Total: {len(stations)}")
    for s in stations:
        print(f"- {s.get('stationId')} | {s.get('stationName')} | cap={s.get('capacity')}")

    if not stations:
        print("Nenhuma usina retornada.")
        return

    # 3) tenta achar endpoint de energia
    station = stations[0]
    print(f"\n== TESTANDO GERAÇÃO / REALTIME: {station.get('stationName')} (ID {station.get('stationId')}) ==")
    hits = client.try_energy_endpoints(station)

    print("\n== HITS DE ENERGIA ==")
    if not hits:
        print("Nenhum endpoint retornou dados óbvios de energia.")
        print("➡️ Dica: pegue no DevTools (Network) qual endpoint o portal usa ao abrir o dashboard da usina.")
    else:
        for h in hits:
            print("\n>>>", h["endpoint"])
            print("payload:", h["payload"])
            print("preview:", json.dumps(h["response"], ensure_ascii=False)[:900])


if __name__ == "__main__":
    main()
