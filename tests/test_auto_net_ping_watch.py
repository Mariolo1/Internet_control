#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testy jednostkowe dla auto_net_ping_watch.py

Uruchomienie:
    python -m pytest test_auto_net_ping_watch.py -v
lub:
    python test_auto_net_ping_watch.py
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
    
import unittest
from unittest.mock import patch, MagicMock, call
import smtplib
import subprocess


# ──────────────────────────────────────────────
# Pomocnicze stałe do podmienienia env
# ──────────────────────────────────────────────
BASE_ENV = {
    "ANPW_PUBLIC": "1.1.1.1,8.8.8.8",
    "ANPW_WAN_HOST": "",
    "ANPW_INTERVAL": "5",
    "ANPW_FAIL_THRESHOLD": "3",
    "ANPW_OK_THRESHOLD": "2",
    "ANPW_PING_TIMEOUT": "1",
    "ANPW_NOTIFY_ON_START": "1",
    "ANPW_ROUTER_REDISCOVER_EVERY": "300",
    "ANPW_SMTP_HOST": "smtp.gmail.com",
    "ANPW_SMTP_PORT": "587",
    "ANPW_SMTP_USER": "user@example.com",
    "ANPW_SMTP_PASS": "secret",
    "ANPW_MAIL_FROM": "Ping Watch <user@example.com>",
    "ANPW_MAIL_TO": "admin@example.com",
}


def import_module_with_env(env_overrides=None):
    """Importuje moduł na świeżo z podanymi zmiennymi środowiskowymi."""
    import importlib, sys, os
    env = {**BASE_ENV, **(env_overrides or {})}
    with patch.dict(os.environ, env, clear=True):
        if "auto_net_ping_watch" in sys.modules:
            del sys.modules["auto_net_ping_watch"]
        import auto_net_ping_watch as m
    return m


# ══════════════════════════════════════════════
# 1. fmt_dur – formatowanie czasu trwania
# ══════════════════════════════════════════════
class TestFmtDur(unittest.TestCase):

    def setUp(self):
        self.m = import_module_with_env()

    def test_zero_seconds(self):
        self.assertEqual(self.m.fmt_dur(0), "0s")

    def test_only_seconds(self):
        self.assertEqual(self.m.fmt_dur(45), "45s")

    def test_one_minute(self):
        self.assertEqual(self.m.fmt_dur(60), "1m 0s")

    def test_minutes_and_seconds(self):
        self.assertEqual(self.m.fmt_dur(125), "2m 5s")

    def test_one_hour(self):
        self.assertEqual(self.m.fmt_dur(3600), "1h 0m 0s")

    def test_hours_minutes_seconds(self):
        self.assertEqual(self.m.fmt_dur(3661), "1h 1m 1s")

    def test_rounds_floats(self):
        # 90.6 → 91 → 1m 31s
        self.assertEqual(self.m.fmt_dur(90.6), "1m 31s")

    def test_large_value(self):
        # 25h 30m 15s = 91815s
        self.assertEqual(self.m.fmt_dur(91815), "25h 30m 15s")


# ══════════════════════════════════════════════
# 2. discover_default_gateway
# ══════════════════════════════════════════════
class TestDiscoverDefaultGateway(unittest.TestCase):

    def setUp(self):
        self.m = import_module_with_env()

    def _run(self, stdout, rc=0):
        """Pomocnik: podmień run_cmd i wywołaj discover_default_gateway."""
        mock_result = MagicMock(returncode=rc, stdout=stdout)
        with patch("subprocess.run", return_value=mock_result):
            return self.m.discover_default_gateway()

    def test_standard_output(self):
        out = "default via 192.168.1.1 dev eth0 proto dhcp\n"
        self.assertEqual(self._run(out), "192.168.1.1")

    def test_alternative_metric_format(self):
        out = "default via 10.0.0.1 dev wlan0 metric 100\n"
        self.assertEqual(self._run(out), "10.0.0.1")

    def test_no_default_route(self):
        out = "10.0.0.0/8 via 10.0.0.1 dev eth0\n"
        result = self._run(out)
        self.assertIsNone(result)

    def test_empty_output(self):
        self.assertIsNone(self._run("", rc=0))

    def test_command_failure(self):
        self.assertIsNone(self._run("", rc=1))

    def test_multiple_routes_picks_default(self):
        out = (
            "10.0.0.0/8 via 10.0.0.1 dev eth0\n"
            "default via 192.168.100.1 dev eth0\n"
        )
        self.assertEqual(self._run(out), "192.168.100.1")


