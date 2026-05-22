"""
HSL Bussien Luotettavuusanalyysi
=================================
Laskee päivittäisen luotettavuusprosentin:
  Luotettavuus = Ajetut lähdöt / Suunnitellut lähdöt × 100

KÄYTTÖOHJE:
  Avaa komentokehote (CMD) kansiossa jossa tämä tiedosto on, ja aja:
    python hsl_luotettavuus.py

Kirjastojen asennus (vain kerran):
    pip install pandas requests zstandard matplotlib
"""

import os
import io
import zipfile
import datetime
import requests
import zstandard
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
#  ASETUKSET
# ============================================================

TRANSITLAND_API_KEY = "ElFbX1XVXbQZsBXwc4wdREL6ngmyIInE"

# Analysoitava päivä: None = eilen automaattisesti
# Tietty päivä: "2026-05-20"
ANALYSOITAVA_PAIVA = None

# Rinnakkaiset lataukset (nopeuttaa)
RINNAKKAISET_LATAUKSET = 3

# Tulosten tallennuskansio
TULOSKANSIO = "tulokset"

# ============================================================

BLOB_BASE_URL = "https://hfpv2.blob.core.windows.net/hfp-v2-prod"
GTFS_URL      = "https://dev.hsl.fi/gtfs/hsl.zip"

BUSSI_TYYPIT = {"3","700","701","702","703","704","705",
                "706","707","708","709","710","711","712",
                "713","714","715","716"}


# ── Apufunktiot ─────────────────────────────────────────────

def maarita_paiva():
    if ANALYSOITAVA_PAIVA:
        return datetime.date.fromisoformat(ANALYSOITAVA_PAIVA)
    return datetime.date.today() - datetime.timedelta(days=1)

def viikonpaiva(paiva):
    return ["maanantai","tiistai","keskiviikko","torstai",
            "perjantai","lauantai","sunnuntai"][paiva.weekday()]

def pura_zst(data_bytes):
    dctx = zstandard.ZstdDecompressor()
    with dctx.stream_reader(io.BytesIO(data_bytes)) as reader:
        return reader.read()


# ── GTFS ────────────────────────────────────────────────────

def lataa_gtfs(paiva):
    print("📥 Ladataan GTFS-aikataulu HSL:ltä...")
    r = requests.get(GTFS_URL, timeout=120)
    r.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        trips          = pd.read_csv(z.open("trips.txt"),          dtype=str)
        calendar_dates = pd.read_csv(z.open("calendar_dates.txt"), dtype=str)
        routes         = pd.read_csv(z.open("routes.txt"),         dtype=str,
                                     usecols=["route_id","route_type","route_short_name"])
        stop_times     = pd.read_csv(z.open("stop_times.txt"),     dtype=str,
                                     usecols=["trip_id","stop_sequence","departure_time"])
        cal_df = None
        if "calendar.txt" in z.namelist():
            cal_df = pd.read_csv(z.open("calendar.txt"), dtype=str)

    print(f"  ✓ {len(trips):,} reittiajoa, {len(calendar_dates):,} kalenterimerkintää")
    return trips, calendar_dates, routes, stop_times, cal_df


