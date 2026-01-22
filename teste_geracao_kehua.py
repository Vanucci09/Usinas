import os
import time
import json
import requests
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


TZ_BR = ZoneInfo("America/Sao_Paulo")

BASE = "https://energy.kehua.com.cn"
LOGIN_PAGE = f"{BASE}/sellerLogin"
SYS_INVERTER_PAGE = f"{BASE}/sysInverter"
REALTIME_URL = f"{BASE}/necp/server-maintenance/monitor/getDeviceRealtimeData"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/143.0.0.0 Safari/537.36")

REQUIRED_HEADER_KEYS = ["authorization", "sign", "clienttype", "web_version", "locale"]

def _focus_and_type(driver, el, text: str):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.15)
    try:
        el.click()
    except Exception:
        driver.execute_script("arguments[0].click();", el)
    time.sleep(0.1)
    try:
        el.clear()
    except Exception:
        el.send_keys(Keys.CONTROL, "a")
        el.send_keys(Keys.DELETE)
    el.send_keys(text)

def _mark_required_checkboxes(driver):
    time.sleep(0.4)
    cbs = [cb for cb in driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']") if cb.is_enabled()]
    marked = 0
    for cb in cbs:
        try:
            if not cb.is_selected():
                driver.execute_script("arguments[0].click();", cb)
            if cb.is_selected():
                marked += 1
        except Exception:
            pass
    return marked

def _make_driver(headless: bool):
    options = Options()
    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1366,900")
    options.add_argument(f"--user-agent={UA}")

    # evitar popups/password manager
    options.add_argument("--disable-features=PasswordLeakDetection,AutofillServerCommunication")
    options.add_argument("--disable-save-password-bubble")
    options.add_argument("--disable-notifications")
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "profile.default_content_setting_values.notifications": 2,
    }
    options.add_experimental_option("prefs", prefs)

    # logs de performance para capturar headers reais
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    return webdriver.Chrome(options=options)

def _capture_realtime_headers(driver, timeout_sec=25):
    """
    Captura os headers do portal na request getDeviceRealtimeData.
    Retorna dict headers.
    """
    # limpa logs antigos
    try:
        _ = driver.get_log("performance")
    except Exception:
        pass

    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        logs = driver.get_log("performance")
        for entry in logs:
            try:
                msg = json.loads(entry["message"])["message"]
            except Exception:
                continue

            if msg.get("method") == "Network.requestWillBeSent":
                req = (msg.get("params") or {}).get("request") or {}
                url = req.get("url", "")
                if "getDeviceRealtimeData" in url:
                    h = req.get("headers") or {}
                    return url, h
        time.sleep(0.6)

    return None, None

def get_kehua_session_context(username: str, password: str, headless: bool = True):
    """
    Faz login no portal, captura:
      - cookies
      - headers essenciais (authorization, sign, clientType, web_version, locale)
      - url do endpoint realtime
    """
    driver = _make_driver(headless=headless)
    wait = WebDriverWait(driver, 60)

    try:
        driver.get(LOGIN_PAGE)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']")))

        inputs = [e for e in driver.find_elements(By.CSS_SELECTOR, "input") if e.is_displayed()]
        user_el = None
        pass_el = None
        for e in inputs:
            t = (e.get_attribute("type") or "").lower()
            name = (e.get_attribute("name") or "").lower()
            ph = (e.get_attribute("placeholder") or "").lower()
            if t in ("text", "email"):
                if name == "username" or "mail" in ph or "email" in ph or user_el is None:
                    user_el = e
            if t == "password":
                pass_el = e

        _focus_and_type(driver, user_el, username)
        _focus_and_type(driver, pass_el, password)
        _mark_required_checkboxes(driver)

        # clicar login
        btn = None
        for b in driver.find_elements(By.CSS_SELECTOR, "button"):
            if b.is_displayed() and "login" in ((b.text or "").lower()):
                btn = b
                break
        if btn:
            driver.execute_script("arguments[0].click();", btn)
        else:
            pass_el.send_keys(Keys.ENTER)

        wait.until(lambda d: "monitor" in (d.current_url or "").lower())

        # ir pra sysInverter (gera as chamadas XHR)
        driver.get(SYS_INVERTER_PAGE)
        wait.until(lambda d: "sysInverter" in (d.current_url or ""))

        url, hdr = _capture_realtime_headers(driver, timeout_sec=25)
        if not url or not hdr:
            raise RuntimeError("Não consegui capturar headers do getDeviceRealtimeData.")

        # normaliza keys para minúsculo
        hdr_norm = {str(k).lower(): v for k, v in hdr.items()}

        # monta só os essenciais (mantendo valor original)
        essential = {}
        for k in REQUIRED_HEADER_KEYS:
            if k in hdr_norm:
                essential[k] = hdr_norm[k]

        # alguns vêm como ClientType no log; já normalizamos
        if "clienttype" not in essential and "clientType" in hdr:
            essential["clienttype"] = hdr["clientType"]

        if "authorization" not in essential or "sign" not in essential:
            raise RuntimeError(f"Headers insuficientes capturados: {list(essential.keys())}")

        cookies = driver.get_cookies()

        return {
            "realtime_url": url,
            "headers": essential,   # lower-case keys
            "cookies": cookies
        }

    finally:
        driver.quit()

def call_realtime_dayelec(ctx: dict, payload: dict) -> tuple[float, dict]:
    """
    Faz POST no realtime com cookies + headers capturados.
    Retorna (dayElec, json).
    """
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA})

    # cookies
    for c in ctx["cookies"]:
        sess.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))

    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/x-www-form-urlencoded",
        "referer": SYS_INVERTER_PAGE,
        "origin": BASE,
        # essenciais
        "authorization": ctx["headers"]["authorization"],
        "sign": ctx["headers"]["sign"],
        "clienttype": ctx["headers"].get("clienttype", "web"),
        "web_version": ctx["headers"].get("web_version", "3.0.4"),
        "locale": ctx["headers"].get("locale", "pt-BR"),
    }

    resp = sess.post(ctx["realtime_url"], headers=headers, data=payload, timeout=30)
    j = resp.json()

    if str(j.get("code")) != "0":
        raise RuntimeError(f"Kehua realtime falhou: code={j.get('code')} msg={j.get('message')}")

    # extrair dayElec
    day = 0.0
    data = j.get("data") or {}
    yc_infos = data.get("ycInfos") or data.get("ycInfo") or []
    for grupo in yc_infos:
        dps = grupo.get("dataPoint") or grupo.get("datapoint") or []
        for p in dps:
            if (p.get("property") or p.get("name")) in ("dayElec", "day_elec", "dayEnergy"):
                day = float(p.get("val") or 0)
                break
        if day:
            break

    return day, j
