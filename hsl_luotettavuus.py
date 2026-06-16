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
 
ANALYSOITAVA_PAIVA     = None
RINNAKKAISET_LATAUKSET = 3
TULOSKANSIO            = "tulokset"
 
# Operaattorit joiden trendi piirretään kuvaajaan
TRENDI_OPERAATTORIT = [
    "Nobina Finland",
    "Koiviston Auto",
    "Pohjolan Liikenne",
    "Tammelundin Liikenne",
]
 
# ============================================================
 
BLOB_BASE_URL = "https://hfpv2.blob.core.windows.net/hfp-v2-prod"
GTFS_URL      = "https://dev.hsl.fi/gtfs/hsl.zip"
 
BUSSI_TYYPIT = {"3","700","701","702","703","704","705",
                "706","707","708","709","710","711","712",
                "713","714","715","716"}
 
OPERAATTORIT = {
    "6":  "Pohjolan Liikenne",
    "12": "Koiviston Auto",
    "17": "Tammelundin Liikenne",
    "18": "Pohjolan Liikenne",
    "20": "Bus Travel Åbergin Linja",
    "21": "Bus Travel Reissu Ruoti",
    "22": "Nobina Finland",
    "30": "Savonlinja",
    "36": "Nurmijärven Linja",
    "40": "HKL-Raitioliikenne",
    "47": "Taksikuljetus Oy",
    "50": "HKL-Metroliikenne",
    "51": "Korsisaari",
    "54": "V-S Bussipalvelut",
    "58": "Koillisen Liikennepalvelut",
    "59": "Tilausliikenne Nikkanen",
    "60": "Suomenlinnan Liikenne",
    "64": "Taksikuljetus Harri Vuolle",
    "89": "Metropolia",
    "90": "VR",
}
 
# Värit trendikuvaajaan per operaattori
OPERAATTORI_VARIT = {
    "Nobina Finland":       "#00a650",
    "Koiviston Auto":       "#ff6600",
    "Pohjolan Liikenne":    "#7b2d8b",
    "Tammelundin Liikenne": "#0071bc",
}
 
 
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
 
def normalisoi_aika(aika_str):
    if pd.isna(aika_str):
        return ""
    osat = str(aika_str).split(":")
    if len(osat) >= 2:
        tunnit = int(osat[0]) % 24
        return f"{tunnit:02d}:{osat[1]}"
    return str(aika_str)[:5]
 
 
# ── GTFS ────────────────────────────────────────────────────
 
def lataa_gtfs(paiva):
    print("📥 Ladataan GTFS-aikataulu HSL:ltä...")
    r = requests.get(GTFS_URL, timeout=120)
    r.raise_for_status()
 
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        trips          = pd.read_csv(z.open("trips.txt"),          dtype=str)
        calendar_dates = pd.read_csv(z.open("calendar_dates.txt"), dtype=str)
        routes         = pd.read_csv(z.open("routes.txt"),         dtype=str,
                                     usecols=["route_id","route_type",
                                              "route_short_name","agency_id"])
        agency         = pd.read_csv(z.open("agency.txt"),         dtype=str,
                                     usecols=["agency_id","agency_name"])
        stop_times     = pd.read_csv(z.open("stop_times.txt"),     dtype=str,
                                     usecols=["trip_id","stop_sequence","departure_time"])
        cal_df = None
        if "calendar.txt" in z.namelist():
            cal_df = pd.read_csv(z.open("calendar.txt"), dtype=str)
 
    routes = routes.merge(agency, on="agency_id", how="left")
    routes["route_short_name"] = routes["route_short_name"].str.strip()
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
        routes[["route_id","route_type","route_short_name","agency_name"]],
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
    return bussit[["trip_id","route_id","route_short_name","agency_name","lahtoaika"]]
 
 
# ── HFP-lataus ───────────────────────────────────────────────
 