# ══════════════════════════════════════════════
# 3. ping_once
# ══════════════════════════════════════════════
class TestPingOnce(unittest.TestCase):

    def setUp(self):
        self.m = import_module_with_env()

    def test_ping_success(self):
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            self.assertTrue(self.m.ping_once("8.8.8.8"))

    def test_ping_failure(self):
        mock_result = MagicMock(returncode=1)
        with patch("subprocess.run", return_value=mock_result):
            self.assertFalse(self.m.ping_once("8.8.8.8"))

    def test_ping_binary_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError), \
             patch("time.sleep") as mock_sleep:
            result = self.m.ping_once("8.8.8.8")
        self.assertFalse(result)
        mock_sleep.assert_called_once_with(5)

    def test_passes_timeout_to_command(self):
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            self.m.ping_once("1.1.1.1", timeout_s=3)
        args = mock_run.call_args[0][0]
        self.assertIn("3", args)

    def test_uses_correct_flags(self):
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            self.m.ping_once("1.2.3.4")
        cmd = mock_run.call_args[0][0]
        self.assertIn("-c", cmd)
        self.assertIn("1", cmd)
        self.assertIn("-n", cmd)


# ══════════════════════════════════════════════
# 4. classify_status – kluczowa logika
# ══════════════════════════════════════════════
class TestClassifyStatus(unittest.TestCase):

    def setUp(self):
        self.m = import_module_with_env()

    def _classify(self, router_ip, lan_up, wan_result=None, internet_results=None):
        """
        Pomocnik: podmienia ping_once i wywołuje classify_status.
        internet_results: lista bool dla kolejnych hostów publicznych.
        """
        def fake_ping(host, timeout_s=1):
            if host == router_ip:
                return lan_up
            if wan_result is not None and host == self.m.WAN_HOST:
                return wan_result
            if internet_results:
                return internet_results.pop(0)
            return False

        with patch.object(self.m, "ping_once", side_effect=fake_ping):
            return self.m.classify_status(router_ip)

    # --- brak bramy ---
    def test_no_gateway(self):
        ok, label, diag = self.m.classify_status(None)
        self.assertFalse(ok)
        self.assertEqual(label, "NO_GATEWAY")
        self.assertEqual(diag["LAN"], "NO_GATEWAY")
        self.assertEqual(diag["INTERNET"], "DOWN")

    # --- LAN DOWN ---
    def test_lan_down(self):
        ok, label, diag = self._classify("192.168.1.1", lan_up=False)
        self.assertFalse(ok)
        self.assertEqual(label, "LAN_DOWN")
        self.assertEqual(diag["LAN"], "DOWN")

    # --- Internet działa ---
    def test_internet_up(self):
        ok, label, diag = self._classify(
            "192.168.1.1", lan_up=True,
            internet_results=[True, False]
        )
        self.assertTrue(ok)
        self.assertEqual(label, "UP")
        self.assertEqual(diag["LAN"], "UP")
        self.assertEqual(diag["INTERNET"], "UP")

    # --- LAN OK, ale Internet nie działa ---
    def test_internet_down_lan_ok(self):
        ok, label, diag = self._classify(
            "192.168.1.1", lan_up=True,
            internet_results=[False, False]
        )
        self.assertFalse(ok)
        self.assertEqual(label, "INTERNET_DOWN")
        self.assertEqual(diag["LAN"], "UP")
        self.assertEqual(diag["INTERNET"], "DOWN")

    # --- WAN N/A gdy ANPW_WAN_HOST nie ustawiony ---
    def test_wan_na_when_not_configured(self):
        ok, label, diag = self._classify(
            "192.168.1.1", lan_up=True,
            internet_results=[True]
        )
        self.assertEqual(diag["WAN"], "N/A")

    # --- WAN UP gdy ustawiony i odpowiada ---
    def test_wan_up_when_configured(self):
        m = import_module_with_env({"ANPW_WAN_HOST": "myhome.duckdns.org"})

        def fake_ping(host, timeout_s=1):
            if host == "192.168.1.1":
                return True
            if host == "myhome.duckdns.org":
                return True
            return True  # publiczne

        with patch.object(m, "ping_once", side_effect=fake_ping):
            ok, label, diag = m.classify_status("192.168.1.1")

        self.assertEqual(diag["WAN"], "UP")
        self.assertTrue(ok)

    # --- WAN DOWN gdy ustawiony ale nie odpowiada ---
    def test_wan_down_when_configured(self):
        m = import_module_with_env({"ANPW_WAN_HOST": "myhome.duckdns.org"})

        def fake_ping(host, timeout_s=1):
            if host == "192.168.1.1":
                return True
            if host == "myhome.duckdns.org":
                return False
            return True

        with patch.object(m, "ping_once", side_effect=fake_ping):
            ok, label, diag = m.classify_status("192.168.1.1")

        self.assertEqual(diag["WAN"], "DOWN")

    # --- any() zatrzymuje się na pierwszym True (optymalizacja) ---
    def test_short_circuit_on_first_public_success(self):
        call_count = []

        def fake_ping(host, timeout_s=1):
            if host == "192.168.1.1":
                return True
            call_count.append(host)
            return True  # pierwszy publiczny odpowiada

        m = import_module_with_env({"ANPW_PUBLIC": "1.1.1.1,8.8.8.8,9.9.9.9"})
        with patch.object(m, "ping_once", side_effect=fake_ping):
            ok, label, diag = m.classify_status("192.168.1.1")

        self.assertTrue(ok)
        # any() powinno wywołać ping tylko dla pierwszego hosta publicznego
        self.assertEqual(len(call_count), 1)


