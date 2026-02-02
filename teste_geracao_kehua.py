#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import tempfile
import shutil
from typing import Tuple, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


BASE = "https://energy.kehua.com.cn"
LOGIN_PAGE = f"{BASE}/sellerLogin"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/144.0.0.0 Safari/537.36"
)

HEADLESS = os.getenv("KEHUA_HEADLESS", "0").strip().lower() not in ("0", "false", "no")
KEEP_OPEN = os.getenv("KEHUA_KEEP_OPEN", "0").strip() in ("1", "true", "yes", "sim", "on")
PAGELOAD_TIMEOUT = int(os.getenv("KEHUA_PAGELOAD_TIMEOUT", "60"))
DEFAULT_TIMEOUT = int(os.getenv("KEHUA_TIMEOUT", "60"))
RETRIES = int(os.getenv("KEHUA_RETRIES", "2"))


def _make_driver() -> Tuple[webdriver.Chrome, str]:
    profile_dir = tempfile.mkdtemp(prefix="kehua_profile_")

    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")

    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1366,900")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--lang=pt-BR")
    opts.add_argument(f"--user-agent={UA}")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-features=PasswordLeakDetection,PasswordManagerOnboarding,PasswordManagerRedesign")
    opts.add_argument(f"--user-data-dir={profile_dir}")

    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "profile.default_content_setting_values.notifications": 2,
    }
    opts.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(PAGELOAD_TIMEOUT)
    return driver, profile_dir


def _save_debug(driver: webdriver.Chrome, prefix: str):
    try:
        driver.save_screenshot(f"{prefix}.png")
    except Exception:
        pass
    try:
        with open(f"{prefix}.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    except Exception:
        pass


def _vue_set_value(driver: webdriver.Chrome, el, value: str):
    """
    Vue/iView costuma precisar de eventos (input/change) pra "assumir" o valor.
    """
    driver.execute_script(
        """
        const el = arguments[0];
        const val = arguments[1];
        el.focus();
        el.value = '';
        el.dispatchEvent(new Event('input', {bubbles:true}));
        el.value = val;
        el.dispatchEvent(new Event('input', {bubbles:true}));
        el.dispatchEvent(new Event('change', {bubbles:true}));
        """,
        el, value
    )


def _safe_click(driver: webdriver.Chrome, el) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.08)
        el.click()
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", el)
            return True
        except Exception:
            return False


def _find_login_inputs(driver: webdriver.Chrome):
    """
    Padrão do login:
      - 1 input texto/email
      - 1 input password
    """
    inputs = driver.find_elements(By.CSS_SELECTOR, "input")
    visible = [i for i in inputs if i.is_displayed()]

    user_el = None
    pass_el = None

    for e in visible:
        t = (e.get_attribute("type") or "").lower().strip()
        if t in ("text", "email", "") and user_el is None:
            user_el = e
        elif t == "password" and pass_el is None:
            pass_el = e

    return user_el, pass_el


def _checkbox_is_checked(driver: webdriver.Chrome, input_el) -> bool:
    try:
        return bool(driver.execute_script("return arguments[0].checked === true;", input_el))
    except Exception:
        try:
            return input_el.is_selected()
        except Exception:
            return False


def _force_check_vue(driver: webdriver.Chrome, input_el) -> bool:
    """
    Força "checked=true" + dispara eventos. Isso normalmente resolve quando o clique
    mexe no visual mas o Vue não assume.
    """
    try:
        driver.execute_script(
            """
            const cb = arguments[0];
            cb.checked = true;
            cb.dispatchEvent(new Event('input', {bubbles:true}));
            cb.dispatchEvent(new Event('change', {bubbles:true}));
            cb.dispatchEvent(new MouseEvent('click', {bubbles:true}));
            """,
            input_el
        )
        time.sleep(0.15)
        return _checkbox_is_checked(driver, input_el)
    except Exception:
        return False


