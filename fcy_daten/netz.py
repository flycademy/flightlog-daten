"""Abrufe (mit Wiederholung) und Hochladen per FTPS."""
from __future__ import annotations

import bz2
import ftplib
import os
import re
import ssl
import time
from concurrent.futures import ThreadPoolExecutor

import requests

UA = "FlyCademy-FlightLog-Daten/1.0 (+https://training.flycademy.de)"
_S = requests.Session()
_S.headers["User-Agent"] = UA


def hole(url: str, versuche: int = 4, timeout: int = 60, ok404: bool = False) -> bytes | None:
    letzter = None
    for n in range(versuche):
        try:
            r = _S.get(url, timeout=timeout)
            if r.status_code == 404 and ok404:
                return None
            r.raise_for_status()
            return r.content
        except Exception as e:  # noqa: BLE001 — Netzfehler wiederholen
            letzter = e
            time.sleep(2 * (n + 1))
    raise RuntimeError(f"Abruf fehlgeschlagen: {url}: {letzter}")


def hole_bz2(url: str) -> bytes:
    return bz2.decompress(hole(url))


def verzeichnis(url: str) -> list[str]:
    """Dateinamen einer Apache/nginx-Verzeichnisliste."""
    html = hole(url).decode("utf-8", "replace")
    return sorted(set(re.findall(r'href="([^"?/][^"]*?)"', html)))


def parallel(funktion, eingaben, threads: int = 16):
    with ThreadPoolExecutor(max_workers=threads) as ex:
        return list(ex.map(funktion, eingaben))


# ----------------------------------------------------------------------------------------------
# FTPS (explizit, passiv). Zugangsdaten nur aus der Umgebung (GitHub-Secrets): FTP_HOST, FTP_USER, FTP_PASS, FTP_DIR.
# Hochladen unter neuem Namen, dann umbenennen — der Flight Log sieht nie eine halbe Datei.
# ----------------------------------------------------------------------------------------------
class _FTPS(ftplib.FTP_TLS):
    """FTPS mit Wiederverwendung der TLS-Sitzung auf der Datenverbindung — viele Server (ProFTPD unter Plesk,
    vsftpd mit require_ssl_reuse) lehnen die Datenverbindung sonst ab („522 … session reuse required“)."""
    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session)
        return conn, size


def ftp_verbinden() -> ftplib.FTP_TLS:
    host, user, pw = os.environ.get("FTP_HOST"), os.environ.get("FTP_USER"), os.environ.get("FTP_PASS")
    if not (host and user and pw):
        raise RuntimeError("FTP_HOST, FTP_USER und FTP_PASS fehlen (GitHub → Settings → Secrets and variables → Actions)")
    ctx = ssl.create_default_context(cafile=os.environ.get("FTP_CAFILE") or None)   # FTP_CAFILE nur für Tests
    if os.environ.get("FTP_TLS12") == "1":          # falls der Server mit TLS 1.3 und Sitzungswiederverwendung hakt
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    f = _FTPS(context=ctx, timeout=120)
    f.connect(host, int(os.environ.get("FTP_PORT", "21")))
    f.auth()
    f.prot_p()
    f.login(user, pw)
    f.set_pasv(True)
    return f


def _mkdirs(f: ftplib.FTP_TLS, pfad: str) -> None:
    teile = [p for p in pfad.split("/") if p]
    cur = "/" if pfad.startswith("/") else ""
    for p in teile:
        cur = (cur.rstrip("/") + "/" + p) if cur else p
        try:
            f.mkd(cur)
        except ftplib.error_perm:
            pass


def hochladen(lokal: str, ziel: str) -> None:
    """ziel relativ zu FTP_DIR, z. B. "wx/wind.bin"."""
    basis = os.environ.get("FTP_DIR", "").strip().rstrip("/")
    voll = f"{basis}/{ziel}" if basis else ziel
    ordner = voll.rsplit("/", 1)[0] if "/" in voll else ""
    f = ftp_verbinden()
    try:
        if ordner:
            _mkdirs(f, ordner)
        tmp = voll + ".neu"
        with open(lokal, "rb") as fh:
            f.storbinary(f"STOR {tmp}", fh, blocksize=1 << 16)
        groesse = f.size(tmp)
        if groesse is not None and groesse != os.path.getsize(lokal):
            raise RuntimeError(f"Upload unvollständig: {groesse} von {os.path.getsize(lokal)} Byte")
        try:
            f.rename(tmp, voll)
        except ftplib.error_perm:
            try:
                f.delete(voll)
            except ftplib.error_perm:
                pass
            f.rename(tmp, voll)
    finally:
        try:
            f.quit()
        except Exception:  # noqa: BLE001
            f.close()
