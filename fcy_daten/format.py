"""Dateiformate der FlyCademy-Flight-Log-Daten (Wind, Gelände, Orte).

Alle drei Dateien haben denselben Aufbau:
  Byte 0–3     Kennung (b"FCYW", b"FCYG", b"FCYO")
  Byte 4–7     Länge des Kopfes in Byte (uint32, little endian)
  Byte 8–…     Kopf als JSON (UTF-8), mit Leerzeichen auf KOPF_BYTES aufgefüllt
  ab KOPF_BYTES  Index und Daten; alle Positionen im Kopf sind absolut ab Dateianfang.

Gelesen werden die Dateien von der Server-Abfrage des Flight Log (PHP, private/flightlog/dienst.php)
und von den Prüfungen hier (lese_* unten). Beide müssen zu diesem Modul passen.
"""
from __future__ import annotations

import gzip
import json
import struct
import unicodedata

import numpy as np

KOPF_BYTES = 8192
FEHLT_I8 = -128          # Wind/Temperatur in Höhen: fehlt (unter Gelände, außerhalb)
FEHLT_I16 = -32768       # Bodenwerte am Platz: fehlt


# ----------------------------------------------------------------------------------------------
# gemeinsam
# ----------------------------------------------------------------------------------------------
def _kopf_schreiben(f, kennung: bytes, kopf: dict) -> None:
    js = json.dumps(kopf, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(js) + 8 > KOPF_BYTES:
        raise ValueError(f"Kopf zu groß ({len(js)} Byte)")
    f.seek(0)
    f.write(kennung + struct.pack("<I", len(js)) + js + b" " * (KOPF_BYTES - 8 - len(js)))


def kopf_lesen(daten: bytes, kennung: bytes) -> dict:
    if daten[:4] != kennung:
        raise ValueError(f"keine {kennung!r}-Datei")
    n = struct.unpack("<I", daten[4:8])[0]
    return json.loads(daten[8:8 + n].decode("utf-8"))


def gz(b: bytes) -> bytes:
    """gzip ohne Zeitstempel (gleiche Eingabe → gleiche Datei)."""
    return gzip.compress(b, compresslevel=9, mtime=0)


# ----------------------------------------------------------------------------------------------
# Wind (FCYW): ICON-D2, Höhen fest in ft MSL, Kacheln aus kachel × kachel Gitterpunkten
# ----------------------------------------------------------------------------------------------
def schreibe_wind(pfad: str, kopf: dict, u_kt: np.ndarray, v_kt: np.ndarray, t_c: np.ndarray,
                  plaetze: list[tuple[str, np.ndarray]]) -> dict:
    """u_kt, v_kt, t_c: float-Arrays [schritt, hoehe, nlat, nlon] (NaN = fehlt), Gitter von Süd nach Nord, West nach Ost.
    plaetze: Liste (ICAO, Array [boden_schritt, 6]) mit t2m °C, td2m °C, pmsl hPa, u10 kt, v10 kt, vmax10 kt (NaN = fehlt).
    kopf: modell, lauf, erzeugt, quelle, hoehen_ft, schritte_h, boden_schritte_h, gitter{lat0, lon0, d, nlat, nlon}."""
    ns, na, nlat, nlon = u_kt.shape
    k = int(kopf.get("kachel", 10))
    nkl, nko = -(-nlat // k), -(-nlon // k)

    def q8(a, lo, hi):
        b = np.where(np.isfinite(a), np.clip(np.rint(a), lo, hi), FEHLT_I8)
        return b.astype(np.int8)

    U, V, T = q8(u_kt, -127, 127), q8(v_kt, -127, 127), q8(t_c, -127, 127)
    # auf volle Kacheln auffüllen
    def pad(a):
        p = np.full((ns, na, nkl * k, nko * k), FEHLT_I8, dtype=np.int8)
        p[:, :, :nlat, :nlon] = a
        return p
    U, V, T = pad(U), pad(V), pad(T)
    # je Punkt: [schritt][hoehe][u, v, t]
    alle = np.stack([U, V, T], axis=-1)              # ns, na, LAT, LON, 3
    alle = np.transpose(alle, (2, 3, 0, 1, 4))       # LAT, LON, ns, na, 3

    kopf = dict(kopf)
    kopf.update({"format": "FCYW", "version": 1, "kachel": k, "nkl": nkl, "nko": nko,
                 "punkt_bytes": ns * na * 3, "fehlt": FEHLT_I8, "einheiten": {"u": "kt", "v": "kt", "t": "°C"}})
    with open(pfad, "w+b") as f:
        f.write(b"\0" * KOPF_BYTES)
        index_ab = f.tell()
        f.write(b"\0" * (nkl * nko * 8))
        index = []
        for i in range(nkl):
            for j in range(nko):
                blk = alle[i * k:(i + 1) * k, j * k:(j + 1) * k].tobytes()
                z = gz(blk)
                index.append((f.tell(), len(z)))
                f.write(z)
        # Plätze: sortiert nach ICAO, je Satz 4 Byte ICAO + int16[boden_schritte][6]
        plaetze = sorted(plaetze, key=lambda x: x[0])
        nb = len(kopf["boden_schritte_h"])
        skala = [10, 10, 10, 10, 10, 10]
        plaetze_ab = f.tell()
        for icao, arr in plaetze:
            a = np.asarray(arr, dtype=float).reshape(nb, 6) * np.array(skala, dtype=float)
            b = np.where(np.isfinite(a), np.clip(np.rint(a), -32767, 32767), FEHLT_I16).astype("<i2")
            f.write(icao.encode("ascii")[:4].ljust(4, b" ") + b.tobytes())
        kopf.update({"index_ab": index_ab,
                     "plaetze": {"ab": plaetze_ab, "anzahl": len(plaetze), "satz_bytes": 4 + nb * 6 * 2,
                                 "felder": ["t2m", "td2m", "pmsl", "u10", "v10", "vmax10"], "skala": skala,
                                 "fehlt": FEHLT_I16}})
        f.seek(index_ab)
        f.write(b"".join(struct.pack("<II", o, n) for o, n in index))
        _kopf_schreiben(f, b"FCYW", kopf)
    return kopf


def lese_wind_punkt(daten: bytes, i: int, j: int) -> np.ndarray | None:
    """Rohwerte eines Gitterpunkts (int8 [schritt, hoehe, 3]) — für Prüfungen."""
    K = kopf_lesen(daten, b"FCYW")
    g, k = K["gitter"], K["kachel"]
    if not (0 <= i < g["nlat"] and 0 <= j < g["nlon"]):
        return None
    ti, tj = i // k, j // k
    o, n = struct.unpack_from("<II", daten, K["index_ab"] + (ti * K["nko"] + tj) * 8)
    blk = np.frombuffer(gzip.decompress(daten[o:o + n]), dtype=np.int8)
    ns, na = len(K["schritte_h"]), len(K["hoehen_ft"])
    blk = blk.reshape(k, k, ns, na, 3)
    return blk[i % k, j % k]


def lese_platz(daten: bytes, icao: str) -> np.ndarray | None:
    K = kopf_lesen(daten, b"FCYW")
    P = K["plaetze"]
    lo, hi = 0, P["anzahl"] - 1
    want = icao.encode("ascii")
    while lo <= hi:
        m = (lo + hi) // 2
        o = P["ab"] + m * P["satz_bytes"]
        c = daten[o:o + 4]
        if c == want:
            a = np.frombuffer(daten[o + 4:o + P["satz_bytes"]], dtype="<i2").astype(float).reshape(-1, 6)
            a[a == P["fehlt"]] = np.nan
            return a / np.array(P["skala"], dtype=float)
        if c < want:
            lo = m + 1
        else:
            hi = m - 1
    return None


# ----------------------------------------------------------------------------------------------
# Gelände (FCYG): je 1°-Kachel n × n Zellen, Wert = HÖCHSTER Geländepunkt der Zelle in m (int16)
# Zeile 0 = Nordrand, Spalte 0 = Westrand. Kachel N52E010 = 52–53° N, 10–11° E.
# ----------------------------------------------------------------------------------------------
GELAENDE_MEER = 0            # Länge 0 im Index: keine Copernicus-Kachel = Meer (überall 0 m)
GELAENDE_FEHLT = 0xFFFFFFFF  # Position im Index: Kachel konnte nicht erzeugt werden (unbekannt)


def kachel_name(lat: int, lon: int) -> str:
    return f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"


def schreibe_gelaende(pfad: str, kopf: dict, kacheln: dict) -> dict:
    """kacheln: {(lat, lon): np.int16-Array n×n | "meer" | None (fehlt)}"""
    lat0, lat1, lon0, lon1, n = kopf["lat0"], kopf["lat1"], kopf["lon0"], kopf["lon1"], kopf["n"]
    nl, no = lat1 - lat0, lon1 - lon0
    kopf = dict(kopf)
    kopf.update({"format": "FCYG", "version": 1, "wert": "max", "einheit": "m", "zeile0": "Nord"})
    with open(pfad, "w+b") as f:
        f.write(b"\0" * KOPF_BYTES)
        index_ab = f.tell()
        f.write(b"\0" * (nl * no * 8))
        index = []
        land = meer = fehlt = 0
        for la in range(lat0, lat1):
            for lo in range(lon0, lon1):
                k = kacheln.get((la, lo))
                if isinstance(k, str) and k == "meer":
                    index.append((0, 0)); meer += 1
                elif k is None:
                    index.append((GELAENDE_FEHLT, 0)); fehlt += 1
                else:
                    a = np.asarray(k, dtype="<i2")
                    assert a.shape == (n, n)
                    z = gz(a.tobytes())
                    index.append((f.tell(), len(z))); f.write(z); land += 1
        kopf.update({"index_ab": index_ab, "kacheln_land": land, "kacheln_meer": meer, "kacheln_fehlt": fehlt})
        f.seek(index_ab)
        f.write(b"".join(struct.pack("<II", o, m) for o, m in index))
        _kopf_schreiben(f, b"FCYG", kopf)
    return kopf


def lese_gelaende_kachel(daten: bytes, lat: int, lon: int):
    K = kopf_lesen(daten, b"FCYG")
    if not (K["lat0"] <= lat < K["lat1"] and K["lon0"] <= lon < K["lon1"]):
        return None
    no = K["lon1"] - K["lon0"]
    o, m = struct.unpack_from("<II", daten, K["index_ab"] + ((lat - K["lat0"]) * no + (lon - K["lon0"])) * 8)
    if o == GELAENDE_FEHLT:
        return None
    if m == 0:
        return "meer"
    return np.frombuffer(gzip.decompress(daten[o:o + m]), dtype="<i2").reshape(K["n"], K["n"])


# ----------------------------------------------------------------------------------------------
# Orte (FCYO): Zeilen "schluessel\tid\tname\tland1\tcc\tlat\tlon\tew\tklasse\n", sortiert nach Schlüssel (Bytes),
# danach uint32-Index der Zeilenanfänge. Suche: Präfix des normierten Schlüssels.
# ----------------------------------------------------------------------------------------------
def _tabelle() -> dict:
    """Zeichen außerhalb a–z/0–9 → Ersatz (klein, ASCII). Lateinische Buchstaben mit Akzent werden zum Grundbuchstaben.
    Dieselbe Tabelle steht in dienst.php (FL_TRANS, erzeugt mit php_tabelle())."""
    t = {}
    for cp in list(range(0xC0, 0x250)) + [0x1E9E]:
        ch = chr(cp)
        if unicodedata.category(ch)[0] != "L":
            continue
        base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c)).lower()
        if base and all("a" <= c <= "z" for c in base):
            t[ch] = base
    t.update({"ß": "ss", "ẞ": "ss", "æ": "ae", "Æ": "ae", "ø": "o", "Ø": "o", "œ": "oe", "Œ": "oe", "đ": "d", "Đ": "d",
              "ł": "l", "Ł": "l", "ı": "i", "þ": "th", "Þ": "th", "ð": "d", "Ð": "d", "ŋ": "n", "Ŋ": "n", "ħ": "h", "Ħ": "h",
              "ŧ": "t", "Ŧ": "t", "ĸ": "k", "ſ": "s"})
    return t