def generoi_urlit(paiva):
    """Hakee koko päivän + seuraavan päivän yötunnit (00-04)
    jotta yövuorot joiden oday on vaihtunut löytyvät."""
    urlit = []
    # Koko analysoitava päivä
    for tunti in range(24):
        for kvarttaali in (1, 2, 3, 4):
            nimi = f"{paiva}T{tunti:02d}-{kvarttaali}_utc_VP.csv.zst"
            urlit.append(f"{BLOB_BASE_URL}/{nimi}")
    # Seuraavan päivän yötunnit 00-04 (liikennöintivuorokausi päättyy 04:30)
    seuraava = paiva + datetime.timedelta(days=1)
    for tunti in range(5):
        for kvarttaali in (1, 2, 3, 4):
            nimi = f"{seuraava}T{tunti:02d}-{kvarttaali}_utc_VP.csv.zst"
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
                         usecols=lambda c: c in ["routeId","oday","start","dir","oper"])
        if all(c in df.columns for c in ["routeId","oday","start","dir"]):
            df = df.dropna(subset=["routeId","oday","start","dir"])
            df["avain"] = (df["routeId"].astype(str) + "|" +
                           df["oday"].astype(str)    + "|" +
                           df["start"].astype(str)   + "|" +
                           df["dir"].astype(str))
            if "oper" in df.columns:
                return dict(zip(df["avain"], df["oper"].astype(str)))
            else:
                return {a: "tuntematon" for a in df["avain"].unique()}
        return {}
    except Exception:
        return None
 
 
def hae_ajetut_trip_id(paiva):
    urlit = generoi_urlit(paiva)
    print(f"🌐 Ladataan HFP-data ({len(urlit)} tiedostoa, "
          f"{RINNAKKAISET_LATAUKSET} rinnakkain)...")
    print("   Tämä kestää n. 5–15 minuuttia datan koosta riippuen.")
 
    ajetut   = {}
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
                      f"{len(ajetut):,} uniikkia vuoroa löydetty")
 
    print(f"  ✓ Valmis. Ajettuja vuoroja: {len(ajetut):,} "
          f"({virheita} tiedostoa puuttui / epäonnistui)")
    return ajetut
 
 
# ── Laskenta ────────────────────────────────────────────────
 
def laske_luotettavuus(suunnitellut_df, ajetut_dict):
    df = suunnitellut_df.copy()
    df["lahtoaika_lyhyt"] = df["lahtoaika"].apply(normalisoi_aika)
    df["route_id_norm"] = df["route_id"].astype(str).apply(lambda x: x.split(" ")[0].strip())
    df["avain"] = df["route_id_norm"] + "|" + df["lahtoaika_lyhyt"]
 
    reitti_oper = {}
    hfp_avaimet = {}

    for a, oper in ajetut_dict.items():
        osat = a.split("|")
        if len(osat) >= 3:
            route = osat[0]
            lahto = osat[2]
            # Tallennetaan avain ilman oday-tarkistusta
            lyhyt = f"{route}|{lahto}"
            hfp_avaimet[lyhyt] = oper
            reitti_oper.setdefault(route, []).append(oper)
 
    reitti_oper_yleisin = {
        r: max(set(lst), key=lst.count)
        for r, lst in reitti_oper.items()
    }
 
    df["ajettu"] = df["avain"].isin(hfp_avaimet)
    df["oper"]   = df["route_id"].map(reitti_oper_yleisin).fillna("tuntematon")
    df["oper"]   = df["oper"].map(lambda x: OPERAATTORIT.get(x, f"Operaattori {x}"))
    df = df[~df["oper"].str.startswith("Operaattori")].copy()
 
    n          = len(df)
    ajettu_n   = int(df["ajettu"].sum())
    ajamatta_n = n - ajettu_n
    pct        = round((ajettu_n / n) * 100, 2) if n else 0.0


    return {
        "suunnitellut" : n,
        "ajetut"       : ajettu_n,
        "ajamatta"     : ajamatta_n,
        "luotettavuus" : pct,
        "trips_df"     : df,
    }
 
 
