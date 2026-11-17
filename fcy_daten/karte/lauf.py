"""Job „Karte“: ICAO-Optik für ganz Deutschland je AIRAC-Zyklus rechnen, prüfen und veröffentlichen.

  1. Plan: welche Zyklen (laufender, nächster) gibt es bei der DFS, welche stehen schon in karte.bin des Release „daten“?
  2. Grunddaten (einmal, im Zwischenspeicher des Jobs): BKG DLM250 und DGM200, OurAirports, Copernicus GLO-30 → topo.pkl,
     dgm200.npz, Gelände-Raster
  3. Je fehlendem Zyklus: Luftfahrtdaten (DFS, open flightmaps), Flugplätze, Kacheln, Bündel, Prüfung
  4. Veröffentlichen (ab Build 25y nur verschlüsselt, Accountable Manager 17.11.2026): jedes neue Bündel als <bündel>.v für den Schlüssel
     des Servers (fcy_daten/schluessel.pub), dann das Verzeichnis karte-verzeichnis.bin und .json (Beschreibung zuletzt);
     alte Zyklen nach Ablauf entfernen. Das Verzeichnis bleibt lesbar (Zyklen, Dateinamen, Größen, Prüfsummen, Fingerabdruck
     des Schlüssels, Umriss Deutschlands, Quellen); die Kartenbilder kann nur der Server lesen. Ohne Schlüssel im Repository
     veröffentlicht der Job nichts (und rechnet im täglichen Lauf gar nicht erst).

Aufruf: python -m fcy_daten.karte.lauf --arbeit <Ordner> --aus out/karte [--zyklen auto|0|1|0,1] [--veroeffentlichen]
        [--gebiet lon0 lat0 lon1 lat1] [--zoom 8 12] [--prozesse N]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import zipfile

from .. import luftraum_dfs as LD
from .. import netz
from .. import schloss as S
from . import buendel as BU

BKG_DLM = "https://daten.gdz.bkg.bund.de/produkte/dlm/dlm250/aktuell/dlm250.utm32s.shape.ebenen.zip"
BKG_DGM = "https://daten.gdz.bkg.bund.de/produkte/dgm/dgm200/aktuell/dgm200.utm32s.tiff.zip"
OA = "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/{n}.csv"
COP = "https://copernicus-dem-30m.s3.amazonaws.com/{n}/{n}.tif"
RELEASE = "https://github.com/flycademy/flightlog-daten/releases/download/daten/"
TAG = "daten"
VERZ = "karte-verzeichnis.bin"      # ab 25y; „karte.bin“ (Build 25x) wird nie veröffentlicht
HIER = os.path.dirname(os.path.abspath(__file__))


def log(*a):
    print(*a, flush=True)


def plan(wahl: str) -> list[dict]:
    zy = []
    for n in (0, 1):
        try:
            u = LD.uebersicht(n)
        except Exception as e:                       # noqa: BLE001
            log(f"DFS-Übersicht {n}: {e}"); u = None
        if u:
            zy.append({"n": n, "zyklus": LD.zyklus_von(u["airac"]), "ab": u["airac"]})
    if wahl != "auto":
        ns = {int(x) for x in wahl.split(",")}
        return [z for z in zy if z["n"] in ns]
    roh = netz.hole(RELEASE + VERZ, ok404=True)
    da = set()
    if roh:
        tmp = os.path.join("/tmp", "karte_alt.bin"); open(tmp, "wb").write(roh)
        alt = BU.verzeichnis_lesen(tmp)
        pk = S.oeffentlich_laden()
        if pk is not None and alt.get("schluessel") == S.fp_hex(pk):
            da = {z["zyklus"] for z in alt.get("zyklen", [])}
        else:
            log("Verzeichnis für einen anderen Schlüssel: alle Zyklen neu")   # z. B. neuer Schlüssel auf dem Server
    return [z for z in zy if z["zyklus"] not in da]


def grunddaten(arbeit: str, roh: str, prozesse: int):
    os.makedirs(arbeit, exist_ok=True); os.makedirs(roh, exist_ok=True)
    t0 = time.time()
    dlm = os.path.join(roh, "dlm"); dgm = os.path.join(roh, "dgm"); oa = os.path.join(roh, "oa"); cop = os.path.join(roh, "cop")
    if not os.path.isdir(dlm):                         # für die Flugplätze je Zyklus immer gebraucht
        zipfile.ZipFile(io.BytesIO(netz.hole(BKG_DLM, timeout=600))).extractall(dlm)
    if not os.path.isdir(oa):
        os.makedirs(oa + ".neu", exist_ok=True)
        for n in ("airports", "runways", "airport-frequencies"):
            open(os.path.join(oa + ".neu", n + ".csv"), "wb").write(netz.hole(OA.format(n=n), timeout=120))
        os.replace(oa + ".neu", oa)
    fertig = all(os.path.exists(os.path.join(arbeit, f)) for f in ("topo.pkl", "dgm200.npz", "gelaende.json", "gelaende_z8_dk.npy"))
    if fertig:
        log("Grunddaten aus dem Zwischenspeicher"); return
    if not os.path.isdir(dgm):
        zipfile.ZipFile(io.BytesIO(netz.hole(BKG_DGM, timeout=300))).extractall(dgm)
    os.makedirs(cop, exist_ok=True)
    import rasterio
    for la in range(47, 56):
        for lo in range(5, 16):
            n = f"Copernicus_DSM_COG_10_N{la:02d}_00_E{lo:03d}_00_DEM"; f = os.path.join(cop, n + ".tif")
            if os.path.exists(f):
                continue
            d = netz.hole(COP.format(n=n), timeout=600, ok404=True)
            if d:
                open(f + ".neu", "wb").write(d)
                with rasterio.open(f + ".neu") as r:
                    r.read(1)                         # ganz lesbar? (eine abgebrochene Übertragung fällt hier auf)
                os.replace(f + ".neu", f)
    log(f"Rohdaten geladen ({time.time() - t0:.0f} s)")
    dlm_e = os.path.join(dlm, "dlm250_ebenen")
    dgm_t = os.path.join(dgm, "dgm200", "dgm200_utm32s.tif")
    _py("fcy_daten.karte.daten", "--dlm", dlm_e, "--dgm", dgm_t, "--oa", oa, "--aus", arbeit)
    _py("fcy_daten.karte.gelaende", "--cop", cop, "--arbeit", arbeit)


def _py(mod, *args):
    r = subprocess.run([sys.executable, "-m", mod, *args])
    if r.returncode:
        raise SystemExit(f"{mod} fehlgeschlagen ({r.returncode})")


def zyklus_rechnen(z: dict, arbeit: str, roh: str, aus: str, zoom, gebiet, prozesse) -> str:
    zk = z["zyklus"]; t0 = time.time()
    lr = os.path.join(arbeit, "luftraum.bin")
    if not os.path.exists(lr):                       # ab 25y selbst rechnen (die Datei im Release ist verschlüsselt)
        _py("fcy_daten.luftraum", "--aus", lr)
    _py("fcy_daten.karte.luftfahrt", "--arbeit", arbeit, "--luftraum", lr, "--n", str(z["n"]))
    ofm_ad = os.path.join(arbeit, f"ofm_plaetze_{zk}.json")
    try:
        _py("fcy_daten.karte.ofm", "--zyklus", zk, "--aus", ofm_ad)
    except SystemExit as e:
        log(f"open flightmaps {zk} nicht verfügbar ({e}) — Frequenzen und Pisten aus OurAirports"); ofm_ad = None
    import json as _j
    from . import daten as DA
    P = DA.plaetze(os.path.join(roh, "dlm", "dlm250_ebenen"), os.path.join(roh, "oa"), None, _j.load(open(ofm_ad)) if ofm_ad else None)
    _j.dump(P, open(os.path.join(arbeit, f"plaetze_{zk}.json"), "w", encoding="utf-8"), ensure_ascii=False)
    kach = os.path.join(arbeit, f"kacheln_{zk}")
    args = ["--arbeit", arbeit, "--zyklus", zk, "--aus", kach, "--zoom", str(zoom[0]), str(zoom[1]), "--prozesse", str(prozesse)]
    if gebiet:
        args += ["--gebiet", *[str(v) for v in gebiet]]
    _py("fcy_daten.karte.zeichne", *args)
    _py("fcy_daten.karte.buendel", "--kacheln", kach, "--zyklus", zk, "--ab", z["ab"], "--aus", aus, "--deckung", os.path.join(arbeit, "deckung.json"),
        "--alt", os.path.join(aus, "karte.bin"))
    log(f"Zyklus {zk}: fertig in {(time.time() - t0) / 60:.0f} min")
    return zk


def deckung(arbeit: str):
    """Umriss Deutschlands für die App (Teile über 20 km², auf rund 300 m vereinfacht), [[lat, lon], …] je Teil"""
    import pickle
    from pyproj import Transformer
    import shapely
    p = os.path.join(arbeit, "deckung.json")
    if os.path.exists(p):
        return
    de = pickle.load(open(os.path.join(arbeit, "topo.pkl"), "rb"))["de"]
    m2l = Transformer.from_crs(3857, 4326, always_xy=True)
    out = []
    for q in getattr(de, "geoms", [de]):
        if q.area < 20e6 * 2.6:
            continue
        s = shapely.simplify(q, 500, preserve_topology=True)
        lo, la = m2l.transform(*zip(*s.exterior.coords))
        out.append([[round(b, 4), round(a, 4)] for a, b in zip(lo, la)])
    json.dump(out, open(p, "w"))


def veroeffentlichen(aus: str):
    pk = S.oeffentlich_laden()
    if pk is None:
        raise SystemExit("kein öffentlicher Schlüssel des Servers in fcy_daten/schluessel.pub — nichts veröffentlicht")
    fp = S.fp_hex(pk)
    v = BU.verzeichnis_lesen(os.path.join(aus, "karte.bin"))
    neu = 0
    for z in v["zyklen"]:
        for n, d in z["dateien"].items():
            p = os.path.join(aus, n)
            if os.path.exists(p):                    # in diesem Lauf gerechnet: verschlüsseln und hochladen
                r = S.verschluesseln(p, p + ".v", pk)
                assert r["klar_sha256"] == d["sha256"] and r["klar_groesse"] == d["groesse"], n
                d["v"] = {"groesse": r["groesse"], "sha256": r["sha256"]}
                subprocess.run(["gh", "release", "upload", TAG, p + ".v", "--clobber"], check=True)
                neu += 1
            elif "v" not in d:
                raise SystemExit(f"{n}: weder in diesem Lauf gerechnet noch verschlüsselt veröffentlicht")
    log(f"hochgeladen: {neu} Bündel (verschlüsselt, Schlüssel {fp})")
    v["schluessel"] = fp
    BU.verzeichnis_schreiben(os.path.join(aus, VERZ), v)
    d = open(os.path.join(aus, VERZ), "rb").read()
    beschr = {"datei": VERZ, "art": "karte", "groesse": len(d), "sha256": hashlib.sha256(d).hexdigest(), "schluessel": fp,
              "fassung": "+".join(z["zyklus"] for z in v["zyklen"]), "veroeffentlicht": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    json.dump(beschr, open(os.path.join(aus, VERZ + ".json"), "w"))
    subprocess.run(["gh", "release", "upload", TAG, os.path.join(aus, VERZ), "--clobber"], check=True)
    subprocess.run(["gh", "release", "upload", TAG, os.path.join(aus, VERZ + ".json"), "--clobber"], check=True)
    log(f"{VERZ} veröffentlicht: Zyklen {beschr['fassung']}")
    # Bündel abgelaufener Zyklen entfernen (zwei Tage nach dem Ende, damit Server mit altem Verzeichnis nicht ins Leere greifen)
    behalten = {n + ".v" for z in v["zyklen"] for n in z["dateien"]}
    r = subprocess.run(["gh", "release", "view", TAG, "--json", "assets", "--jq", ".assets[].name"], capture_output=True, text=True, check=True)
    from ..luftraum import zyklus as _zyklus
    grenze = _zyklus(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2))[0]   # laufender Zyklus vor zwei Tagen
    for n in r.stdout.split():
        if n.startswith("karte-") and (n.endswith(".bin") or n.endswith(".bin.v")) and n not in behalten:
            zk = n.split("-")[1]
            if zk.isdigit() and len(zk) == 4 and (zk < grenze or n.endswith(".bin")):    # offene Bündel nie stehen lassen
                subprocess.run(["gh", "release", "delete-asset", TAG, n, "--yes"], check=False)
                log(f"entfernt: {n}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arbeit", required=True); ap.add_argument("--roh", required=True); ap.add_argument("--aus", required=True)
    ap.add_argument("--zyklen", default="auto"); ap.add_argument("--veroeffentlichen", action="store_true")
    ap.add_argument("--gebiet", nargs=4, type=float); ap.add_argument("--zoom", nargs=2, type=int, default=[8, 12])
    ap.add_argument("--prozesse", type=int, default=os.cpu_count() or 1)
    a = ap.parse_args(argv)
    os.makedirs(a.aus, exist_ok=True)
    if a.veroeffentlichen and S.oeffentlich_laden() is None:
        log("kein öffentlicher Schlüssel des Servers in fcy_daten/schluessel.pub — die Karte wird erst gerechnet, wenn er eingetragen ist")
        return 0
    zy = plan(a.zyklen)
    log("zu rechnen:", ", ".join(f"{z['zyklus']} (ab {z['ab']})" for z in zy) or "nichts")
    if not zy:
        return 0
    alt = netz.hole(RELEASE + VERZ, ok404=True)      # übrige Zyklen übernehmen, wenn sie für denselben Schlüssel verschlüsselt sind
    pk = S.oeffentlich_laden()
    if alt and (pk is None or BU.verzeichnis_lesen_bytes(alt).get("schluessel") != S.fp_hex(pk)):
        alt = None
    if alt:
        open(os.path.join(a.aus, "karte.bin"), "wb").write(alt)
    grunddaten(a.arbeit, a.roh, a.prozesse)
    deckung(a.arbeit)
    for z in zy:
        zyklus_rechnen(z, a.arbeit, a.roh, a.aus, a.zoom, a.gebiet, a.prozesse)
    _py("fcy_daten.karte.pruefen", os.path.join(a.aus, "karte.bin"), "--gebiet" if a.gebiet else "--voll")
    if a.veroeffentlichen:
        veroeffentlichen(a.aus)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
