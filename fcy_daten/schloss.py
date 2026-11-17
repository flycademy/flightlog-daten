"""Verschlüsselung der Daten für den Flight Log (Accountable Manager 17.11.2026: „nur unsere Seite soll sie lesen können“).

Die Jobs legen jede Datei verschlüsselt im Release „daten“ ab (<datei>.v). Lesen kann sie nur der Server des Flight Log:
Er erzeugt sein Schlüsselpaar selbst (private/flightlog/daten/schluessel/, geheim.key und oeffentlich.txt); der geheime Teil
verlässt den Server nie. Der öffentliche Teil steht hier im Repository (fcy_daten/schluessel.pub); mit ihm kann man nur
verschlüsseln. Auf GitHub liegt damit kein Geheimnis.

Verfahren (libsodium, über PyNaCl; auf dem Server PHP sodium):
  - je Datei ein neuer Dateischlüssel (32 Byte), versiegelt für den öffentlichen Schlüssel des Servers (crypto_box_seal:
    X25519, XSalsa20-Poly1305),
  - die Datei selbst in Stücken zu 1 MiB mit crypto_secretstream_xchacha20poly1305 (jedes Stück mit Prüfwert, das letzte
    als Ende markiert: abgeschnittene, vertauschte oder veränderte Stücke fallen auf).

Aufbau von <datei>.v:
  0   4  b"FCYV"
  4   4  Fassung 1, dann drei Nullbytes
  8  16  Fingerabdruck des Empfängerschlüssels (BLAKE2b, 16 Byte, über den öffentlichen Schlüssel)
  24 80  versiegelter Dateischlüssel
  104 24 Kopf von secretstream
  128 …  Stücke (1 MiB Klartext + 17 Byte), Zusatzdaten je Stück: Byte 0–23 der Datei

Aufrufe:
  python -m fcy_daten.schloss verschluesseln <datei> [--aus <datei>.v] [--schluessel fcy_daten/schluessel.pub]
  python -m fcy_daten.schloss entschluesseln <datei.v> --geheim <geheim.key> --aus <datei>      (nur zum Prüfen)
  python -m fcy_daten.schloss neu <ordner>          Schlüsselpaar zum Prüfen (geheim.key, oeffentlich.txt)
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import os
import sys

from nacl import bindings as B
from nacl.public import PrivateKey

MAGIC = b"FCYV"
FASSUNG = 1
STUECK = 1 << 20
KOPF = 128
OEFF = "FCY-OEFFENTLICH-1"
GEHEIM = "FCY-GEHEIM-1"
STANDARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schluessel.pub")
_TAG_M = B.crypto_secretstream_xchacha20poly1305_TAG_MESSAGE
_TAG_F = B.crypto_secretstream_xchacha20poly1305_TAG_FINAL


class SchlossFehler(Exception):
    pass


def fingerabdruck(pk: bytes) -> bytes:
    return hashlib.blake2b(pk, digest_size=16).digest()     # = PHP sodium_crypto_generichash($pk, '', 16)


def fp_hex(pk: bytes) -> str:
    return fingerabdruck(pk).hex()


def _zeile(text: str, kennung: str) -> bytes:
    for z in text.replace("\r", "").split("\n"):
        z = z.strip()
        if z.startswith(kennung + " "):
            return base64.b64decode(z[len(kennung) + 1:].strip(), validate=True)
    raise SchlossFehler(f"keine Zeile „{kennung} …“")


def oeffentlich_lesen(text: str) -> bytes:
    """Öffentlicher Schlüssel aus oeffentlich.txt bzw. schluessel.pub; auch die bloße Base64-Zeile geht."""
    t = text.strip()
    try:
        pk = _zeile(t, OEFF) if OEFF in t else base64.b64decode(t, validate=True)
    except (ValueError, SchlossFehler) as e:
        raise SchlossFehler(f"öffentlicher Schlüssel unlesbar: {e}") from None
    if len(pk) != 32:
        raise SchlossFehler("öffentlicher Schlüssel: 32 Byte erwartet")
    return pk


def oeffentlich_laden(pfad: str | None = None) -> bytes | None:
    """Schlüssel des Servers aus dem Repository; None, solange er noch nicht eingetragen ist."""
    p = pfad or os.environ.get("FCY_SCHLUESSEL") or STANDARD
    if not os.path.exists(p):
        return None
    t = open(p, encoding="utf-8").read()
    if not t.strip() or OEFF not in t:
        return None
    return oeffentlich_lesen(t)


def geheim_lesen(text: str) -> bytes:
    """Schlüsselpaar (geheim 32 Byte + öffentlich 32 Byte) wie PHP sodium_crypto_box_keypair."""
    kp = _zeile(text, GEHEIM)
    if len(kp) != 64 or B.crypto_scalarmult_base(kp[:32]) != kp[32:]:
        raise SchlossFehler("geheimer Schlüssel unlesbar")
    return kp


def schluessel_texte(kp: bytes) -> tuple[str, str]:
    jetzt = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pk = kp[32:]
    g = (f"# Geheimer Schlüssel des Flight-Log-Servers. Nicht weitergeben.\n{GEHEIM} {base64.b64encode(kp).decode()}\n")
    o = (f"{OEFF} {base64.b64encode(pk).decode()}\n# Fingerabdruck: {fp_hex(pk)}\n# erzeugt: {jetzt}\n")
    return g, o


def verschluesseln(klar: str, aus: str, pk: bytes) -> dict:
    """Datei verschlüsseln; Rückgabe: Größe und SHA-256 von Klartext und verschlüsselter Datei."""
    fk = B.crypto_secretstream_xchacha20poly1305_keygen()
    st = B.crypto_secretstream_xchacha20poly1305_state()
    kopf_ss = B.crypto_secretstream_xchacha20poly1305_init_push(st, fk)
    vorn = MAGIC + bytes([FASSUNG, 0, 0, 0]) + fingerabdruck(pk)
    kopf = vorn + B.crypto_box_seal(fk, pk) + kopf_ss
    assert len(kopf) == KOPF
    hk, hv = hashlib.sha256(), hashlib.sha256()
    nk = nv = 0
    with open(klar, "rb") as f, open(aus + ".neu", "wb") as o:
        o.write(kopf); hv.update(kopf); nv += len(kopf)
        stueck = f.read(STUECK)
        while True:
            naechstes = f.read(STUECK) if len(stueck) == STUECK else b""
            letztes = not naechstes
            hk.update(stueck); nk += len(stueck)
            c = B.crypto_secretstream_xchacha20poly1305_push(st, stueck, vorn, _TAG_F if letztes else _TAG_M)
            o.write(c); hv.update(c); nv += len(c)
            if letztes:
                break
            stueck = naechstes
    os.replace(aus + ".neu", aus)
    return {"klar_groesse": nk, "klar_sha256": hk.hexdigest(), "groesse": nv, "sha256": hv.hexdigest(), "schluessel": fp_hex(pk)}


def entschluesseln(pfad: str, kp: bytes) -> bytes:
    d = open(pfad, "rb").read()
    if len(d) < KOPF + 17 or d[:4] != MAGIC or d[4] != FASSUNG:
        raise SchlossFehler("kein FCYV")
    if d[8:24] != fingerabdruck(kp[32:]):
        raise SchlossFehler("für einen anderen Schlüssel verschlüsselt")
    try:
        fk = B.crypto_box_seal_open(d[24:104], kp[32:], kp[:32])
    except Exception:  # noqa: BLE001
        raise SchlossFehler("Dateischlüssel nicht zu öffnen") from None
    st = B.crypto_secretstream_xchacha20poly1305_state()
    B.crypto_secretstream_xchacha20poly1305_init_pull(st, d[104:128], fk)
    out, pos, ende = [], KOPF, False
    while pos < len(d):
        c = d[pos:pos + STUECK + 17]; pos += len(c)
        try:
            m, tag = B.crypto_secretstream_xchacha20poly1305_pull(st, c, d[:24])
        except Exception:  # noqa: BLE001
            raise SchlossFehler("Stück beschädigt") from None
        out.append(m)
        if tag == _TAG_F:
            ende = True
            break
    if not ende or pos != len(d):
        raise SchlossFehler("abgeschnitten oder angehängt")
    return b"".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="was", required=True)
    v = sp.add_parser("verschluesseln"); v.add_argument("datei"); v.add_argument("--aus"); v.add_argument("--schluessel")
    e = sp.add_parser("entschluesseln"); e.add_argument("datei"); e.add_argument("--geheim", required=True); e.add_argument("--aus", required=True)
    n = sp.add_parser("neu"); n.add_argument("ordner")
    a = ap.parse_args(argv)
    if a.was == "verschluesseln":
        pk = oeffentlich_laden(a.schluessel)
        if pk is None:
            print("kein öffentlicher Schlüssel des Servers eingetragen", file=sys.stderr)
            return 2
        r = verschluesseln(a.datei, a.aus or a.datei + ".v", pk)
        print(f"verschlüsselt: {os.path.basename(a.datei)} ({r['klar_groesse']} → {r['groesse']} Byte, Schlüssel {r['schluessel']})")
    elif a.was == "entschluesseln":
        d = entschluesseln(a.datei, geheim_lesen(open(a.geheim, encoding="utf-8").read()))
        open(a.aus, "wb").write(d)
        print(f"entschlüsselt: {len(d)} Byte")
    else:
        os.makedirs(a.ordner, exist_ok=True)
        sk = PrivateKey.generate()
        g, o = schluessel_texte(bytes(sk) + bytes(sk.public_key))
        open(os.path.join(a.ordner, "geheim.key"), "w").write(g)
        open(os.path.join(a.ordner, "oeffentlich.txt"), "w").write(o)
        print(o.splitlines()[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