def _mark_login_automatico(driver: webdriver.Chrome) -> bool:
    """
    Esse costuma ser um <label class="ivu-checkbox-wrapper ...">Login automático</label>
    """
    try:
        label = driver.find_element(By.XPATH, "//label[contains(., 'Login automático')]")
        # clicar no label geralmente marca
        _safe_click(driver, label)
        time.sleep(0.2)

        # garantir via input interno (se existir)
        cb = None
        try:
            cb = label.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
        except Exception:
            pass

        if cb:
            if _checkbox_is_checked(driver, cb):
                return True
            # tenta clicar no "inner" do ivu-checkbox (melhor que clicar no input)
            try:
                inner = label.find_element(By.CSS_SELECTOR, ".ivu-checkbox-inner")
                _safe_click(driver, inner)
                time.sleep(0.2)
            except Exception:
                pass
            if _checkbox_is_checked(driver, cb):
                return True
            return _force_check_vue(driver, cb)

        return True  # se não achou input, pelo menos tentou clicar no label
    except Exception:
        return False


def _mark_agreement(driver: webdriver.Chrome) -> bool:
    """
    Esse é o chato: ele fica em div.agreement e às vezes o texto/links ficam fora do label.
    A forma mais confiável:
      - achar div.agreement
      - achar o input[type=checkbox].ivu-checkbox-input lá dentro
      - clicar no .ivu-checkbox-inner (ou no wrapper) e, se necessário, forçar via JS
    """
    try:
        agreement_box = driver.find_element(By.CSS_SELECTOR, "div.agreement")
    except Exception:
        return False

    # tenta pegar o input do agreement
    cb = None
    try:
        cb = agreement_box.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
    except Exception:
        cb = None

    if not cb:
        return False

    # 1) tenta clicar no "inner" (melhor que clicar no input)
    clicked_any = False
    for css in (".ivu-checkbox-inner", ".ivu-checkbox", "label.ivu-checkbox-wrapper", "input[type='checkbox']"):
        try:
            el = agreement_box.find_element(By.CSS_SELECTOR, css)
            if _safe_click(driver, el):
                clicked_any = True
                time.sleep(0.25)
                break
        except Exception:
            continue

    if _checkbox_is_checked(driver, cb):
        return True

    # 2) se clicou mas não marcou, força via Vue events
    ok = _force_check_vue(driver, cb)
    if ok:
        return True

    # 3) última tentativa: clicar no texto "Ler e concordar" (às vezes o click handler está nele)
    try:
        txt = agreement_box.find_element(By.XPATH, ".//*[contains(., 'Ler e concordar')]")
        _safe_click(driver, txt)
        time.sleep(0.25)
    except Exception:
        pass

    if _checkbox_is_checked(driver, cb):
        return True

    # 4) força de novo
    return _force_check_vue(driver, cb)


def _click_login(driver: webdriver.Chrome) -> bool:
    """
    Clica no botão Login. Na tela é um <button> com texto 'Login'.
    """
    # tenta botão visível
    try:
        btn = driver.find_element(By.XPATH, "//button[contains(translate(., 'LOGIN', 'login'), 'login')]")
        return _safe_click(driver, btn)
    except Exception:
        pass

    # fallback: ENTER no password
    try:
        pass_el = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        pass_el.send_keys(Keys.ENTER)
        return True
    except Exception:
        return False


def _is_logged_in(driver: webdriver.Chrome) -> bool:
    url = (driver.current_url or "").lower()
    if "/sellerlogin" in url:
        return False
    # normalmente vai pra /index após login
    return any(x in url for x in ("/index", "/monitor", "/monitorow", "/sysinverter"))