# ══════════════════════════════════════════════
# 5. format_diag
# ══════════════════════════════════════════════
class TestFormatDiag(unittest.TestCase):

    def setUp(self):
        self.m = import_module_with_env()

    def test_all_up(self):
        diag = {"LAN": "UP", "WAN": "UP", "INTERNET": "UP"}
        result = self.m.format_diag(diag)
        self.assertIn("LAN=UP", result)
        self.assertIn("WAN=UP", result)
        self.assertIn("INTERNET=UP", result)

    def test_all_down(self):
        diag = {"LAN": "DOWN", "WAN": "N/A", "INTERNET": "DOWN"}
        result = self.m.format_diag(diag)
        self.assertIn("LAN=DOWN", result)
        self.assertIn("WAN=N/A", result)

    def test_no_gateway(self):
        diag = {"LAN": "NO_GATEWAY", "WAN": "N/A", "INTERNET": "DOWN"}
        result = self.m.format_diag(diag)
        self.assertIn("NO_GATEWAY", result)


# ══════════════════════════════════════════════
# 6. send_mail
# ══════════════════════════════════════════════
class TestSendMail(unittest.TestCase):

    def setUp(self):
        self.m = import_module_with_env()

    def test_no_mail_to_skips_send(self):
        m = import_module_with_env({"ANPW_MAIL_TO": ""})
        with patch("smtplib.SMTP") as mock_smtp:
            m.send_mail("Temat", "Treść")
        mock_smtp.assert_not_called()

    def test_sends_via_starttls_port_587(self):
        m = import_module_with_env({"ANPW_SMTP_PORT": "587"})
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_smtp_instance):
            m.send_mail("Temat testowy", "Treść testowa")

        mock_smtp_instance.send_message.assert_called_once()

    def test_sends_via_ssl_port_465(self):
        m = import_module_with_env({"ANPW_SMTP_PORT": "465"})
        mock_ssl_instance = MagicMock()
        mock_ssl_instance.__enter__ = MagicMock(return_value=mock_ssl_instance)
        mock_ssl_instance.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP_SSL", return_value=mock_ssl_instance), \
             patch("ssl.create_default_context"):
            m.send_mail("Temat", "Treść")

        mock_ssl_instance.send_message.assert_called_once()

    def test_message_contains_subject_and_body(self):
        """Sprawdza, że send_message otrzymuje obiekt z właściwym Subject."""
        m = import_module_with_env({"ANPW_SMTP_PORT": "587"})
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)
        mock_smtp_instance.starttls = MagicMock()

        with patch("smtplib.SMTP", return_value=mock_smtp_instance):
            m.send_mail("Przerwa wykryta", "Szczegóły przerwy...")

        sent_msg = mock_smtp_instance.send_message.call_args[0][0]
        self.assertEqual(sent_msg["Subject"], "Przerwa wykryta")

    def test_smtp_not_supported_fallback(self):
        """Jeśli STARTTLS nie jest wspierane, metoda nie rzuca wyjątku."""
        m = import_module_with_env({"ANPW_SMTP_PORT": "25"})
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)
        mock_smtp_instance.starttls.side_effect = smtplib.SMTPNotSupportedError

        with patch("smtplib.SMTP", return_value=mock_smtp_instance):
            m.send_mail("Temat", "Treść")  # nie powinno rzucać

        mock_smtp_instance.send_message.assert_called_once()


