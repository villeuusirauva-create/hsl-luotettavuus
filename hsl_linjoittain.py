"""
HSL Runkolinjojen täsmällisyysanalyysi – lähtöpysäkki
=======================================================
Laskee eiliseltä päivältä runkolinjojen täsmällisyyden lähtöpysäkillä.
Vertaa HFP DEP-tapahtumia GTFS:n aikatauluihin.

Täsmällisyysluokat:
  Etuajassa:    lähtö yli 15s ennen aikataulua
  Aikataulussa: -15s ... +60s
  Myöhässä:     +60s ... +180s
  Paljon myöhässä: yli +180s

Tulokset tallennetaan: tulokset/linjoittain_YYYY-MM-DD.json
"""

import os
import io
import json
import zipfile
import datetime
import requests
import zstandard
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
#  ASETUKSET
# ============================================================

ANALYSOITAVA_PAIVA     = None  # None = eilen, tai "2026-05-25"
RINNAKKAISET_LATAUKSET = 4
TULOSKANSIO            = "tulokset"

# Täsmällisyysrajat sekunteina
RAJA_ETUAJASSA   = -15   # alle -15s = etuajassa
RAJA_MYOHASSA    = 60    # yli 60s = myöhässä
RAJA_PALJON      = 180   # yli 180s = paljon myöhässä

# ============================================================

BLOB_BASE_URL = "https://hfpv2.blob.core.windows.net/hfp-v2-prod"
GTFS_URL      = "https://dev.hsl.fi/gtfs/hsl.zip"

# Runkolinjat: linja -> gtfsId
RUNKOLINJAT = {
    "20":  "HSL:1020",
    "30":  "HSL:1030",
    "40":  "HSL:1040",
    "200": "HSL:2200",
    "300": "HSL:4300",
    "400": "HSL:4400",
    "500": "HSL:1500",
    "510": "HSL:2510",
    "520": "HSL:5520",
    "530": "HSL:5530",
    "560": "HSL:4560",
    "570": "HSL:4570",
    "600": "HSL:4600",
}

# Reittiselitteet
RUNKOLINJA_NIMET = {
    "20":  "Eira – Munkkivuori",
    "30":  "Eira – Myyrmäki",
    "40":  "Pelimanni – Elielinaukio",
    "200": "Elielinaukio – Espoon keskus",
    "300": "Elielinaukio – Myyrmäki",
    "400": "Kamppi – Vantaankoski",
    "500": "Itäkeskus – Munkkivuori",
    "510": "Herttoniemi – Kivenlahti",
    "520": "Matinkylä – Martinlaakso",
    "530": "Matinkylä – Myyrmäki",
    "560": "Rastila – Myyrmäki",
    "570": "Lentoasema – Mellunmäki",
    "600": "Rautatientori – Lentoasema",
}


# ── Apufunktiot ─────────────────────────────────────────────

def maarita_paiva():
    if ANALYSOITAVA_PAIVA:
        return datetime.date.fromisoformat(ANALYSOITAVA_PAIVA)
    return datetime.date.today() - datetime.timedelta(days=1)

def pura_zst(data_bytes):
    dctx = zstandard.ZstdDecompressor()
    with dctx.stream_reader(io.BytesIO(data_bytes)) as reader:
        return reader.read()

def normalisoi_aika(aika_str):
    if pd.isna(aika_str):
        return None
    osat = str(aika_str).split(":")
    if len(osat) >= 2:
        tunnit  = int(osat[0]) % 24
        minuutit = int(osat[1])
        sekunnit = int(osat[2]) if len(osat) > 2 else 0
        return tunnit * 3600 + minuutit * 60 + sekunnit
    return None


# ── GTFS ────────────────────────────────────────────────────

def lataa_gtfs():
    print("📥 Ladataan GTFS...")
    r = requests.get(GTFS_URL, timeout=120)
    r.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        trips      = pd.read_csv(z.open("trips.txt"),      dtype=str)
        stop_times = pd.read_csv(z.open("stop_times.txt"), dtype=str)
        routes     = pd.read_csv(z.open("routes.txt"),     dtype=str,
                                 usecols=["route_id","route_short_name"])
        calendar_dates = pd.read_csv(z.open("calendar_dates.txt"), dtype=str)
        cal_df = None
        if "calendar.txt" in z.namelist():
            cal_df = pd.read_csv(z.open("calendar.txt"), dtype=str)

    print(f"  ✓ GTFS ladattu")
    return trips, stop_times, routes, calendar_dates, cal_df


