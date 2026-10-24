"""Abrufe mit Wiederholung."""
from __future__ import annotations

import bz2
import re
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