def laske_operaattorierittely(trips_df):
    grp = trips_df.groupby("oper")["ajettu"]
    erittely = pd.DataFrame({
        "oper":         grp.count().index,
        "suunnitellut": grp.count().values,
        "ajettu":       grp.sum().values,
    })
    erittely["luotettavuus"] = (
        erittely["ajettu"] / erittely["suunnitellut"] * 100
    ).round(2)
    return erittely.sort_values("luotettavuus").reset_index(drop=True)
 
 
def laske_linjaerittely(trips_df):
    grp = trips_df.groupby(["route_short_name","oper"])["ajettu"]
    erittely = pd.DataFrame({
        "linja":        grp.count().index.get_level_values("route_short_name"),
        "operaattori":  grp.count().index.get_level_values("oper"),
        "suunnitellut": grp.count().values,
        "ajettu":       grp.sum().values,
    })
    erittely["luotettavuus"] = (
        erittely["ajettu"] / erittely["suunnitellut"] * 100
    ).round(2)
    return erittely.sort_values("luotettavuus").reset_index(drop=True)
 
 
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
 
    erittely = laske_operaattorierittely(t["trips_df"])
    if len(erittely) > 0:
        print()
        print("  OPERAATTOREITTAIN:")
        print(f"  {'Operaattori':<30}  {'Luotett.':>8}  {'Ajettu/Suunn.':>15}")
        print("  " + "─" * 58)
        for _, rivi in erittely.iterrows():
            print(f"  {rivi['oper']:<30}  {rivi['luotettavuus']:>7.2f} %"
                  f"  {int(rivi['ajettu']):>7,} / {int(rivi['suunnitellut']):>7,}")
    print()
 
 
def tallenna_tulokset(paiva, t):
    os.makedirs(TULOSKANSIO, exist_ok=True)
    paiva_str = paiva.strftime("%Y-%m-%d")
 
    # Yksityiskohtainen raportti
    csv_polku = os.path.join(TULOSKANSIO, f"raportti_{paiva_str}.csv")
    t["trips_df"].to_csv(csv_polku, index=False, encoding="utf-8-sig")
    print(f"💾 Raportti      → {csv_polku}")
 
    # Operaattorierittely
    erittely = laske_operaattorierittely(t["trips_df"])
    oper_polku = os.path.join(TULOSKANSIO, f"operaattorit_{paiva_str}.csv")
    erittely.to_csv(oper_polku, index=False, encoding="utf-8-sig")
    print(f"💾 Operaattorit  → {oper_polku}")
 
    # Linjaerittely
    linjaerittely = laske_linjaerittely(t["trips_df"])
    linja_polku = os.path.join(TULOSKANSIO, f"linjat_{paiva_str}.csv")
    linjaerittely.to_csv(linja_polku, index=False, encoding="utf-8-sig")
    print(f"💾 Linjat        → {linja_polku}")
 
    # Kumulatiivinen trendi – kokonais + 4 suurinta operaattoria
    trendi_polku = os.path.join(TULOSKANSIO, "trendi.csv")
 
    # Lasketaan operaattorikohtaiset prosentit
    oper_pct = {}
    for oper in TRENDI_OPERAATTORIT:
        rivi = erittely[erittely["oper"] == oper]
        if len(rivi) > 0:
            oper_pct[oper] = float(rivi["luotettavuus"].iloc[0])
        else:
            oper_pct[oper] = None
 
    uusi = pd.DataFrame([{
        "paiva"              : paiva_str,
        "suunnitellut"       : t["suunnitellut"],
        "ajetut"             : t["ajetut"],
        "ajamatta"           : t["ajamatta"],
        "luotettavuus"       : t["luotettavuus"],
        "Nobina Finland"     : oper_pct.get("Nobina Finland"),
        "Koiviston Auto"     : oper_pct.get("Koiviston Auto"),
        "Pohjolan Liikenne"  : oper_pct.get("Pohjolan Liikenne"),
        "Tammelundin Liikenne": oper_pct.get("Tammelundin Liikenne"),
    }])
 
    if os.path.exists(trendi_polku):
        trendi = pd.read_csv(trendi_polku)
        trendi = trendi[trendi["paiva"] != paiva_str]
        trendi = pd.concat([trendi, uusi], ignore_index=True)
    else:
        trendi = uusi
    trendi = trendi.sort_values("paiva").reset_index(drop=True)
    trendi.to_csv(trendi_polku, index=False, encoding="utf-8-sig")
    print(f"📈 Trendidata    → {trendi_polku}  ({len(trendi)} päivää)")
    return trendi
 
 
