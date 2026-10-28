"""
E17: پشتیبانی V2Ray/Xray از طریق دستور proxy. همه‌ی لینک‌ها ساختگی‌اند و
هیچ تستی پروسه‌ی واقعی xray بالا نمی‌آره (Popen جعلی).
"""

import base64
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import proxy_state, xray_proxy

UUID = "11111111-2222-3333-4444-555555555555"
VLESS_REALITY = (f"vless://{UUID}@example.test:443?encryption=none&type=tcp&security=reality"
                 "&sni=front.test&fp=chrome&pbk=FAKEPUBLICKEY&sid=abcd1234&flow=xtls-rprx-vision#name")
VLESS_WS_TLS = (f"vless://{UUID}@ws.test:8443?type=ws&security=tls&sni=ws.test"
                "&host=cdn.test&path=%2Fsock&alpn=h2,http/1.1")
VLESS_GRPC = f"vless://{UUID}@g.test:443?type=grpc&security=tls&serviceName=svc&sni=g.test"
_VMESS_JSON = {"v": "2", "ps": "n", "add": "vm.test", "port": "443", "id": UUID, "aid": "0",
               "scy": "auto", "net": "ws", "type": "none", "host": "h.test", "path": "/v", "tls": "tls",
               "sni": "vm.test"}
VMESS = "vmess://" + base64.b64encode(json.dumps(_VMESS_JSON).encode()).decode()
TROJAN = "trojan://s3cretpass@tr.test:443?sni=tr.test&type=tcp#t"
SS_SIP002 = "ss://" + base64.urlsafe_b64encode(b"aes-256-gcm:sspass").decode().rstrip("=") + "@ss.test:8388#x"
SS_LEGACY = "ss://" + base64.b64encode(b"chacha20-ietf-poly1305:sspass@ss2.test:9000").decode()
ALL = [VLESS_REALITY, VLESS_WS_TLS, VLESS_GRPC, VMESS, TROJAN, SS_SIP002, SS_LEGACY]


class ParseTest(unittest.TestCase):
    def test_vless_reality(self):
        o = xray_proxy.parse_link(VLESS_REALITY)
        user = o["settings"]["vnext"][0]
        self.assertEqual((o["protocol"], user["address"], user["port"]), ("vless", "example.test", 443))
        self.assertEqual(user["users"][0]["id"], UUID)
        self.assertEqual(user["users"][0]["flow"], "xtls-rprx-vision")
        s = o["streamSettings"]
        self.assertEqual((s["network"], s["security"]), ("tcp", "reality"))
        self.assertEqual(s["realitySettings"]["publicKey"], "FAKEPUBLICKEY")
        self.assertEqual(s["realitySettings"]["shortId"], "abcd1234")
        self.assertEqual(s["realitySettings"]["serverName"], "front.test")

    def test_vless_ws_tls(self):
        s = xray_proxy.parse_link(VLESS_WS_TLS)["streamSettings"]
        self.assertEqual(s["wsSettings"], {"path": "/sock", "headers": {"Host": "cdn.test"}})
        self.assertEqual(s["tlsSettings"]["alpn"], ["h2", "http/1.1"])

    def test_vless_grpc(self):
        s = xray_proxy.parse_link(VLESS_GRPC)["streamSettings"]
        self.assertEqual(s["network"], "grpc")
        self.assertEqual(s["grpcSettings"]["serviceName"], "svc")

    def test_vmess(self):
        o = xray_proxy.parse_link(VMESS)
        v = o["settings"]["vnext"][0]
        self.assertEqual((o["protocol"], v["address"], v["port"]), ("vmess", "vm.test", 443))
        self.assertEqual(v["users"][0]["id"], UUID)
        self.assertEqual(o["streamSettings"]["security"], "tls")
        self.assertEqual(o["streamSettings"]["wsSettings"]["path"], "/v")

    def test_trojan(self):
        o = xray_proxy.parse_link(TROJAN)
        self.assertEqual(o["settings"]["servers"][0]["password"], "s3cretpass")
        self.assertEqual(o["streamSettings"]["security"], "tls")

    def test_ss_both_forms(self):
        for link, host, method in ((SS_SIP002, "ss.test", "aes-256-gcm"),
                                   (SS_LEGACY, "ss2.test", "chacha20-ietf-poly1305")):
            server = xray_proxy.parse_link(link)["settings"]["servers"][0]
            self.assertEqual((server["address"], server["method"], server["password"]),
                             (host, method, "sspass"))

    def test_bad_links_raise_without_leaking(self):
        for bad in ("vless://nohost", "vmess://!!!notbase64", "ss://", "http://x:1", "trojan://@h:1"):
            with self.assertRaises(xray_proxy.LinkError) as ctx:
                xray_proxy.parse_link(bad)
            self.assertNotIn("nohost", str(ctx.exception))


