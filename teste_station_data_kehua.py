from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import requests
import os

# 🔐 Dados do cliente
API_2CAPTCHA = "a8a517df68cc0cf9cf37d8e976d8be33"
CPF_CNPJ = "25091452000157"
SENHA = "cgr2020"
CODIGO_UNIDADE = "03008200"
MES_REFERENCIA = "07/2025"

# Caminho para salvar o PDF
PASTA_DOWNLOAD = r"\\192.168.65.1\oem"

# 🔗 Dados da página
URL_LOGIN = "https://agenciavirtual.neoenergiabrasilia.com.br/Account/EfetuarLogin"
SITEKEY = "6LdmOIAbAAAAANXdHAociZWz1gqR9Qvy3AN0rJy4"

# 🔧 Opções do navegador
options = Options()
options.add_argument("--start-maximized")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--disable-gpu")
options.add_argument("--disable-infobars")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--no-sandbox")
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")

prefs = {
    "download.default_directory": PASTA_DOWNLOAD,
    "plugins.always_open_pdf_externally": True,
    "download.prompt_for_download": False,
}
options.add_experimental_option("prefs", prefs)
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)

driver = webdriver.Chrome(options=options)

# Desativa navigator.webdriver
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
    "source": """
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined
    })
    """
})

try:
    print("🌐 Acessando página de login...")
    driver.get(URL_LOGIN)
    time.sleep(5)

    print("✍️ Preenchendo CPF/CNPJ e senha...")
    driver.find_element(By.CSS_SELECTOR, "input[placeholder='CPF/CNPJ']").send_keys(CPF_CNPJ)
    driver.find_element(By.CSS_SELECTOR, "input[placeholder='Senha']").send_keys(SENHA)

    print("🎯 Enviando CAPTCHA para 2Captcha...")
    resp = requests.get(f"http://2captcha.com/in.php?key={API_2CAPTCHA}&method=userrecaptcha&googlekey={SITEKEY}&pageurl={URL_LOGIN}")
    if not resp.text.startswith("OK|"):
        raise Exception(f"Erro ao enviar CAPTCHA: {resp.text}")
    request_id = resp.text.split('|')[1]

    print("⏳ Aguardando solução do CAPTCHA...")
    token = ""
    for _ in range(30):
        time.sleep(5)
        check = requests.get(f"http://2captcha.com/res.php?key={API_2CAPTCHA}&action=get&id={request_id}")
        if check.text.startswith("OK|"):
            token = check.text.split('|')[1]
            break

    if not token:
        raise Exception("❌ Falha ao resolver CAPTCHA")

    print("✅ CAPTCHA resolvido!")
    driver.execute_script("document.getElementById('g-recaptcha-response').style.display = 'block';")
    driver.execute_script(f"document.getElementById('g-recaptcha-response').innerHTML = '{token}';")
    driver.execute_script("if (typeof recaptchaCallback === 'function') recaptchaCallback();")
    time.sleep(3)

    print("🚀 Clicando no botão Entrar...")
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

    print("⏳ Aguardando redirecionamento...")
    WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "a.btn")))

    print(f"🔽 Procurando botão da unidade com código: {CODIGO_UNIDADE}")
    botoes = driver.find_elements(By.CSS_SELECTOR, "a.btn")
    for botao in botoes:
        texto = botao.text.strip().replace("-", "").replace(".", "")
        if CODIGO_UNIDADE in texto:
            print(f"✅ Unidade encontrada: {botao.text.strip()}")
            driver.execute_script("arguments[0].click();", botao)
            break
    else:
        raise Exception("❌ Unidade consumidora não encontrada.")

    print("🕵️ Aguardando botão 'Histórico de Consumo' aparecer...")
    historico_btn = WebDriverWait(driver, 20).until(
        EC.element_to_be_clickable((By.XPATH, "//a[contains(@href, 'HistoricoConsumo')]"))
    )
    print("✅ Clicando em 'Histórico de Consumo'...")
    historico_btn.click()

    print(f"🔍 Procurando fatura do mês: {MES_REFERENCIA}...")
    linhas_faturas = WebDriverWait(driver, 30).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "tr"))
    )

    for linha in linhas_faturas:
        if MES_REFERENCIA in linha.text:
            print(f"✅ Fatura encontrada: {linha.text.strip()}")

            try:
                WebDriverWait(driver, 20).until(
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, "div.loader"))
                )
            except:
                print("⚠️ Loader ainda visível, continuando mesmo assim.")

            driver.execute_script("arguments[0].scrollIntoView();", linha)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", linha)
            time.sleep(2)

            link_element = linha.find_element(By.XPATH, ".//a[contains(@href, 'SegundaVia')]")
            link = link_element.get_attribute("href")
            print(f"📥 Acessando link da fatura: {link}")

            driver.get(link)
            time.sleep(5)

            nome_arquivo = f"fatura_{MES_REFERENCIA.replace('/', '_')}.pdf"
            print(f"✅ PDF deve estar salvo na pasta: {PASTA_DOWNLOAD}\\{nome_arquivo}")
            break
    else:
        print("❌ Fatura do mês desejado não encontrada.")

except Exception as e:
    print("❌ Erro:", e)
    driver.save_screenshot("erro_final.png")
    with open("pagina_erro.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)

input("🟢 Pressione Enter para sair...")
driver.quit()
