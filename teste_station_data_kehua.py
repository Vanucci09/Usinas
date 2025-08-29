# deye_login_and_station_list.py
import os, json, hashlib, requests

BASE_URL = "https://us1-developer.deyecloud.com"
APP_ID   = "202507084069006"
APP_SEC  = "c5e239738a63d1c614e6603f8246a66b"

IDENT = os.getenv("DEYE_EMAIL_OR_USER", "monitoramento@cgrenergia.com.br")  # email/username/mobile
PWD   = os.getenv("DEYE_PASSWORD_PLAIN", "Cgr@2020")  # senha da CONTA DeyeCloud (texto plano)

def sha256_lower(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()

def post(path, body, headers=None):
    url = f"{BASE_URL}{path}"
    h = {"Content-Type":"application/json"}
    if headers: h.update(headers)
    r = requests.post(url, json=body, headers=h, timeout=30)
    print(f"POST {url} -> {r.status_code}")
    print(r.text)
    r.raise_for_status()
    return r.json()

def get_business_token():
    # 1) token "personal"
    body = {"appSecret": APP_SEC, "email": IDENT, "password": sha256_lower(PWD)}
    res  = post(f"/v1.0/account/token?appId={APP_ID}", body)
    personal = res.get("accessToken")
    if not personal:
        raise SystemExit("Falha ao obter token inicial (personal).")

    # 2) descobrir companyId (Business Member)
    info = post("/v1.0/account/info", {}, headers={"Authorization": f"bearer {personal}"})
    orgs = info.get("orgInfoList") or []
    if not orgs:
        # conta pessoal sem organização — alguns endpoints podem falhar
        return personal

    company_id = str(orgs[0]["companyId"])

    # 3) token "business" (inclui companyId)
    body_biz = {"appSecret": APP_SEC, "email": IDENT, "password": sha256_lower(PWD), "companyId": company_id}
    res_biz  = post(f"/v1.0/account/token?appId={APP_ID}", body_biz)
    business = res_biz.get("accessToken")
    if not business:
        raise SystemExit("Falha ao obter token business.")
    return business

def station_list(token, page=1, size=10):
    return post("/v1.0/station/list",
                {"page": page, "size": size},
                headers={"Authorization": f"bearer {token}", "Accept":"application/json"})

if __name__ == "__main__":
    token = get_business_token()
    est   = station_list(token, page=1, size=10)
    print("\nstation/list:", json.dumps(est, indent=2, ensure_ascii=False))