def piirra_kuvaajat(trendi_df):
    if len(trendi_df) < 2:
        print("ℹ️  Trendikuvaajat piirretään kun dataa on kahdelta päivältä.")
        return
 
    paivamaarat = pd.to_datetime(trendi_df["paiva"])
 
    # ── Kuvaaja 1: Kokonaisluotettavuus ─────────────────────
    fig, ax = plt.subplots(figsize=(13, 5))
    fig.patch.set_facecolor("#0f1923")
    ax.set_facecolor("#141f2e")
 
    luotettavuudet = trendi_df["luotettavuus"]
    for i in range(len(paivamaarat) - 1):
        v = luotettavuudet.iloc[i]
        c = ("#00c896" if v >= 99 else "#4fc3f7" if v >= 97
             else "#ffd54f" if v >= 95 else "#ff8a65" if v >= 90 else "#ef5350")
        ax.plot(paivamaarat.iloc[i:i+2], luotettavuudet.iloc[i:i+2],
                color=c, linewidth=2.5, solid_capstyle="round")
 
    ax.fill_between(paivamaarat, luotettavuudet,
                    luotettavuudet.min() - 1, alpha=0.12, color="#4fc3f7")


      # Värialueet
    ax.axhspan(99, 100.6, alpha=0.08, color="#00c896", zorder=0)
    ax.axhspan(max(85, luotettavuudet.min()-1.5), 97, alpha=0.08, color="#ef5350", zorder=0)
  
    for raja, teksti, vari in [(99,"99 %","#00c896"),
                                (97,"97 %","#4fc3f7"),
                                (95,"95 %","#ffd54f")]:
        ax.axhline(raja, linestyle="--", linewidth=0.8, color=vari, alpha=0.45)
        ax.text(paivamaarat.iloc[0], raja + 0.08, teksti,
                color=vari, fontsize=7.5, alpha=0.7, va="bottom")
 
    ax.scatter(paivamaarat, luotettavuudet, color="white", s=35, zorder=5, alpha=0.85)
 
    viim_y = luotettavuudet.iloc[-1]
    ax.annotate(f"{viim_y:.1f} %",
                xy=(paivamaarat.iloc[-1], viim_y),
                xytext=(12, 8), textcoords="offset points",
                color="white", fontsize=11, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.35",
                          facecolor="#0f3460", edgecolor="#4fc3f7", alpha=0.9),
                arrowprops=dict(arrowstyle="->", color="#4fc3f7", lw=1.2))
 
    ymin = max(85, luotettavuudet.min() - 1.5)
    ax.set_ylim(ymin, 100.6)
    ax.set_xlabel("Päivä", color="#8899bb", fontsize=10)
    ax.set_ylabel("Luotettavuus (%)", color="#8899bb", fontsize=10)
    ax.set_title("HSL Bussiliikenne – Kokonaisluotettavuus",
                 color="white", fontsize=13, fontweight="bold", pad=14)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m."))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.xticks(rotation=40, color="#8899bb", fontsize=8)
    plt.yticks(color="#8899bb")
    for sp in ax.spines.values():
        sp.set_edgecolor("#2a3a5a")
    ax.grid(axis="y", linestyle=":", alpha=0.25, color="#8899bb")
    plt.tight_layout()
 
    polku1 = os.path.join(TULOSKANSIO, "luotettavuus_trendi.png")
    plt.savefig(polku1, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"📊 Kokonaistrendi → {polku1}")
 
    # ── Kuvaaja 2: Operaattorikohtainen trendi ──────────────
    fig, ax = plt.subplots(figsize=(13, 6))
    fig.patch.set_facecolor("#0f1923")
    ax.set_facecolor("#141f2e")
 
    kaikki_arvot = []
    for oper in TRENDI_OPERAATTORIT:
        if oper not in trendi_df.columns:
            continue
        arvot = pd.to_numeric(trendi_df[oper], errors="coerce")
        if arvot.isna().all():
            continue
        vari = OPERAATTORI_VARIT.get(oper, "#ffffff")
        ax.plot(paivamaarat, arvot, color=vari, linewidth=2.2,
                solid_capstyle="round", label=oper)
        ax.scatter(paivamaarat[arvot.notna()], arvot[arvot.notna()],
                   color=vari, s=30, zorder=5, alpha=0.85)
        # Viimeisin arvo labelina
        viim_idx = arvot.last_valid_index()
        if viim_idx is not None:
            viim_y = arvot[viim_idx]
            viim_x = paivamaarat[viim_idx]
            ax.annotate(f"{viim_y:.1f} %",
                        xy=(viim_x, viim_y),
                        xytext=(8, 0), textcoords="offset points",
                        color=vari, fontsize=8, fontweight="bold", va="center")
        kaikki_arvot.extend(arvot.dropna().tolist())
 
    if kaikki_arvot:
        ymin = max(85, min(kaikki_arvot) - 2)
        ax.set_ylim(ymin, 100.6)

    # Värialueet: vihreä = hyvä (>=99), punainen = heikko (<97)
    ax.axhspan(99, 100.6, alpha=0.08, color="#00c896", zorder=0)
    ax.axhspan(ax.get_ylim()[0], 97, alpha=0.08, color="#ef5350", zorder=0)

    for raja, teksti, vari in [(99,"99 %","#00c896"),
                                (97,"97 %","#ef5350")]:
        ax.axhline(raja, linestyle="--", linewidth=0.8, color=vari, alpha=0.4)
        ax.text(paivamaarat.iloc[0], raja + 0.08, teksti,
                color=vari, fontsize=7.5, alpha=0.7, va="bottom")
 
    ax.set_xlabel("Päivä", color="#8899bb", fontsize=10)
    ax.set_ylabel("Luotettavuus (%)", color="#8899bb", fontsize=10)
    ax.set_title("HSL Bussiliikenne – Operaattorikohtainen luotettavuus",
                 color="white", fontsize=13, fontweight="bold", pad=14)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m."))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.xticks(rotation=40, color="#8899bb", fontsize=8)
    plt.yticks(color="#8899bb")
    for sp in ax.spines.values():
        sp.set_edgecolor("#2a3a5a")
    ax.grid(axis="y", linestyle=":", alpha=0.25, color="#8899bb")
    legend = ax.legend(loc="lower left", facecolor="#1a2a3a",
                       edgecolor="#2a3a5a", labelcolor="white", fontsize=9)
    plt.tight_layout()
 
    polku2 = os.path.join(TULOSKANSIO, "luotettavuus_operaattorit.png")
    plt.savefig(polku2, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"📊 Operaattoritrendi → {polku2}")
 
 
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
    piirra_kuvaajat(trendi)
 
    print()
    print(f"✅  Valmis! Tulokset: {os.path.abspath(TULOSKANSIO)}")
    print()
 
 
if __name__ == "__main__":
    main()