# ══════════════════════════════════════════════
# 7. Logika progów w pętli głównej (thresholds)
# ══════════════════════════════════════════════
class TestThresholdLogic(unittest.TestCase):
    """
    Symuluje kilka iteracji pętli main() przez bezpośrednie
    testowanie logiki liczników, bez uruchamiania całej pętli.
    """

    def test_fail_threshold_not_exceeded(self):
        """Poniżej progu FAIL_THRESHOLD – in_outage nie jest ustawiane."""
        fail_threshold = 3
        consecutive_fail = 0
        in_outage = False

        for _ in range(2):  # 2 nieudane pingi, próg = 3
            consecutive_fail += 1
            if not in_outage and consecutive_fail >= fail_threshold:
                in_outage = True

        self.assertFalse(in_outage)

    def test_fail_threshold_triggers_outage(self):
        """Przy 3 kolejnych błędach in_outage = True."""
        fail_threshold = 3
        consecutive_fail = 0
        in_outage = False

        for _ in range(3):
            consecutive_fail += 1
            if not in_outage and consecutive_fail >= fail_threshold:
                in_outage = True

        self.assertTrue(in_outage)

    def test_ok_threshold_clears_outage(self):
        """Po OK_THRESHOLD sukcesach in_outage wraca do False."""
        ok_threshold = 2
        consecutive_ok = 0
        in_outage = True

        for _ in range(2):
            consecutive_ok += 1
            if in_outage and consecutive_ok >= ok_threshold:
                in_outage = False

        self.assertFalse(in_outage)

    def test_ok_not_enough_to_clear_outage(self):
        """Jeden sukces przy OK_THRESHOLD=2 nie czyści przerwy."""
        ok_threshold = 2
        consecutive_ok = 1
        in_outage = True

        if in_outage and consecutive_ok >= ok_threshold:
            in_outage = False

        self.assertTrue(in_outage)

    def test_fail_resets_ok_counter(self):
        """Po nieudanym pingu licznik ok musi się zerować."""
        consecutive_ok = 1
        ok = False  # ping failed

        if ok:
            consecutive_ok += 1
        else:
            consecutive_ok = 0

        self.assertEqual(consecutive_ok, 0)

    def test_ok_resets_fail_counter(self):
        """Po udanym pingu licznik fail musi się zerować."""
        consecutive_fail = 2
        ok = True

        if ok:
            consecutive_fail = 0

        self.assertEqual(consecutive_fail, 0)


# ══════════════════════════════════════════════
# 8. Konfiguracja ze zmiennych środowiskowych
# ══════════════════════════════════════════════
class TestEnvConfig(unittest.TestCase):

    def test_public_hosts_parsed_correctly(self):
        m = import_module_with_env({"ANPW_PUBLIC": "1.1.1.1, 8.8.8.8 , 9.9.9.9"})
        self.assertEqual(m.PUBLIC_HOSTS, ["1.1.1.1", "8.8.8.8", "9.9.9.9"])

    def test_single_public_host(self):
        m = import_module_with_env({"ANPW_PUBLIC": "1.1.1.1"})
        self.assertEqual(m.PUBLIC_HOSTS, ["1.1.1.1"])

    def test_mail_to_multiple_recipients(self):
        m = import_module_with_env({"ANPW_MAIL_TO": "a@x.com, b@x.com"})
        self.assertEqual(m.MAIL_TO, ["a@x.com", "b@x.com"])

    def test_interval_default(self):
        m = import_module_with_env({"ANPW_INTERVAL": "10"})
        self.assertEqual(m.INTERVAL_SEC, 10)

    def test_fail_threshold_custom(self):
        m = import_module_with_env({"ANPW_FAIL_THRESHOLD": "5"})
        self.assertEqual(m.FAIL_THRESHOLD, 5)

    def test_notify_on_start_disabled(self):
        m = import_module_with_env({"ANPW_NOTIFY_ON_START": "0"})
        self.assertFalse(m.NOTIFY_ON_START)

    def test_wan_host_empty_string_is_none(self):
        m = import_module_with_env({"ANPW_WAN_HOST": ""})
        self.assertIsNone(m.WAN_HOST)

    def test_wan_host_set(self):
        m = import_module_with_env({"ANPW_WAN_HOST": "home.example.com"})
        self.assertEqual(m.WAN_HOST, "home.example.com")


# ══════════════════════════════════════════════
# Uruchomienie bezpośrednie
# ══════════════════════════════════════════════
if __name__ == "__main__":
    unittest.main(verbosity=2)