def hae_lahtoajat_gtfs(paiva, trips, stop_times, routes, calendar_dates, cal_df):
    """
    Palauttaa DataFramen: route_id, trip_id, lahtoaika_s (sekunteina)
    vain runkolinjoille ja vain ensimmäiselle pysäkille.
    """
    paiva_str = paiva.strftime("%Y%m%d")

    # Aktiiviset service_id:t
    lisatyt = set(calendar_dates.loc[
        (calendar_dates["date"] == paiva_str) &
        (calendar_dates["exception_type"] == "1"), "service_id"])
    poistetut = set(calendar_dates.loc[
        (calendar_dates["date"] == paiva_str) &
        (calendar_dates["exception_type"] == "2"), "service_id"])

    if not lisatyt and cal_df is not None:
        vp = ["monday","tuesday","wednesday","thursday",
              "friday","saturday","sunday"][paiva.weekday()]
        maski = (
            (cal_df["start_date"] <= paiva_str) &
            (cal_df["end_date"]   >= paiva_str) &
            (cal_df[vp] == "1")
        )
        lisatyt = set(cal_df.loc[maski, "service_id"])

    aktiiviset = lisatyt - poistetut

    # Runkolinja trip_id:t
    runko_route_ids = set(RUNKOLINJAT.values())
    trips_r = trips[
        (trips["service_id"].isin(aktiiviset)) &
        (trips["route_id"].isin(runko_route_ids))
    ].copy()

    # Ensimmäinen pysäkki per trip
    st = stop_times[stop_times["trip_id"].isin(trips_r["trip_id"])]
    st = st.copy()
    st["stop_sequence"] = pd.to_numeric(st["stop_sequence"], errors="coerce")
    ensim = st.sort_values("stop_sequence").groupby("trip_id").first().reset_index()
    ensim["lahtoaika_s"] = ensim["departure_time"].apply(normalisoi_aika)

    tulos = trips_r.merge(ensim[["trip_id","departure_time","lahtoaika_s"]],
                          on="trip_id", how="inner")
    tulos = tulos.merge(routes, on="route_id", how="left")

    print(f"  ✓ {len(tulos):,} runkolinja-vuoroa löytyi GTFS:stä")
    return tulos[["trip_id","route_id","route_short_name","departure_time","lahtoaika_s"]]


# ── HFP DEP-data ────────────────────────────────────────────

def generoi_dep_urlit(paiva):
    """Generoi DEP-tiedostojen URL:t koko päivälle + seuraavan yö."""
    urlit = []
    for tunti in range(24):
        for k in (1, 2, 3, 4):
            nimi = f"{paiva}T{tunti:02d}-{k}_utc_DEP.csv.zst"
            urlit.append(f"{BLOB_BASE_URL}/{nimi}")
    seuraava = paiva + datetime.timedelta(days=1)
    for tunti in range(5):
        for k in (1, 2, 3, 4):
            nimi = f"{seuraava}T{tunti:02d}-{k}_utc_DEP.csv.zst"
            urlit.append(f"{BLOB_BASE_URL}/{nimi}")
    return urlit


def lataa_dep_tiedosto(url):
    try:
        r = requests.get(url, timeout=60)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = pura_zst(r.content)
        df = pd.read_csv(io.BytesIO(data), low_memory=False,
                         usecols=lambda c: c in [
                             "routeId","oday","start","dir",
                             "tst","stop","seq","dl"
                         ])
        return df
    except Exception:
        return None


def hae_dep_data(paiva):
    """Lataa kaikki DEP-tapahtumat eiliseltä."""
    urlit  = generoi_dep_urlit(paiva)
    print(f"🌐 Ladataan DEP-data ({len(urlit)} tiedostoa)...")

    kehykset = []
    valmis   = 0
    virheita = 0

    with ThreadPoolExecutor(max_workers=RINNAKKAISET_LATAUKSET) as executor:
        futures = {executor.submit(lataa_dep_tiedosto, u): u for u in urlit}
        for future in as_completed(futures):
            valmis += 1
            tulos = future.result()
            if tulos is None:
                virheita += 1
            elif len(tulos) > 0:
                kehykset.append(tulos)
            if valmis % 20 == 0 or valmis == len(urlit):
                print(f"  ↳ {valmis}/{len(urlit)} tiedostoa käsitelty")

    if not kehykset:
        print("  ❌ Ei DEP-dataa löytynyt")
        return pd.DataFrame()

    df = pd.concat(kehykset, ignore_index=True)
    print(f"  ✓ {len(df):,} DEP-tapahtumaa ladattu")
    return df


# ── Laskenta ────────────────────────────────────────────────

def luokittele_viive(viive_s):
    if viive_s < RAJA_ETUAJASSA:
        return "etuajassa"
    elif viive_s <= RAJA_MYOHASSA:
        return "aikataulussa"
    elif viive_s <= RAJA_PALJON:
        return "myohassa"
    else:
        return "paljon_myohassa"


