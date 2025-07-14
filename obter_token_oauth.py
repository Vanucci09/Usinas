import requests
import json

# Dados do seu app
APP_KEY = "EBE1031E3B716CA93B03CFC3E4093768"
APP_SECRET = "fx52xkkzcey2vecrnkr5v433sjhfa0df"
REDIRECT_URI = "https://example.com/callback"

# Cole aqui o code obtido após autorizar o app
authorization_code = "COLE_SEU_CODE_AQUI"

# Endpoint para obter o token
url = "https://openapi.isolarcloud.com.hk/oauth2/token"

payload = {
    "grant_type": "authorization_code",
    "code": authorization_code,
    "redirect_uri": REDIRECT_URI,
    "client_id": APP_KEY,
    "client_secret": APP_SECRET
}

headers = {
    "Content-Type": "application/json"
}

# Requisição
response = requests.post(url, json=payload, headers=headers)
print("Status:", response.status_code)
print("Resposta:", response.text)

if response.status_code == 200:
    data = response.json()
    access_token = data.get("access_token")
    print("\n✅ Access Token obtido com sucesso:\n", access_token)
else:
    print("\n❌ Falha ao obter token.")
