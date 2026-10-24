"""Hochladen per FTPS gegen einen lokalen FTPS-Server (pyftpdlib, eigenes Zertifikat): Ordner anlegen, .neu, Größe, Umbenennen über die alte Datei."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fcy_daten import netz  # noqa: E402


def test_ohne_secrets():
    """Ohne eingetragene Secrets: nur Warnung, Rückgabe 0 (Lauf grün); teilweise eingetragen: Fehler."""
    from fcy_daten import hochladen
    alt = {k: os.environ.pop(k, None) for k in ("FTP_HOST", "FTP_USER", "FTP_PASS")}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            quelle = os.path.join(tmp, "wind.bin"); open(quelle, "wb").write(b"x")
            summ = os.path.join(tmp, "summary.md")
            os.environ["GITHUB_STEP_SUMMARY"] = summ
            assert hochladen.main([quelle, "wx/wind.bin"]) == 0
            assert "Nicht hochgeladen" in open(summ, encoding="utf-8").read()
            os.environ["FTP_HOST"] = "localhost"            # nur ein Teil eingetragen → muss fehlschlagen
            try:
                hochladen.main([quelle, "wx/wind.bin"])
                raise AssertionError("teilweise eingetragene Secrets hätten fehlschlagen müssen")
            except RuntimeError:
                pass
    finally:
        os.environ.pop("GITHUB_STEP_SUMMARY", None); os.environ.pop("FTP_HOST", None)
        os.environ.update({k: v for k, v in alt.items() if v is not None})
    print("ok: ohne Secrets nur Warnung")


def test_hochladen():
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import TLS_FTPHandler
    from pyftpdlib.servers import ThreadedFTPServer
    with tempfile.TemporaryDirectory() as tmp:
        wurzel = os.path.join(tmp, "daten"); os.makedirs(wurzel)
        crt, key = os.path.join(tmp, "c.pem"), os.path.join(tmp, "k.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt, "-days", "1",
                        "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"], check=True, capture_output=True)
        a = DummyAuthorizer(); a.add_user("fcy-daten", "geheim", wurzel, perm="elradfmwMT")
        h = TLS_FTPHandler; h.certfile, h.keyfile, h.authorizer = crt, key, a
        h.tls_control_required = True; h.tls_data_required = True
        srv = ThreadedFTPServer(("127.0.0.1", 0), h)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        os.environ.update({"FTP_HOST": "localhost", "FTP_PORT": str(srv.address[1]), "FTP_USER": "fcy-daten", "FTP_PASS": "geheim", "FTP_CAFILE": crt})
        quelle = os.path.join(tmp, "wind.bin")
        open(quelle, "wb").write(b"A" * 300000)
        netz.hochladen(quelle, "wx/wind.bin")
        assert open(os.path.join(wurzel, "wx", "wind.bin"), "rb").read() == b"A" * 300000
        open(quelle, "wb").write(b"B" * 1000)                 # zweiter Lauf: alte Datei wird ersetzt
        netz.hochladen(quelle, "wx/wind.bin")
        assert open(os.path.join(wurzel, "wx", "wind.bin"), "rb").read() == b"B" * 1000
        assert sorted(os.listdir(os.path.join(wurzel, "wx"))) == ["wind.bin"]   # keine .neu-Reste
        srv.close_all()
        print("ok: Hochladen per FTPS")


if __name__ == "__main__":
    test_ohne_secrets()
    test_hochladen()
