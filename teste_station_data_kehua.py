# deye_login_and_station_list.py
# -*- coding: utf-8 -*-
import os, json, hashlib, requests, datetime, sys

BASE_URL = "https://us1-developer.deyecloud.com"
APP_ID   = os.getenv("DEYE_APP_ID", "202507084069006")
APP_SEC  = os.getenv("DEYE_APP_SECRET", "c5e239738a63d1c614e6603f8246a66b")
IDENT    = os.getenv("DEYE_EMAIL_OR_USER", "monitoramento@cgrenergia.com.br")
PWD      = os.getenv("DEYE_PASSWORD_PLAIN", "Cgr@2020")  # use env em prod

def sha256_lower(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def post_json(path: str, body: dict, token: str | None = None, extra_hdr: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"bearer {token}"
        headers["Accept"] = "application/json"
    if extra_hdr:
        headers.update(extra_hdr)
    # prints curtos
    slim_hdr = {k: (v[:18]+"…" if k.lower()=="authorization" else v) for k,v in headers.items()}
    print(f"\nPOST {url}\nHEADERS: {slim_hdr}\nBODY   : {body}")
    r = requests.post(url, json=body, headers=headers, timeout=30)
    print("RESP  :", r.status_code, (r.text or "")[:240], "…")
    r.raise_for_status()
    return r.json()

def post_form(path: str, body: dict, token: str | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if token:
        headers["Authorization"] = f"bearer {token}"
        headers["Accept"] = "application/json"
    slim_hdr = {k: (v[:18]+"…" if k.lower()=="authorization" else v) for k,v in headers.items()}
    print(f"\nPOST(form) {url}\nHEADERS: {slim_hdr}\nBODY   : {body}")
    r = requests.post(url, data=body, headers=headers, timeout=30)
    print("RESP  :", r.status_code, (r.text or "")[:240], "…")
    r.raise_for_status()
    return r.json()

def pegar_token_business() -> str:
    # personal
    res = post_json(f"/v1.0/account/token?appId={APP_ID}",
                    {"appSecret": APP_SEC, "email": IDENT, "password": sha256_lower(PWD)})
    personal = res.get("accessToken") or sys.exit("Falha token personal")
    # org
    info = post_json("/v1.0/account/info", {}, token=personal)
    orgs = info.get("orgInfoList") or []
    if not orgs:
        return personal
    company_id = str(orgs[0]["companyId"])
    # business
    res_biz = post_json(f"/v1.0/account/token?appId={APP_ID}",
                        {"appSecret": APP_SEC, "email": IDENT, "password": sha256_lower(PWD), "companyId": company_id})
    return res_biz.get("accessToken") or sys.exit("Falha token business")

def listar_estacoes(token: str, page=1, size=10) -> dict:
    return post_json("/v1.0/station/list", {"page": page, "size": size}, token=token)

# ---------- TENTATIVAS PARA PEGAR kWh DO DIA ----------
def energia_dia_overview(token: str, station_id: int, data_iso: str):
    """/v1.0/station/overview — muitos tenants têm todayEnergy/dayEnergy aqui."""
    try:
        r = post_json("/v1.0/station/overview", {"stationId": station_id, "date": data_iso}, token=token)
        blob = r.get("data", r)
        for k in ("todayEnergy", "dayEnergy", "generationValue"):
            v = blob.get(k) if isinstance(blob, dict) else None
            if isinstance(v, (int, float)): return float(v), "station/overview"
    except Exception as e:
        print("overview falhou:", e)
    return None, None

def energia_dia_station_realtime(token: str, station_id: int, data_iso: str = None):
    """/v1.0/station/realTimeData — alguns retornam dayEnergy junto com potência."""
    try:
        r = post_json("/v1.0/station/realTimeData", {"stationId": station_id}, token=token)
        blob = r.get("data", r)
        for k in ("dayEnergy", "todayEnergy", "generationValue"):
            v = blob.get(k) if isinstance(blob, dict) else None
            if isinstance(v, (int, float)):
                return float(v), "station/realTimeData"
    except Exception as e:
        print("station/realTimeData falhou:", e)
    return None, None

def listar_inversores(token: str, station_id: int):
    """Lista inversores para usar device realtime."""
    for path, body in (
        ("/v1.0/station/device", {"stationId": station_id, "page": 1, "size": 50, "deviceType": "INVERTER"}),
        ("/v1.0/device/list",    {"stationId": station_id, "page": 1, "size": 50}),
    ):
        try:
            r = post_json(path, body, token=token)
            lst = r.get("deviceListItems") or r.get("deviceList") or r.get("data") or []
            if isinstance(lst, list) and lst:
                return lst
        except Exception as e:
            print("listar_inversores falhou:", e)
    return []

def energia_dia_por_dispositivo_realtime(token: str, station_id: int):
    """/v1.0/device/realtime | /v1.0/device/realTime — soma Etdy_ge1 (kWh)."""
    inversores = listar_inversores(token, station_id)
    if not inversores:
        return None, None
    soma = 0.0; achou = False; rota = None
    for d in inversores:
        sn = d.get("deviceSn") or d.get("sn") or d.get("serialNo")
        if not sn: 
            continue
        payload = {"deviceSn": sn}
        for path in ("/v1.0/device/realtime", "/v1.0/device/realTime"):
            try:
                r = post_json(path, payload, token=token)
                # formatos comuns:
                # { data: [{key:"Etdy_ge1", value: X}, ...] }  ou  { paramList: [...] }
                arr = r.get("data") or r.get("paramList") or []
                if isinstance(arr, dict): arr = arr.get("list", [])
                if isinstance(arr, list):
                    for item in arr:
                        if item.get("key") in ("Etdy_ge1", "Etdy"):  # Daily Production (kWh)
                            val = item.get("value")
                            if isinstance(val, (int, float)):
                                soma += float(val); achou = True; rota = path
                                break
            except Exception as e:
                print(f"{path} falhou:", e)
    return (soma if achou else None), rota

def energia_dia_history_form(token: str, station_id: int, data_iso: str):
    """
    Último tiro: alguns ambientes rejeitam JSON e exigem FORM.
    Testa start/end YYYY-MM-DD (sem hora) e yyyyMMddHHmmss.
    """
    tries = [
        {"stationId": str(station_id), "timeType": "2", "startTime": data_iso, "endTime": data_iso},
        {"stationId": str(station_id), "timeType": "2",
         "startTime": data_iso.replace("-", "") + "000000",
         "endTime":   data_iso.replace("-", "") + "235959"},
    ]
    for body in tries:
        try:
            r = post_form("/v1.0/station/history", body, token=token)
            items = r.get("stationDataItems") or r.get("data") or []
            if isinstance(items, list) and items:
                v = items[0].get("generationValue")
                if isinstance(v, (int, float)): return float(v), "station/history (FORM)"
            if isinstance(items, dict):
                v = items.get("generationValue")
                if isinstance(v, (int, float)): return float(v), "station/history (FORM)"
        except Exception as e:
            print("history(form) falhou:", e)
    return None, None

def energia_dia(token: str, station_id: int, data_iso: str):
    for fn in (energia_dia_overview,
               energia_dia_station_realtime,
               energia_dia_por_dispositivo_realtime,
               energia_dia_history_form):
        kwh, via = fn(token, station_id, data_iso) if fn != energia_dia_por_dispositivo_realtime \
                   else fn(token, station_id)
        if kwh is not None:
            return kwh, via
    return None, None

# ---------------- MAIN ----------------
if __name__ == "__main__":
    token = pegar_token_business()
    est   = listar_estacoes(token, page=1, size=10)

    print("\n=== station/list (potência instantânea) ===")
    print(json.dumps(est, indent=2, ensure_ascii=False))

    hoje = datetime.date.today().strftime("%Y-%m-%d")

    for st in est.get("stationList", []):
        sid   = int(st.get("id"))
        nome  = st.get("name")
        pot_w = st.get("generationPower")
        print(f"\n➡️ Usina: {nome} (ID {sid})")
        print(f"   Potência agora: {pot_w} W  (~{(pot_w or 0)/1000:.2f} kW)")

        kwh, via = energia_dia(token, sid, hoje)
        print(f"   Geração do dia: {kwh} kWh  | via: {via}")
