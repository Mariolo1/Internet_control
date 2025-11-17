#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automatyczny monitor Internetu przez ICMP ping (Linux / Docker).

Teraz z trzema poziomami diagnostyki:
- LAN (brama / router),
- WAN (opcjonalny host typu duckdns – ANPW_WAN_HOST),
- Internet (PUBLIC_HOSTS, np. 1.1.1.1, 8.8.8.8, 9.9.9.9).

Wykrywa:
- brak bramy (NO_GATEWAY),
- problem w LAN (LAN_DOWN),
- brak dostępu do Internetu przy działającym LAN (INTERNET_DOWN),
- raportuje w mailu stany: LAN, WAN, INTERNET.
"""

import os
import time
import subprocess
import logging
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime

PUBLIC_HOSTS = [
    h.strip()
    for h in os.getenv("ANPW_PUBLIC", "1.1.1.1,8.8.8.8,9.9.9.9").split(",")
    if h.strip()
]

WAN_HOST = os.getenv("ANPW_WAN_HOST", "").strip() or None

INTERVAL_SEC = int(os.getenv("ANPW_INTERVAL", "5"))
FAIL_THRESHOLD = int(os.getenv("ANPW_FAIL_THRESHOLD", "3"))
OK_THRESHOLD = int(os.getenv("ANPW_OK_THRESHOLD", "2"))
PING_TIMEOUT_S = int(os.getenv("ANPW_PING_TIMEOUT", "1"))
NOTIFY_ON_START = os.getenv("ANPW_NOTIFY_ON_START", "1") == "1"
ROUTER_REDISCOVER_EVERY = int(os.getenv("ANPW_ROUTER_REDISCOVER_EVERY", "300"))

SMTP_HOST = os.getenv("ANPW_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("ANPW_SMTP_PORT", "587"))
SMTP_USER = os.getenv("ANPW_SMTP_USER", "")
SMTP_PASS = os.getenv("ANPW_SMTP_PASS", "")
MAIL_FROM = os.getenv("ANPW_MAIL_FROM", "Auto Ping Watch <noreply@example.com>")
MAIL_TO = [x.strip() for x in os.getenv("ANPW_MAIL_TO", "").split(",") if x.strip()]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def now_local() -> str:
    """Zwraca timestamp lokalny 'YYYY-MM-DD HH:MM:SS TZ'."""
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def fmt_dur(sec: float) -> str:
    """Formatowanie czasu trwania w sek. do 'Hh Mm Ss'."""
    sec = int(round(sec))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    out = []
    if h:
        out.append(f"{h}h")
    if h or m:
        out.append(f"{m}m")
    out.append(f"{s}s")
    return " ".join(out)


def run_cmd(args: list[str]) -> tuple[int, str]:
    """Uruchom komendę i zwróć (rc, output)."""
    try:
        cp = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        return cp.returncode, cp.stdout.strip()
    except Exception as e:
        return 1, f"ERR: {e}"


def discover_default_gateway() -> str | None:
    """
    Wykryj bramę domyślną IPv4 poprzez `ip route`.
    """
    rc, out = run_cmd(["ip", "-4", "route", "show", "default"])
    if rc == 0 and out:
        for line in out.splitlines():
            parts = line.split()
            if parts and parts[0] == "default":
                try:
                    idx = parts.index("via")
                    return parts[idx + 1]
                except (ValueError, IndexError):
                    continue

    rc, out = run_cmd(["ip", "route"])
    if rc == 0 and out:
        for line in out.splitlines():
            parts = line.split()
            if parts and parts[0] == "default":
                try:
                    idx = parts.index("via")
                    return parts[idx + 1]
                except (ValueError, IndexError):
                    continue
    return None


def ping_once(host: str, timeout_s: int = 1) -> bool:
    """
    Jednorazowy ping ICMP do hosta.

    Zwraca True jeśli `ping` zwróci kod 0.
    """
    try:
        res = subprocess.run(
            ["ping", "-n", "-c", "1", "-W", str(timeout_s), host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return res.returncode == 0
    except FileNotFoundError:
        logging.error("Brak binarki `ping`. Zainstaluj iputils-ping w obrazie.")
        time.sleep(5)
        return False


def send_mail(subject: str, body: str):
    """
    Wyślij maila tekstowego przez SMTP (STARTTLS/SSL).
    """
    if not MAIL_TO:
        logging.warning("MAIL_TO nie ustawione – pomijam wysyłkę e-maila.")
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM
    msg["To"] = ", ".join(MAIL_TO)
    msg.set_content(body)

    if SMTP_PORT == 465:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=15) as s:
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            try:
                s.ehlo()
                s.starttls(context=ssl.create_default_context())
            except smtplib.SMTPNotSupportedError:
                # Np. lokalny MTA na porcie 25.
                pass
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)


def classify_status(router_ip: str | None) -> tuple[bool, str, dict[str, str]]:
    """
    Zwraca (ok, label, diag) gdzie:
      - ok: bool określający, czy Internet jest dostępny (INTERNET=UP),
      - label: UP / LAN_DOWN / INTERNET_DOWN / NO_GATEWAY,
      - diag: słownik z kluczami 'LAN', 'WAN', 'INTERNET'.

    Logika:
      - LAN:
          router_ip brak     -> LAN = NO_GATEWAY
          ping(brama) false  -> LAN = DOWN
          ping(brama) true   -> LAN = UP
      - WAN (opcjonalny):
          WAN_HOST brak      -> WAN = N/A
          ping(WAN_HOST)     -> WAN = UP / DOWN
      - INTERNET:
          jeśli LAN != UP    -> INTERNET = DOWN
          jeśli LAN == UP
             i ANY ping(PUBLIC_HOSTS) -> INTERNET = UP
             else                     -> INTERNET = DOWN

    Label:
      - NO_GATEWAY (brak bramy),
      - LAN_DOWN (brama nie odpowiada),
      - UP (Internet działa),
      - INTERNET_DOWN (brama OK, Internet nie działa).
    """
    diag: dict[str, str] = {
        "LAN": "DOWN",
        "WAN": "N/A",
        "INTERNET": "DOWN",
    }

    # LAN
    if not router_ip:
        diag["LAN"] = "NO_GATEWAY"
        # przy braku bramy WAN/INTERNET i tak są DOWN/N/A
        return False, "NO_GATEWAY", diag

    lan_ok = ping_once(router_ip, PING_TIMEOUT_S)
    diag["LAN"] = "UP" if lan_ok else "DOWN"

    # WAN (opcjonalnie)
    if WAN_HOST:
        wan_ok = ping_once(WAN_HOST, PING_TIMEOUT_S)
        diag["WAN"] = "UP" if wan_ok else "DOWN"
    else:
        diag["WAN"] = "N/A"

    # INTERNET – tylko jeśli LAN jest UP
    internet_ok = False
    if lan_ok:
        internet_ok = any(ping_once(h, PING_TIMEOUT_S) for h in PUBLIC_HOSTS)
    diag["INTERNET"] = "UP" if internet_ok else "DOWN"

    # label / ok
    if not lan_ok:
        # brama nie odpowiada
        return False, "LAN_DOWN", diag
    if internet_ok:
        return True, "UP", diag
    else:
        return False, "INTERNET_DOWN", diag


def format_diag(diag: dict[str, str]) -> str:
    """Ładny string z diagnostyką LAN/WAN/INTERNET."""
    return f"LAN={diag['LAN']}, WAN={diag['WAN']}, INTERNET={diag['INTERNET']}"


def main():
    """
    Główna pętla monitorująca.
    """
    logging.info("Auto Ping Watch — start (Docker, LAN+WAN+Internet)")
    router_ip = discover_default_gateway()
    if router_ip:
        logging.info(f"Wykryta brama (router): {router_ip}")
    else:
        logging.warning("Nie wykryto bramy. Spróbuję ponownie w trakcie pracy.")

    if WAN_HOST:
        logging.info(f"WAN host (self-check): {WAN_HOST}")
    else:
        logging.info("WAN host (ANPW_WAN_HOST) nie ustawiony – pomijam ten test.")

    consecutive_fail = 0
    consecutive_ok = 0
    in_outage = False
    outage_start_ts = None
    outage_kind = None
    last_router_check = 0.0

    while True:
        now_ts = time.time()
        # okresowe ponowne wykrywanie bramy
        if now_ts - last_router_check >= ROUTER_REDISCOVER_EVERY or router_ip is None:
            new_router = discover_default_gateway()
            last_router_check = now_ts
            if new_router and new_router != router_ip:
                logging.info(f"Zmieniono wykrytą bramę: {router_ip} -> {new_router}")
                router_ip = new_router
            elif router_ip is None and new_router:
                logging.info(f"Wykryto bramę: {new_router}")
                router_ip = new_router

        ok, kind, diag = classify_status(router_ip)

        if ok:
            consecutive_ok += 1
            consecutive_fail = 0
            if in_outage and consecutive_ok >= OK_THRESHOLD:
                duration = time.time() - outage_start_ts
                end_str = now_local()
                start_str = (
                    datetime.fromtimestamp(outage_start_ts)
                    .astimezone()
                    .strftime("%Y-%m-%d %H:%M:%S %Z")
                )
                subject = f"[AUTO-PING] Koniec przerwy ({fmt_dur(duration)})"
                body = (
                    "Raport przerwy w dostępie do Internetu (ICMP)\n\n"
                    f"Rodzaj przerwy: {outage_kind}\n"
                    f"Przerwa rozpoczęła się: {start_str}\n"
                    f"Przerwa zakończyła się: {end_str}\n"
                    f"Czas trwania: {fmt_dur(duration)}\n\n"
                    f"Diagnostyka końcowa: {format_diag(diag)}\n\n"
                    f"Router (brama): {router_ip or 'nieznany'}\n"
                    f"Cele publiczne: {', '.join(PUBLIC_HOSTS)}\n"
                    f"Host WAN: {WAN_HOST or 'brak (ANPW_WAN_HOST)'}\n"
                    f"Progi: FAIL>={FAIL_THRESHOLD}, OK>={OK_THRESHOLD}, interwał={INTERVAL_SEC}s\n"
                )
                try:
                    send_mail(subject, body)
                    logging.info(f"Wysłano e-mail: {subject}")
                except Exception as e:
                    logging.error(f"Błąd wysyłki e-maila: {e}")
                in_outage = False
                outage_start_ts = None
                outage_kind = None
        else:
            consecutive_fail += 1
            consecutive_ok = 0
            if not in_outage and consecutive_fail >= FAIL_THRESHOLD:
                in_outage = True
                outage_start_ts = time.time()
                outage_kind = kind
                logging.warning(
                    f"Wykryto przerwę: {kind} (router={router_ip}, public={PUBLIC_HOSTS}, diag={format_diag(diag)})"
                )
                if NOTIFY_ON_START:
                    subject = f"[AUTO-PING] Przerwa wykryta: {kind}"
                    body = (
                        "Wykryto przerwę w dostępie do Internetu (ICMP)\n\n"
                        f"Rodzaj przerwy: {kind}\n"
                        f"Start przerwy: {now_local()}\n"
                        f"Diagnostyka: {format_diag(diag)}\n\n"
                        f"Router (brama): {router_ip or 'nieznany'}\n"
                        f"Cele publiczne: {', '.join(PUBLIC_HOSTS)}\n"
                        f"Host WAN: {WAN_HOST or 'brak (ANPW_WAN_HOST)'}\n"
                        f"Progi: FAIL>={FAIL_THRESHOLD}, OK>={OK_THRESHOLD}, interwał={INTERVAL_SEC}s\n"
                    )
                    try:
                        send_mail(subject, body)
                        logging.info(f"Wysłano e-mail: {subject}")
                    except Exception as e:
                        logging.error(f"Błąd wysyłki e-maila: {e}")

        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Zatrzymano (Ctrl+C).")