def suunnitellut_bussivuorot(paiva, trips, calendar_dates, routes, stop_times, cal_df=None):
    paiva_str = paiva.strftime("%Y%m%d")

    lisatyt = set(calendar_dates.loc[
        (calendar_dates["date"] == paiva_str) &
        (calendar_dates["exception_type"] == "1"), "service_id"])
    poistetut = set(calendar_dates.loc[
        (calendar_dates["date"] == paiva_str) &
        (calendar_dates["exception_type"] == "2"), "service_id"])

    if not lisatyt and cal_df is not None:
        viikonpaiva_nimi = ["monday","tuesday","wednesday","thursday",
                            "friday","saturday","sunday"][paiva.weekday()]
        maski = (
            (cal_df["start_date"] <= paiva_str) &
            (cal_df["end_date"]   >= paiva_str) &
            (cal_df[viikonpaiva_nimi] == "1")
        )
        lisatyt = set(cal_df.loc[maski, "service_id"])
        print(f"  ✓ calendar.txt: {len(lisatyt)} aktiivista service_id:tä")

    aktiiviset = lisatyt - poistetut

    if not aktiiviset:
        print(f"  ⚠️  Ei palveluja päivälle {paiva_str}")
        return pd.DataFrame()

    trips_r = trips.merge(
        routes[["route_id","route_type","route_short_name"]],
        on="route_id", how="left")

    bussit = trips_r[
        (trips_r["service_id"].isin(aktiiviset)) &
        (trips_r["route_type"].isin(BUSSI_TYYPIT))
    ].copy()

    ensim = (
        stop_times.sort_values("stop_sequence")
        .groupby("trip_id").first().reset_index()
        [["trip_id","departure_time"]]
        .rename(columns={"departure_time":"lahtoaika"})
    )
    bussit = bussit.merge(ensim, on="trip_id", how="left")
    print(f"  ✓ Suunniteltuja bussivuoroja: {len(bussit):,}")
    return bussit[["trip_id","route_id","route_short_name","lahtoaika"]]


# ── HFP-lataus ───────────────────────────────────────────────

def generoi_urlit(paiva):
    urlit = []
    for tunti in range(24):
        for kvarttaali in (1, 2, 3, 4):
            nimi = f"{paiva}T{tunti:02d}-{kvarttaali}_utc_VP.csv.zst"
            urlit.append(f"{BLOB_BASE_URL}/{nimi}")
    return urlit


def lataa_yksi_tiedosto(url):
    try:
        r = requests.get(url, timeout=60)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = pura_zst(r.content)
        df = pd.read_csv(io.BytesIO(data), low_memory=False,
                         usecols=lambda c: c in ["routeId","oday","start","dir"])
        if all(c in df.columns for c in ["routeId","oday","start","dir"]):
            df = df.dropna(subset=["routeId","oday","start","dir"])
            avaimet = (df["routeId"].astype(str) + "|" +
                       df["oday"].astype(str)    + "|" +
                       df["start"].astype(str)   + "|" +
                       df["dir"].astype(str))
            return set(avaimet.unique())
        return set()
    except Exception:
        return None


def hae_ajetut_trip_id(paiva):
    urlit = generoi_urlit(paiva)
    print(f"🌐 Ladataan HFP-data ({len(urlit)} tiedostoa, "
          f"{RINNAKKAISET_LATAUKSET} rinnakkain)...")
    print("   Tämä kestää n. 5–15 minuuttia datan koosta riippuen.")

    ajetut   = set()
    valmis   = 0
    virheita = 0

    with ThreadPoolExecutor(max_workers=RINNAKKAISET_LATAUKSET) as executor:
        futures = {executor.submit(lataa_yksi_tiedosto, u): u for u in urlit}
        for future in as_completed(futures):
            valmis += 1
            tulos = future.result()
            if tulos is None:
                virheita += 1
            else:
                ajetut.update(tulos)
            if valmis % 16 == 0 or valmis == len(urlit):
                print(f"  ↳ {valmis:>3}/{len(urlit)} | "
                      f"{len(ajetut):,} uniikkia trip_id:tä löydetty")

    print(f"  ✓ Valmis. Ajettuja trip_id:tä: {len(ajetut):,} "
          f"({virheita} tiedostoa puuttui / epäonnistui)")
    return ajetut


# ── Laskenta ────────────────────────────────────────────────