def _try_accept_terms_on_index(driver: webdriver.Chrome):
    """
    Quando cai em /index, às vezes aparece modal pedindo "Concordo".
    """
    end = time.time() + 12
    xps = [
        "//*[self::button or self::a or self::span][contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÃÂÉÊÍÓÔÕÚÇ','abcdefghijklmnopqrstuvwxyzáàãâéêíóôõúç'),'concordo')]",
        "//*[self::button or self::a][contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'agree')]",
        "//*[self::button or self::a][contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'accept')]",
    ]
    while time.time() < end:
        for xp in xps:
            els = driver.find_elements(By.XPATH, xp)
            for el in els:
                try:
                    if el.is_displayed() and el.is_enabled():
                        if _safe_click(driver, el):
                            print("✅ Termos em /index: cliquei em 'Concordo'.")
                            return
                except Exception:
                    pass
        time.sleep(0.4)
    print("📝 Modal de termos: não apareceu (ou já estava ok).")


def do_login_once(driver: webdriver.Chrome, user: str, pwd: str) -> bool:
    wait = WebDriverWait(driver, DEFAULT_TIMEOUT)

    print(f"🔐 Abrindo login: {LOGIN_PAGE}")
    driver.get(LOGIN_PAGE)

    # espera os inputs existirem
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input")))
    time.sleep(0.8)

    user_el, pass_el = _find_login_inputs(driver)
    if not user_el or not pass_el:
        print("❌ Não encontrei campos de login.")
        _save_debug(driver, "debug_no_fields")
        return False

    print("✅ Campos encontrados. Preenchendo (Vue)...")
    _vue_set_value(driver, user_el, user)
    _vue_set_value(driver, pass_el, pwd)

    print("☑️ Marcando checkboxes (Login automático + Agreement)...")
    ok_auto = _mark_login_automatico(driver)
    ok_agree = _mark_agreement(driver)
    print(f"   Resultado: login_automatico={ok_auto} | agreement={ok_agree}")

    if not ok_agree:
        print("❌ Agreement NÃO ficou marcado. Salvei debug_agreement_not_marked.png/html")
        _save_debug(driver, "debug_agreement_not_marked")
        return False

    # clica login
    _click_login(driver)

    # aguarda navegar (ou pelo menos mudar algo)
    t0 = time.time()
    while time.time() - t0 < 20:
        if _is_logged_in(driver):
            break
        time.sleep(0.35)

    print(f"🌐 URL final: {driver.current_url}")
    if _is_logged_in(driver):
        print("✅ Login confirmado (saiu de /sellerLogin).")
        if "/index" in (driver.current_url or "").lower():
            _try_accept_terms_on_index(driver)
        return True

    print("❌ Continuou em /sellerLogin após tentar logar.")
    _save_debug(driver, "debug_still_sellerLogin")
    return False


def main():
    user = os.getenv("KEHUA_USER", "").strip()
    pwd = os.getenv("KEHUA_PASS", "").strip()
    if not user or not pwd:
        print("❌ Defina KEHUA_USER e KEHUA_PASS antes de rodar.")
        return

    print(f"🧪 Headless: {HEADLESS} | keep_open={KEEP_OPEN} | pageLoadTimeout={PAGELOAD_TIMEOUT}s | retries={RETRIES}")

    driver, profile_dir = _make_driver()
    ok = False

    try:
        for attempt in range(1, RETRIES + 2):
            print(f"\n🔁 Tentativa {attempt}/{RETRIES+1}")
            ok = do_login_once(driver, user, pwd)
            if ok:
                break
            # pequena pausa e tenta de novo (às vezes o Vue demora pra bindar)
            time.sleep(1.2)

        if ok:
            print("🎉 Pronto. Agora você pode navegar/capturar requests nas páginas internas.")
        else:
            print("🚫 Login NÃO confirmado.")
            print("👉 Abra debug_still_sellerLogin.html/.png pra ver mensagem/validação.")

    finally:
        if KEEP_OPEN:
            print("🧷 KEEP_OPEN=1 -> NÃO vou fechar o Chrome nem apagar o profile_dir.")
            print(f"   Profile: {profile_dir}")
            return

        try:
            driver.quit()
        except Exception:
            pass
        try:
            shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