class ConfigTest(unittest.TestCase):
    def test_config_listens_locally_only(self):
        for link in ALL:
            cfg = xray_proxy.build_config(link, 1111, 2222)
            self.assertEqual([(i["listen"], i["port"], i["protocol"]) for i in cfg["inbounds"]],
                             [("127.0.0.1", 1111, "socks"), ("127.0.0.1", 2222, "http")])
            self.assertEqual(cfg["outbounds"][0]["tag"], "proxy")


class MaskTest(unittest.TestCase):
    def test_mask_never_contains_secrets(self):
        for link in ALL:
            masked = proxy_state.mask(link)
            for secret in (UUID, "s3cretpass", "sspass", "FAKEPUBLICKEY", "abcd1234"):
                self.assertNotIn(secret, masked)
            self.assertIn("***", masked)

    def test_plain_proxy_credentials_masked(self):
        self.assertEqual(proxy_state.mask("http://user:pw@h:8080"), "http://***@h:8080")
        self.assertEqual(proxy_state.mask("http://h:8080"), "http://h:8080")


class ProxyStateTest(unittest.TestCase):
    def tearDown(self):
        proxy_state.configure(False, None)

    def test_validate_accepts_share_links_and_rejects_garbage(self):
        for link in ALL:
            self.assertEqual(proxy_state.validate(link)[0], link)
        self.assertIsNone(proxy_state.validate("vless://broken")[0])

    def test_plain_proxy_untouched_and_no_xray(self):
        with mock.patch.object(xray_proxy, "ensure") as ensure:
            proxy_state.configure(True, "http://127.0.0.1:2080")
            self.assertEqual(proxy_state.get_proxy_url(), "http://127.0.0.1:2080")
            ensure.assert_not_called()

    def test_lazy_start_and_http_resolution(self):
        with mock.patch.object(xray_proxy, "ensure", return_value=("socks5h://127.0.0.1:1", "http://127.0.0.1:2")) as ensure:
            proxy_state.configure(True, VLESS_REALITY)
            ensure.assert_not_called()          # configure تنبله
            self.assertEqual(proxy_state.get_proxy_url(), "http://127.0.0.1:2")
            self.assertEqual(proxy_state.resolve(VLESS_REALITY, prefer="socks"), "socks5h://127.0.0.1:1")

    def test_unset_stops_xray(self):
        with mock.patch.object(xray_proxy, "stop") as stop:
            proxy_state.configure(True, VLESS_REALITY)
            stop.reset_mock()
            proxy_state.configure(False, None)
            stop.assert_called()

    def test_failed_start_returns_none(self):
        with mock.patch.object(xray_proxy, "ensure", return_value=None):
            proxy_state.configure(True, VLESS_REALITY)
            self.assertIsNone(proxy_state.get_proxy_url())