def laske_luotettavuus(suunnitellut_df, ajetut_set):
    df = suunnitellut_df.copy()
    df["lahtoaika_lyhyt"] = df["lahtoaika"].str[:5]
    df["avain"] = df["route_id"].astype(str) + "|" + df["lahtoaika_lyhyt"]

    hfp_avaimet = set()
    for a in ajetut_set:
        osat = a.split("|")
        if len(osat) >= 3:
            hfp_avaimet.add(f"{osat[0]}|{osat[2]}")  # routeId|start

    df["ajettu"]   = df["avain"].isin(hfp_avaimet)
    n              = len(df)
    ajettu_n       = int(df["ajettu"].sum())
    ajamatta_n     = n - ajettu_n
    pct            = round((ajettu_n / n) * 100, 2) if n else 0.0
    return {
        "suunnitellut" : n,
        "ajetut"       : ajettu_n,
        "ajamatta"     : ajamatta_n,
        "luotettavuus" : pct,
        "trips_df"     : df,
    }


# ── Raportti & tallennus ─────────────────────────────────────

def tulosta_raportti(paiva, t):
    p = t["luotettavuus"]
    if   p >= 99: ikoni, arvio = "⭐", "Erinomainen"
    elif p >= 97: ikoni, arvio = "✅", "Hyvä"
    elif p >= 95: ikoni, arvio = "🟡", "Kohtuullinen – hieman poikkeamia"
    elif p >= 90: ikoni, arvio = "🟠", "Heikko – merkittäviä puutteita"
    else:         ikoni, arvio = "🔴", "Erittäin heikko – vakavia häiriöitä"

    print()
    print("═" * 52)
    print("  HSL BUSSILIIKENNE – LUOTETTAVUUSRAPORTTI")
    print(f"  {paiva.strftime('%d.%m.%Y')}  ({viikonpaiva(paiva)})")
    print("═" * 52)
    print(f"  Suunniteltuja lähtöjä :  {t['suunnitellut']:>8,}")
    print(f"  Ajettuja lähtöjä      :  {t['ajetut']:>8,}")
    print(f"  Ajamatta jääneitä     :  {t['ajamatta']:>8,}")
    print("  " + "─" * 38)
    print(f"  LUOTETTAVUUS          :  {p:>7.2f} %")
    print("═" * 52)
    print(f"  {ikoni}  {arvio}")
    print()


def tallenna_tulokset(paiva, t):
    os.makedirs(TULOSKANSIO, exist_ok=True)
    paiva_str = paiva.strftime("%Y-%m-%d")

    csv_polku = os.path.join(TULOSKANSIO, f"raportti_{paiva_str}.csv")
    t["trips_df"].to_csv(csv_polku, index=False, encoding="utf-8-sig")

    trendi_polku = os.path.join(TULOSKANSIO, "trendi.csv")
    uusi = pd.DataFrame([{
        "paiva"        : paiva_str,
        "suunnitellut" : t["suunnitellut"],
        "ajetut"       : t["ajetut"],
        "ajamatta"     : t["ajamatta"],
        "luotettavuus" : t["luotettavuus"],
    }])
    if os.path.exists(trendi_polku):
        trendi = pd.read_csv(trendi_polku)
        trendi = trendi[trendi["paiva"] != paiva_str]
        trendi = pd.concat([trendi, uusi], ignore_index=True)
    else:
        trendi = uusi
    trendi = trendi.sort_values("paiva").reset_index(drop=True)
    trendi.to_csv(trendi_polku, index=False, encoding="utf-8-sig")

    print(f"💾 Raportti  → {csv_polku}")
    print(f"📈 Trendidata → {trendi_polku}  ({len(trendi)} päivää)")
    return trendi


