"""Tests del lector de códigos 2FA de Polar, con un buzón IMAP falso (sin red).

  venv/bin/python3 -m unittest tests.test_codigo_2fa -v
"""
import imaplib
import unittest

from src.scrapers.codigo_2fa import (
    BuzonCodigos, Codigo2FAError, codigo_del_mensaje, direccion_tecnico, extraer_codigo,
)

# Como el correo real de Orange (16-nov-2026), con un código inventado
CUERPO_ORANGE = ("<p>Orange:&nbsp;</p><p>Hola,&nbsp;</p><p>Hola, este es tu c&oacute;digo de seguridad "
                 "<b>47kqz</b> para el acceso a Web de Polar. Por seguridad, no lo compartas con nadie.</p>")


def _correo(para, cuerpo=CUERPO_ORANGE, de="orange@orange.es"):
    return (f"From: {de}\r\nTo: {para}\r\nDelivered-To: {para}\r\n"
            f"Subject: =?utf-8?q?Informaci=C3=B3n_sobre_el_c=C3=B3digo_de_seguridad_de_acceso?=\r\n"
            f"Content-Type: text/html; charset=utf-8\r\n\r\n{cuerpo}\r\n").encode()


class ImapFalso:
    def __init__(self, carpetas):
        self.carpetas = carpetas  # {"INBOX": [(uid, bytes), ...]}
        self.actual = None
        self.logins = 0

    def login(self, usuario, password):
        if password != "abcdabcdabcdabcd":
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        self.logins += 1

    def select(self, carpeta, readonly=False):
        nombre = carpeta.strip('"')
        if nombre not in self.carpetas:
            return "NO", [b"no existe"]
        self.actual = nombre
        return "OK", [str(len(self.carpetas[nombre])).encode()]

    def uid(self, orden, *args):  # como imaplib: SEARCH lleva charset, FETCH no
        msgs = self.carpetas[self.actual]
        if orden == "SEARCH":
            desde = int(args[2].split(":")[0])
            uids = [u for u, _ in msgs if u >= desde] or [u for u, _ in msgs[-1:]]
            return "OK", [" ".join(map(str, uids)).encode()]
        if orden == "FETCH":
            crudo = dict(msgs)[int(args[0])]
            return "OK", [(f"{args[0]} (BODY[] {{{len(crudo)}}}".encode(), crudo), b")"]
        raise AssertionError(orden)

    def logout(self):
        pass


def _buzon(imap, password="abcd abcd abcd abcd"):
    return BuzonCodigos("buzon@example.com", password, conectar=lambda: imap)


class Extraccion(unittest.TestCase):
    def test_codigo_del_correo_de_orange(self):
        self.assertEqual(extraer_codigo(CUERPO_ORANGE), "47kqz")

    def test_sin_codigo(self):
        self.assertIsNone(extraer_codigo("Hola, bienvenido a Polar"))

    def test_direcciones(self):
        self.assertEqual(direccion_tecnico("buzon@example.com", "HANS"), "buzon+hans@example.com")
        self.assertEqual(direccion_tecnico("Buzon@Example.com", "LUIS E"), "buzon+luise@example.com")
        self.assertEqual(direccion_tecnico("buzon+x@example.com", "Iñaki"), "buzon+inaki@example.com")

    def test_solo_de_orange_y_para_ese_tecnico(self):
        hans = "buzon+hans@example.com"
        self.assertEqual(codigo_del_mensaje(_correo(hans), hans), "47kqz")
        self.assertIsNone(codigo_del_mensaje(_correo("buzon+yohan@example.com"), hans))
        self.assertIsNone(codigo_del_mensaje(_correo(hans, de="pesca@ejemplo.com"), hans))


class Buzon(unittest.TestCase):
    def test_faltan_variables(self):
        with self.assertRaises(Codigo2FAError):
            BuzonCodigos("", "", conectar=lambda: None)

    def test_contrasena_mala_es_codigo2faerror(self):
        with self.assertRaises(Codigo2FAError):
            _buzon(ImapFalso({"INBOX": []}), password="mala").marca()

    def test_marca_por_carpeta_y_carpeta_que_no_existe(self):
        imap = ImapFalso({"INBOX": [(3, b"x"), (7, b"y")], "[Gmail]/Spam": []})
        self.assertEqual(_buzon(imap).marca(), {"INBOX": 7, "[Gmail]/Spam": 0})
        self.assertEqual(_buzon(ImapFalso({"INBOX": []})).marca(), {"INBOX": 0})

    def test_ignora_codigos_anteriores_a_la_marca(self):
        hans = "buzon+hans@example.com"
        viejo = _correo(hans, CUERPO_ORANGE.replace("47kqz", "11aaa"))
        imap = ImapFalso({"INBOX": [(5, viejo)]})
        esperas = []
        reloj = iter(range(0, 1000, 5))

        def dormir(s):
            esperas.append(s)
            if len(esperas) == 2:  # llega el nuevo mientras se espera
                imap.carpetas["INBOX"].append((6, _correo(hans)))

        codigo = _buzon(imap).esperar_codigo(hans, {"INBOX": 5}, timeout=60, dormir=dormir,
                                             reloj=lambda: next(reloj))
        self.assertEqual(codigo, "47kqz")
        self.assertEqual(len(esperas), 2)
        self.assertEqual(imap.logins, 1)  # una sola sesión IMAP durante la espera

    def test_elige_el_del_tecnico_y_el_mas_reciente(self):
        hans, yohan = "buzon+hans@example.com", "buzon+yohan@example.com"
        imap = ImapFalso({"INBOX": [
            (10, _correo(hans, CUERPO_ORANGE.replace("47kqz", "22bbb"))),
            (11, _correo(yohan, CUERPO_ORANGE.replace("47kqz", "33ccc"))),
            (12, _correo(hans)),
        ]})
        self.assertEqual(_buzon(imap).esperar_codigo(hans, {"INBOX": 9}, timeout=0), "47kqz")
        self.assertEqual(_buzon(imap).esperar_codigo(yohan, {"INBOX": 9}, timeout=0), "33ccc")

    def test_lo_encuentra_en_spam(self):
        hans = "buzon+hans@example.com"
        imap = ImapFalso({"INBOX": [], "[Gmail]/Spam": [(4, _correo(hans))]})
        self.assertEqual(_buzon(imap).esperar_codigo(hans, {"INBOX": 0, "[Gmail]/Spam": 0}, timeout=0), "47kqz")

    def test_no_llega(self):
        imap = ImapFalso({"INBOX": []})
        reloj = iter(range(0, 1000, 10))
        with self.assertRaisesRegex(Codigo2FAError, "No llegó"):
            _buzon(imap).esperar_codigo("buzon+hans@example.com", {"INBOX": 0}, timeout=30,
                                        dormir=lambda s: None, reloj=lambda: next(reloj))


if __name__ == "__main__":
    unittest.main()