class FakeProc:
    _next = 100

    def __init__(self, *a, **k):
        FakeProc._next += 1
        self.pid = FakeProc._next
        self.returncode = None
        self.stdin = mock.MagicMock()
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        xray_proxy.stop()
        xray_proxy._failed_at = 0.0
        self.procs = []

        def popen(*a, **k):
            p = FakeProc()
            self.procs.append((p, a, k))
            return p
        self.patches = [
            mock.patch.object(xray_proxy.subprocess, "Popen", side_effect=popen),
            mock.patch.object(xray_proxy.platform_paths, "find_native_component", return_value="xray-fake"),
            mock.patch.object(xray_proxy.platform_paths, "_ensure_executable", side_effect=lambda p: p),
            mock.patch.object(xray_proxy, "_port_open", return_value=True),
            mock.patch.object(xray_proxy, "_reap_stale"),
            mock.patch.object(xray_proxy, "_pidfile", return_value=os.devnull + ".pid"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        xray_proxy.stop()
        for p in self.patches:
            p.stop()

    def test_one_process_reused_and_config_via_stdin_only(self):
        first = xray_proxy.ensure(VLESS_REALITY)
        self.assertEqual(xray_proxy.ensure(VLESS_REALITY), first)
        self.assertEqual(len(self.procs), 1)
        proc, args, _ = self.procs[0]
        self.assertNotIn(UUID, " ".join(args[0]))          # هیچ راز توی آرگومان‌ها نیست
        written = proc.stdin.write.call_args[0][0].decode()
        self.assertIn(UUID, written)                        # کانفیگ فقط از stdin می‌ره

    def test_restart_when_process_dies(self):
        xray_proxy.ensure(VLESS_REALITY)
        self.procs[0][0].returncode = 1
        self.assertIsNotNone(xray_proxy.ensure(VLESS_REALITY))
        self.assertEqual(len(self.procs), 2)

    def test_stop_terminates_and_leaves_nothing(self):
        xray_proxy.ensure(VLESS_REALITY)
        proc = self.procs[0][0]
        xray_proxy.stop()
        self.assertTrue(proc.terminated)
        self.assertFalse(xray_proxy.is_running())

    def test_new_link_replaces_old_process(self):
        xray_proxy.ensure(VLESS_REALITY)
        xray_proxy.ensure(TROJAN)
        self.assertTrue(self.procs[0][0].terminated)
        self.assertEqual(len(self.procs), 2)

    def test_missing_binary_fails_softly_with_cooldown(self):
        with mock.patch.object(xray_proxy.platform_paths, "find_native_component", return_value=None), \
             mock.patch("shutil.which", return_value=None):
            self.assertIsNone(xray_proxy.ensure(VLESS_REALITY))
            self.assertIsNone(xray_proxy.ensure(VLESS_REALITY))   # cooldown
        self.assertEqual(self.procs, [])


class I18nTest(unittest.TestCase):
    def test_new_keys_in_both_languages_with_same_placeholders(self):
        import re
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "languages")
        data = {}
        for l in ("en", "fa"):
            with open(os.path.join(base, l + ".json"), encoding="utf-8") as f:
                data[l] = json.load(f)["strings"]
        for key in ("proxy_cleared", "proxy_v2ray_unavailable", "proxy_not_configured"):
            found = [set(re.findall(r"\{(\w+)\}", data[l][key])) for l in ("en", "fa")]
            self.assertEqual(found[0], found[1], key)


if __name__ == "__main__":
    unittest.main()


class InstallChecksumTest(unittest.TestCase):
    def _run(self, payload, dgst):
        import hashlib
        import io
        import tempfile
        import install
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(payload)
        try:
            resp = mock.MagicMock()
            resp.__enter__.return_value.read.return_value = dgst.format(sha=hashlib.sha256(b"good").hexdigest()).encode()
            with mock.patch("install.urllib.request.urlopen", return_value=resp):
                return install._verify_sha256(f.name, "https://example.invalid/x.zip")
        finally:
            os.remove(f.name)

    def test_match_passes(self):
        self.assertTrue(self._run(b"good", "SHA2-256= {sha}\n"))

    def test_mismatch_aborts(self):
        import install
        with self.assertRaises(install.InstallError):
            self._run(b"tampered", "SHA2-256= {sha}\n")