def piirra_kuvaaja(trendi_df):
    if len(trendi_df) < 2:
        print("ℹ️  Trendikuvaaja piirretään kun dataa on kahdelta päivältä.")
        return

    fig, ax = plt.subplots(figsize=(13, 5))
    fig.patch.set_facecolor("#0f1923")
    ax.set_facecolor("#141f2e")

    paivamaarat    = pd.to_datetime(trendi_df["paiva"])
    luotettavuudet = trendi_df["luotettavuus"]

    for i in range(len(paivamaarat) - 1):
        v = luotettavuudet.iloc[i]
        c = ("#00c896" if v >= 99 else "#4fc3f7" if v >= 97
             else "#ffd54f" if v >= 95 else "#ff8a65" if v >= 90 else "#ef5350")
        ax.plot(paivamaarat.iloc[i:i+2], luotettavuudet.iloc[i:i+2],
                color=c, linewidth=2.5, solid_capstyle="round")

    ax.fill_between(paivamaarat, luotettavuudet,
                    luotettavuudet.min() - 1, alpha=0.12, color="#4fc3f7")

    for raja, teksti, vari in [(99,"99 %","#00c896"),
                                (97,"97 %","#4fc3f7"),
                                (95,"95 %","#ffd54f")]:
        ax.axhline(raja, linestyle="--", linewidth=0.8, color=vari, alpha=0.45)
        ax.text(paivamaarat.iloc[0], raja + 0.08, teksti,
                color=vari, fontsize=7.5, alpha=0.7, va="bottom")

    ax.scatter(paivamaarat, luotettavuudet,
               color="white", s=35, zorder=5, alpha=0.85)

    viim_x = paivamaarat.iloc[-1]
    viim_y = luotettavuudet.iloc[-1]
    ax.annotate(
        f"{viim_y:.1f} %",
        xy=(viim_x, viim_y), xytext=(12, 8), textcoords="offset points",
        color="white", fontsize=11, fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.35",
                  facecolor="#0f3460", edgecolor="#4fc3f7", alpha=0.9),
        arrowprops=dict(arrowstyle="->", color="#4fc3f7", lw=1.2)
    )

    ymin = max(85, luotettavuudet.min() - 1.5)
    ax.set_ylim(ymin, 100.6)
    ax.set_xlabel("Päivä", color="#8899bb", fontsize=10)
    ax.set_ylabel("Luotettavuus (%)", color="#8899bb", fontsize=10)
    ax.set_title("HSL Bussiliikenne – Päivittäinen luotettavuus",
                 color="white", fontsize=13, fontweight="bold", pad=14)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m."))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.xticks(rotation=40, color="#8899bb", fontsize=8)
    plt.yticks(color="#8899bb")
    for sp in ax.spines.values():
        sp.set_edgecolor("#2a3a5a")
    ax.grid(axis="y", linestyle=":", alpha=0.25, color="#8899bb")

    plt.tight_layout()
    polku = os.path.join(TULOSKANSIO, "luotettavuus_trendi.png")
    plt.savefig(polku, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"📊 Kuvaaja    → {polku}")


# ── Pääohjelma ───────────────────────────────────────────────

def main():
    print()
    print("🚌  HSL Luotettavuusanalyysi käynnistyy")
    print("─" * 45)

    paiva = maarita_paiva()
    print(f"📅  Analysoidaan: {paiva.strftime('%d.%m.%Y')} ({viikonpaiva(paiva)})")
    print()

    trips, calendar_dates, routes, stop_times, cal_df = lataa_gtfs(paiva)
    print()

    suunnitellut = suunnitellut_bussivuorot(
        paiva, trips, calendar_dates, routes, stop_times, cal_df)
    if suunnitellut.empty:
        print("❌  Ei suunniteltuja vuoroja – tarkista päivämäärä.")
        return
    print()

    ajetut = hae_ajetut_trip_id(paiva)
    print()

    tulos  = laske_luotettavuus(suunnitellut, ajetut)
    tulosta_raportti(paiva, tulos)

    trendi = tallenna_tulokset(paiva, tulos)
    piirra_kuvaaja(trendi)

    print()
    print(f"✅  Valmis! Tulokset: {os.path.abspath(TULOSKANSIO)}")
    print()


if __name__ == "__main__":
    main()