TRANS = _tabelle()


def normiere(s: str) -> str:
    """Suchschlüssel: A–Z → a–z, Akzente weg (TRANS), sonst Leerzeichen; dann ae → a, oe → o, ue → u;
    Leerzeichen zusammenfassen. Muss genau zu fl_normiere() in dienst.php passen."""
    out = []
    for ch in s:
        if "A" <= ch <= "Z":
            out.append(ch.lower())
        elif ("a" <= ch <= "z") or ("0" <= ch <= "9"):
            out.append(ch)
        else:
            out.append(TRANS.get(ch, " "))
    x = "".join(out)
    for a_, b_ in (("ae", "a"), ("oe", "o"), ("ue", "u")):
        x = x.replace(a_, b_)
    return " ".join(x.split())


def php_tabelle() -> str:
    teile = [f"'{k}'=>'{v}'" for k, v in sorted(TRANS.items())]
    return "const FL_TRANS = [" + ",".join(teile) + "];"


def schreibe_orte(pfad: str, kopf: dict, zeilen: list[tuple]) -> dict:
    """zeilen: (schluessel, id, name, land1, cc, lat, lon, einwohner, klasse)"""
    def sauber(x):
        return str(x).replace("\t", " ").replace("\n", " ")
    roh = sorted({(z[0].encode("utf-8"),) + tuple(z[1:]) for z in zeilen if z[0]}, key=lambda z: (z[0], -int(z[7] or 0), str(z[1])))
    kopf = dict(kopf)
    kopf.update({"format": "FCYO", "version": 1, "spalten": ["schluessel", "id", "name", "land1", "cc", "lat", "lon", "einwohner", "klasse"]})
    with open(pfad, "w+b") as f:
        f.write(b"\0" * KOPF_BYTES)
        pos = []
        for z in roh:
            pos.append(f.tell())
            line = b"\t".join([z[0]] + [sauber(x).encode("utf-8") for x in (z[1], z[2], z[3], z[4], f"{float(z[5]):.4f}", f"{float(z[6]):.4f}", int(z[7] or 0), z[8])]) + b"\n"
            f.write(line)
        index_ab = f.tell()
        f.write(b"".join(struct.pack("<I", p) for p in pos))
        kopf.update({"anzahl": len(pos), "index_ab": index_ab})
        _kopf_schreiben(f, b"FCYO", kopf)
    return kopf
