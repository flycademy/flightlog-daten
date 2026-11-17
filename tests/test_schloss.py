"""Verschlüsselung (fcy_daten/schloss.py): Rundweg, Stückgrenzen, leere Datei, falscher Schlüssel, Veränderung,
Abschneiden, Anhängen, Vertauschen von Stücken."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fcy_daten import schloss as S  # noqa: E402


def _paar(ordner, name):
    S.main(["neu", os.path.join(ordner, name)])
    o = S.oeffentlich_lesen(open(os.path.join(ordner, name, "oeffentlich.txt")).read())
    g = S.geheim_lesen(open(os.path.join(ordner, name, "geheim.key")).read())
    assert g[32:] == o
    return o, g


def _fehlt(f, *a):
    try:
        f(*a)
    except S.SchlossFehler:
        return True
    return False


def test_schloss():
    with tempfile.TemporaryDirectory() as t:
        pk, kp = _paar(t, "a")
        pk2, kp2 = _paar(t, "b")
        for n in (0, 1, S.STUECK - 1, S.STUECK, S.STUECK + 1, 3 * S.STUECK, 2 * S.STUECK + 12345):
            p = os.path.join(t, f"d{n}.bin")
            klar = os.urandom(n)
            open(p, "wb").write(klar)
            r = S.verschluesseln(p, p + ".v", pk)
            assert r["klar_groesse"] == n and r["groesse"] == os.path.getsize(p + ".v")
            stuecke = max(1, -(-n // S.STUECK))      # das letzte Stück trägt die Endmarke, auch wenn es voll ist
            assert r["groesse"] == S.KOPF + n + 17 * stuecke, (n, r["groesse"])
            assert S.entschluesseln(p + ".v", kp) == klar, n
            assert _fehlt(S.entschluesseln, p + ".v", kp2), "fremder Schlüssel"
        p = os.path.join(t, "d3145728.bin.v")      # drei volle Stücke
        d = open(p, "rb").read()
        def probe(neu):
            q = os.path.join(t, "x.v"); open(q, "wb").write(neu); return _fehlt(S.entschluesseln, q, kp)
        assert probe(d[:-1]), "letztes Byte fehlt"
        assert probe(d[:S.KOPF + S.STUECK + 17]), "nach dem ersten Stück abgeschnitten"
        assert probe(d + b"\0"), "angehängt"
        assert probe(d[:200] + bytes([d[200] ^ 1]) + d[201:]), "Bit im ersten Stück"
        assert probe(d[:30] + bytes([d[30] ^ 1]) + d[31:]), "versiegelter Schlüssel verändert"
        assert probe(d[:4] + bytes([2]) + d[5:]), "andere Fassung"
        s1 = d[S.KOPF:S.KOPF + S.STUECK + 17]; s2 = d[S.KOPF + S.STUECK + 17:S.KOPF + 2 * (S.STUECK + 17)]
        assert probe(d[:S.KOPF] + s2 + s1 + d[S.KOPF + 2 * (S.STUECK + 17):]), "Stücke vertauscht"
        # Fingerabdruck wie PHP sodium_crypto_generichash($pk, '', 16)
        assert len(S.fp_hex(pk)) == 32 and S.fp_hex(pk) != S.fp_hex(pk2)
        assert d[8:24].hex() == S.fp_hex(pk)
        # Schlüsseltexte: Zeilenenden aus FileZilla (ASCII-Modus) und bloße Base64-Zeile
        txt = open(os.path.join(t, "a", "oeffentlich.txt")).read()
        assert S.oeffentlich_lesen(txt.replace("\n", "\r\n")) == pk
        assert S.oeffentlich_lesen(txt.split()[1]) == pk
        assert S.geheim_lesen(open(os.path.join(t, "a", "geheim.key")).read().replace("\n", "\r\n")) == kp
        assert _fehlt(S.geheim_lesen, open(os.path.join(t, "a", "geheim.key")).read().replace(S.GEHEIM, "FCY-GEHEIM-X"))
        print("ok: Verschlüsselung")


if __name__ == "__main__":
    test_schloss()