def laske_tasmallisuus(paiva, gtfs_df, dep_df):
    """
    Yhdistää GTFS:n lähtöajat DEP-tapahtumiin ja laskee täsmällisyyden.
    """
    if dep_df.empty:
        return {}

    paiva_str = paiva.strftime("%Y-%m-%d")

    # Suodatetaan DEP vain runkolinjoille ja oikealle päivälle
    runko_route_ids = set(RUNKOLINJAT.values())

    # DEP:ssä routeId voi olla lyhyt (esim. "1020") tai pitkä ("HSL:1020")
    dep_df = dep_df.copy()
    dep_df["routeId_norm"] = dep_df["routeId"].astype(str).apply(
        lambda x: f"HSL:{x}" if not x.startswith("HSL:") else x
    )

    dep_runko = dep_df[
        (dep_df["routeId_norm"].isin(runko_route_ids)) &
        (dep_df["oday"] == paiva_str)
    ].copy()

    print(f"  ✓ {len(dep_runko):,} DEP-tapahtumaa runkolinjoille")

    if dep_runko.empty:
        return {}

    # Otetaan vain ensimmäinen pysäkki (seq == min)
    dep_runko["seq"] = pd.to_numeric(dep_runko["seq"], errors="coerce")
    dep_ensim = dep_runko.sort_values("seq").groupby(
        ["routeId_norm","start","dir"]
    ).first().reset_index()

    # `dl` = delay sekunteina HFP:ssä (negatiivinen = etuajassa)
    dep_ensim["viive_s"] = pd.to_numeric(dep_ensim["dl"], errors="coerce")
    dep_ensim = dep_ensim.dropna(subset=["viive_s"])
    dep_ensim["luokka"] = dep_ensim["viive_s"].apply(luokittele_viive)

    # Lasketaan linjoittain
    tulokset = {}
    for linja, gtfs_id in RUNKOLINJAT.items():
        linja_dep = dep_ensim[dep_ensim["routeId_norm"] == gtfs_id]

        n = len(linja_dep)
        if n == 0:
            continue

        luvut = linja_dep["luokka"].value_counts().to_dict()
        etuajassa      = luvut.get("etuajassa", 0)
        aikataulussa   = luvut.get("aikataulussa", 0)
        myohassa       = luvut.get("myohassa", 0)
        paljon_myohassa= luvut.get("paljon_myohassa", 0)

        keskiviive = round(linja_dep["viive_s"].mean(), 1)

        tulokset[linja] = {
            "linja":           linja,
            "nimi":            RUNKOLINJA_NIMET.get(linja, ""),
            "gtfs_id":         gtfs_id,
            "vuoroja":         n,
            "etuajassa":       etuajassa,
            "aikataulussa":    aikataulussa,
            "myohassa":        myohassa,
            "paljon_myohassa": paljon_myohassa,
            "tasmallisuus_pct": round((aikataulussa / n) * 100, 1),
            "keskiviive_s":    keskiviive,
        }

        print(f"  Linja {linja:>3}: {n} vuoroa, "
              f"täsmällisiä {aikataulussa} ({tulokset[linja]['tasmallisuus_pct']}%), "
              f"ka viive {keskiviive}s")

    return tulokset


# ── Tallennus ────────────────────────────────────────────────

def tallenna_tulokset(paiva, tulokset):
    os.makedirs(TULOSKANSIO, exist_ok=True)
    paiva_str = paiva.strftime("%Y-%m-%d")
    polku = os.path.join(TULOSKANSIO, f"linjoittain_{paiva_str}.json")

    data = {
        "paiva":    paiva_str,
        "linjat":   tulokset,
        "rajat": {
            "etuajassa_s":   RAJA_ETUAJASSA,
            "myohassa_s":    RAJA_MYOHASSA,
            "paljon_s":      RAJA_PALJON,
        }
    }

    with open(polku, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"💾 Tallennettu: {polku}")
    return polku


# ── Pääohjelma ───────────────────────────────────────────────

def main():
    print()
    print("🚌  HSL Runkolinjojen täsmällisyysanalyysi")
    print("─" * 50)

    paiva = maarita_paiva()
    print(f"📅  Analysoidaan: {paiva}")
    print()

    # GTFS
    trips, stop_times, routes, calendar_dates, cal_df = lataa_gtfs()
    gtfs_df = hae_lahtoajat_gtfs(
        paiva, trips, stop_times, routes, calendar_dates, cal_df)
    print()

    # HFP DEP
    dep_df = hae_dep_data(paiva)
    print()

    # Laskenta
    print("📊 Lasketaan täsmällisyys...")
    tulokset = laske_tasmallisuus(paiva, gtfs_df, dep_df)
    print()

    # Tallennus
    tallenna_tulokset(paiva, tulokset)

    print()
    print(f"✅  Valmis! {len(tulokset)} linjaa analysoitu.")
    print()


if __name__ == "__main__":
    main()
