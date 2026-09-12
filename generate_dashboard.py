"""
HSL Dashboard Generator
========================
Lukee tulokset/-kansion datan ja generoi docs/index.html -tiedoston.
Ajetaan GitHub Actionsissa joka päivä analyysin jälkeen.
"""

import os
import json
import datetime
import requests
import pandas as pd
from pathlib import Path

TULOSKANSIO = "tulokset"
DOCS_KANSIO = "docs"

TRENDI_OPERAATTORIT = [
    "Nobina Finland",
    "Koiviston Auto",
    "Pohjolan Liikenne",
    "Tammelundin Liikenne",
]

OPERAATTORI_VARIT = {
    "Nobina Finland":       "#00a650",
    "Koiviston Auto":       "#ff6600",
    "Pohjolan Liikenne":    "#7b2d8b",
    "Tammelundin Liikenne": "#0071bc",
}

HALYTYSTARAJA = 85.0  # päivitetään kun 90pv data analysoitu


def lataa_trendi():
    polku = os.path.join(TULOSKANSIO, "trendi.csv")
    if not os.path.exists(polku):
        return pd.DataFrame()
    df = pd.read_csv(polku)
    df["paiva"] = pd.to_datetime(df["paiva"])
    df = df.drop_duplicates(subset=["paiva"], keep="last")
    return df.sort_values("paiva").reset_index(drop=True)

def laske_kellonaika():
    """Lataa kellonaika.csv ja laskee keskimääräisen luotettavuuden per tunti."""
    polku = os.path.join(TULOSKANSIO, "kellonaika.csv")
    if not os.path.exists(polku):
        return {}
    df = pd.read_csv(polku)
    keskiarvot = df.groupby("tunti")["luotettavuus"].mean()
    return {f"{int(t):02d}": round(keskiarvot.get(t, 0), 1) for t in range(24)}

def lataa_linjadata(paivamaara):
    """Lataa linjakohtaisen datan annetulle päivälle."""
    polku = os.path.join(TULOSKANSIO, f"linjat_{paivamaara}.csv")
    if not os.path.exists(polku):
        return pd.DataFrame()
    return pd.read_csv(polku)


def laske_1kk_linjat(trendi_df):
    """Laskee viimeisen kuukauden heikoiten suoriutuneet linjat."""
    if trendi_df.empty:
        return pd.DataFrame()
    # Käytetään vain dataa 24.5.2026 eteenpäin (korjattu skripti)
    korjaus_pvm = pd.Timestamp("2026-05-24")
    kuukausi_sitten = max(
        trendi_df["paiva"].max() - pd.Timedelta(days=30),
        korjaus_pvm
    )
    viime_kk = trendi_df[trendi_df["paiva"] >= kuukausi_sitten]

    kaikki_linjat = []
    for _, rivi in viime_kk.iterrows():
        paiva_str = rivi["paiva"].strftime("%Y-%m-%d")
        linjadata = lataa_linjadata(paiva_str)
        if not linjadata.empty:
            kaikki_linjat.append(linjadata)

    if not kaikki_linjat:
        return pd.DataFrame()

    yhdistetty = pd.concat(kaikki_linjat, ignore_index=True)
    yhteenveto = yhdistetty.groupby(["linja","operaattori"]).agg(
        suunnitellut=("suunnitellut","sum"),
        ajettu=("ajettu","sum")
    ).reset_index()
    yhteenveto["luotettavuus"] = (
        yhteenveto["ajettu"] / yhteenveto["suunnitellut"] * 100
    ).round(1)
    yhteenveto = yhteenveto[yhteenveto["suunnitellut"] >= 10]
    return yhteenveto.sort_values("luotettavuus").head(10)

def laske_halytyslinjat(trendi_df, raja):
    """Linjat jotka ovat alittaneet hälytysrajan viimeisen 5 päivän aikana."""
    if trendi_df.empty:
        return []
    korjaus_pvm = pd.Timestamp("2026-05-24")
    viimeiset = trendi_df[trendi_df["paiva"] >= korjaus_pvm].tail(5)
    halytyslinjat = []
    for _, rivi in viimeiset.iterrows():
        paiva_str = rivi["paiva"].strftime("%Y-%m-%d")
        linjadata = lataa_linjadata(paiva_str)
        if linjadata.empty:
            continue
        ongelmat = linjadata[
            (linjadata["luotettavuus"] < raja) &
            (linjadata["suunnitellut"] >= 5)
        ]
        for _, linja in ongelmat.iterrows():
            halytyslinjat.append({
                "paiva": paiva_str,
                "linja": linja["linja"],
                "operaattori": linja["operaattori"],
                "luotettavuus": linja["luotettavuus"],
                "ajettu": int(linja["ajettu"]),
                "suunnitellut": int(linja["suunnitellut"]),
            })
    return sorted(halytyslinjat, key=lambda x: x["paiva"], reverse=True)
    
def hae_reittinimet(api_avain):
    """Hakee kaikkien linjojen longName Digitransitista."""
    if not api_avain:
        return {}
    query = """
    {
      routes(feeds: ["HSL"]) {
        gtfsId
        shortName
        longName
        mode
      }
    }
    """
    try:
        r = requests.post(
            "https://api.digitransit.fi/routing/v2/hsl/gtfs/v1",
            json={"query": query},
            headers={"digitransit-subscription-key": api_avain},
            timeout=30
        )
        routes = r.json().get("data", {}).get("routes", [])
        return {
            route["shortName"]: route.get("longName", "")
            for route in routes
            if route.get("shortName") and route.get("longName")
        }
    except Exception as e:
        print(f"  ⚠️ Reittinimien haku epäonnistui: {e}")
        return {}
    """Linjat jotka ovat alittaneet hälytysrajan viimeisen 5 päivän aikana."""
    if trendi_df.empty:
        return []
    korjaus_pvm = pd.Timestamp("2026-05-24")
    viimeiset = trendi_df[trendi_df["paiva"] >= korjaus_pvm].tail(5)
    halytyslinjat = []
    for _, rivi in viimeiset.iterrows():
        paiva_str = rivi["paiva"].strftime("%Y-%m-%d")
        linjadata = lataa_linjadata(paiva_str)
        if linjadata.empty:
            continue
        ongelmat = linjadata[
            (linjadata["luotettavuus"] < raja) &
            (linjadata["suunnitellut"] >= 5)
        ]
        for _, linja in ongelmat.iterrows():
            halytyslinjat.append({
                "paiva": paiva_str,
                "linja": linja["linja"],
                "operaattori": linja["operaattori"],
                "luotettavuus": linja["luotettavuus"],
                "ajettu": int(linja["ajettu"]),
                "suunnitellut": int(linja["suunnitellut"]),
            })
    return sorted(halytyslinjat, key=lambda x: x["paiva"], reverse=True)

def laske_viikonpaivat(trendi_df):
    """Laskee keskimääräisen luotettavuuden viikonpäivittäin, kokonaisuutena ja per operaattori, viimeiset 12kk."""
    if trendi_df.empty:
        return {}, {}
    raja = trendi_df["paiva"].max() - pd.Timedelta(days=365)
    data = trendi_df[trendi_df["paiva"] >= raja].copy()
    data["viikonpaiva"] = data["paiva"].dt.dayofweek  # 0=ma, 6=su
    nimet = ["Ma","Ti","Ke","To","Pe","La","Su"]

    keskiarvot = data.groupby("viikonpaiva")["luotettavuus"].mean()
    kokonais = {nimet[i]: round(keskiarvot.get(i, 0), 1) for i in range(7)}

    operaattorit = ["Nobina Finland","Koiviston Auto","Pohjolan Liikenne","Tammelundin Liikenne"]
    oper_data = {}
    for oper in operaattorit:
        if oper in data.columns:
            ka = data.groupby("viikonpaiva")[oper].mean()
            oper_data[oper] = {nimet[i]: round(ka.get(i, 0), 1) for i in range(7)}

    return kokonais, oper_data

def laske_vuodenaika(trendi_df):
    """Laskee kausikohtaisen luotettavuuden per operaattori. Kaudet 2026 alkaen."""
    if trendi_df.empty:
        return {}

    KAUDET = [
        ("Talvi",  "2026-01-01", "2026-02-28"),
        ("Kevät",  "2026-03-01", "2026-06-14"),
        ("Kesä",   "2026-06-15", "2026-08-09"),
        ("Syksy",  "2026-08-10", "2026-11-30"),
    ]
    OPERAATTORIT = ["Nobina Finland", "Koiviston Auto", "Pohjolan Liikenne", "Tammelundin Liikenne"]

    tulos = {}
    tanaan = trendi_df["paiva"].max()

    for kausi_nimi, alku, loppu in KAUDET:
        alku_pvm = pd.Timestamp(alku)
        loppu_pvm = min(pd.Timestamp(loppu), tanaan)  # ei mennä tulevaisuuteen

        if alku_pvm > tanaan:
            continue  # kausi ei ole vielä alkanut

        data = trendi_df[
            (trendi_df["paiva"] >= alku_pvm) &
            (trendi_df["paiva"] <= loppu_pvm)
        ].copy()

        if len(data) == 0:
            continue

        kausi_data = {
            "paivat": len(data),
            "alku": alku_pvm.strftime("%-d.%-m."),
            "loppu": loppu_pvm.strftime("%-d.%-m.%Y"),
            "koko_hsl": round(data["luotettavuus"].mean(), 2),
            "operaattorit": {}
        }

        for oper in OPERAATTORIT:
            if oper in data.columns:
                ka = data[oper].dropna()
                if len(ka) > 0:
                    kausi_data["operaattorit"][oper] = round(ka.mean(), 2)

        tulos[kausi_nimi] = kausi_data

    return tulos

def laske_saavaikutus(trendi_df):
    """Laskee säävaikutusanalyysin (Kaisaniemi 1.1.–14.3.2026)."""
    if trendi_df.empty:
        return {}

    SAA = {
        "2026-01-01":{"keski":-8.0,"min":-13.4,"sade":0.8},
        "2026-01-02":{"keski":-3.9,"min":-5.8,"sade":3.2},
        "2026-01-03":{"keski":-7.1,"min":-8.7,"sade":0.0},
        "2026-01-04":{"keski":-12.0,"min":-13.3,"sade":1.9},
        "2026-01-05":{"keski":-15.4,"min":-18.7,"sade":0.0},
        "2026-01-06":{"keski":-7.2,"min":-16.1,"sade":6.1},
        "2026-01-07":{"keski":-6.5,"min":-10.2,"sade":0.7},
        "2026-01-08":{"keski":-13.1,"min":-15.9,"sade":0.0},
        "2026-01-09":{"keski":-12.8,"min":-16.9,"sade":0.0},
        "2026-01-10":{"keski":-9.9,"min":-13.5,"sade":1.2},
        "2026-01-11":{"keski":-5.5,"min":-10.4,"sade":0.0},
        "2026-01-12":{"keski":-2.7,"min":-6.2,"sade":0.0},
        "2026-01-13":{"keski":-3.1,"min":-5.5,"sade":0.3},
        "2026-01-14":{"keski":-6.6,"min":-10.0,"sade":0.0},
        "2026-01-15":{"keski":-16.8,"min":-20.2,"sade":0.0},
        "2026-01-16":{"keski":-14.3,"min":-18.5,"sade":0.1},
        "2026-01-17":{"keski":-10.8,"min":-15.1,"sade":0.0},
        "2026-01-18":{"keski":-11.7,"min":-16.2,"sade":0.0},
        "2026-01-19":{"keski":-14.9,"min":-17.4,"sade":0.0},
        "2026-01-20":{"keski":-7.1,"min":-16.0,"sade":0.3},
        "2026-01-21":{"keski":-4.3,"min":-8.3,"sade":0.0},
        "2026-01-22":{"keski":-6.5,"min":-9.1,"sade":0.0},
        "2026-01-23":{"keski":-11.2,"min":-15.5,"sade":0.0},
        "2026-01-24":{"keski":-10.5,"min":-14.2,"sade":0.0},
        "2026-01-25":{"keski":-5.1,"min":-11.0,"sade":3.4},
        "2026-01-26":{"keski":-7.8,"min":-11.0,"sade":0.5},
        "2026-01-27":{"keski":-12.1,"min":-15.4,"sade":0.0},
        "2026-01-28":{"keski":-11.0,"min":-14.9,"sade":0.0},
        "2026-01-29":{"keski":-5.8,"min":-12.6,"sade":0.0},
        "2026-01-30":{"keski":-4.8,"min":-8.3,"sade":4.1},
        "2026-01-31":{"keski":-7.3,"min":-10.6,"sade":0.7},
        "2026-02-01":{"keski":-9.5,"min":-13.1,"sade":0.0},
        "2026-02-02":{"keski":-11.1,"min":-14.8,"sade":0.0},
        "2026-02-03":{"keski":-7.6,"min":-12.4,"sade":0.0},
        "2026-02-04":{"keski":-3.6,"min":-8.0,"sade":0.0},
        "2026-02-05":{"keski":-2.4,"min":-5.1,"sade":2.5},
        "2026-02-06":{"keski":-5.8,"min":-8.9,"sade":0.3},
        "2026-02-07":{"keski":-10.1,"min":-13.9,"sade":0.0},
        "2026-02-08":{"keski":-8.3,"min":-12.5,"sade":0.0},
        "2026-02-09":{"keski":-6.2,"min":-10.0,"sade":0.5},
        "2026-02-10":{"keski":-4.1,"min":-7.8,"sade":3.1},
        "2026-02-11":{"keski":-6.9,"min":-10.3,"sade":0.2},
        "2026-02-12":{"keski":-10.7,"min":-14.1,"sade":0.0},
        "2026-02-13":{"keski":-13.2,"min":-16.5,"sade":0.0},
        "2026-02-14":{"keski":-15.1,"min":-18.3,"sade":0.0},
        "2026-02-15":{"keski":-12.4,"min":-16.8,"sade":0.0},
        "2026-02-16":{"keski":-8.1,"min":-13.5,"sade":0.4},
        "2026-02-17":{"keski":-5.3,"min":-9.2,"sade":0.8},
        "2026-02-18":{"keski":-3.8,"min":-6.4,"sade":3.8},
        "2026-02-19":{"keski":-7.2,"min":-10.9,"sade":0.2},
        "2026-02-20":{"keski":-9.4,"min":-13.1,"sade":0.0},
        "2026-02-21":{"keski":-6.1,"min":-10.8,"sade":0.0},
        "2026-02-22":{"keski":-4.2,"min":-7.5,"sade":1.1},
        "2026-02-23":{"keski":-2.8,"min":-5.3,"sade":0.6},
        "2026-02-24":{"keski":-1.5,"min":-4.1,"sade":0.4},
        "2026-02-25":{"keski":-0.8,"min":-3.2,"sade":0.0},
        "2026-02-26":{"keski":0.2,"min":-2.1,"sade":1.2},
        "2026-02-27":{"keski":-1.1,"min":-3.8,"sade":0.3},
        "2026-02-28":{"keski":-3.5,"min":-6.2,"sade":0.0},
        "2026-03-01":{"keski":-5.2,"min":-8.4,"sade":0.0},
        "2026-03-02":{"keski":-2.1,"min":-5.9,"sade":0.2},
        "2026-03-03":{"keski":0.8,"min":-2.3,"sade":3.5},
        "2026-03-04":{"keski":-1.4,"min":-4.8,"sade":0.5},
        "2026-03-05":{"keski":-3.8,"min":-7.2,"sade":0.0},
        "2026-03-06":{"keski":-6.1,"min":-9.5,"sade":0.0},
        "2026-03-07":{"keski":-4.3,"min":-8.1,"sade":0.3},
        "2026-03-08":{"keski":-2.2,"min":-5.6,"sade":1.8},
        "2026-03-09":{"keski":0.4,"min":-2.8,"sade":0.7},
        "2026-03-10":{"keski":1.2,"min":-1.5,"sade":0.0},
        "2026-03-11":{"keski":-0.8,"min":-3.4,"sade":0.2},
        "2026-03-12":{"keski":-2.5,"min":-5.8,"sade":0.0},
        "2026-03-13":{"keski":-4.1,"min":-7.3,"sade":0.0},
        "2026-03-14":{"keski":-1.8,"min":-4.9,"sade":3.2},
    }

    OPERAATTORIT = ["Nobina Finland","Koiviston Auto","Pohjolan Liikenne","Tammelundin Liikenne"]
    LUOKAT = ["Normaali","Lumisade","Kylmä","Erittäin kylmä"]

    def luokittele(keski, min_t, sade):
        if min_t <= -15:
            return "Erittäin kylmä"
        elif min_t <= -10:
            return "Kylmä"
        elif sade >= 3 and keski <= 2:
            return "Lumisade"
        else:
            return "Normaali"

    paiva_data = []
    for _, row in trendi_df.iterrows():
        p = row["paiva"].strftime("%Y-%m-%d")
        if p not in SAA:
            continue
        saa = SAA[p]
        luokka = luokittele(saa["keski"], saa["min"], saa["sade"])
        entry = {
            "paiva": p,
            "luotettavuus": row["luotettavuus"],
            "luokka": luokka,
            "min_lampotila": saa["min"],
            "sade_mm": saa["sade"],
        }
        for op in OPERAATTORIT:
            if op in trendi_df.columns and not pd.isna(row.get(op)):
                entry[op] = row[op]
        paiva_data.append(entry)

    if not paiva_data:
        return {}

    pylvas = {}
    for luokka in LUOKAT:
        ryh = [d for d in paiva_data if d["luokka"] == luokka]
        if ryh:
            pylvas[luokka] = {
                "n": len(ryh),
                "ka": round(sum(d["luotettavuus"] for d in ryh) / len(ryh), 2),
                "min": round(min(d["luotettavuus"] for d in ryh), 2),
            }

    oper = {}
    for op in OPERAATTORIT:
        oper[op] = {}
        for luokka in ["Normaali","Erittäin kylmä"]:
            ryh = [d[op] for d in paiva_data
                   if d["luokka"] == luokka and op in d and d[op] is not None]
            if ryh:
                oper[op][luokka] = round(sum(ryh) / len(ryh), 2)

    OPER_VARIT_MAP = {
        "Nobina Finland": "#00a650",
        "Koiviston Auto": "#ff6600",
        "Pohjolan Liikenne": "#7b2d8b",
        "Tammelundin Liikenne": "#0071bc",
    }
    scatter = []
    for d in paiva_data:
        for op in OPERAATTORIT:
            if op in d and d[op] is not None:
                scatter.append({
                    "x": d["min_lampotila"],
                    "y": d[op],
                    "luokka": d["luokka"],
                    "paiva": d["paiva"],
                    "operaattori": op,
                })

    return {
        "pylvas": pylvas,
        "oper": oper,
        "scatter": scatter,
        "paivia": len(paiva_data),
    }

def laske_kuukausihistoria(trendi_df):
    """Laskee operaattorikohtaisen kuukausihistorian kaikille operaattoreille."""
    if trendi_df.empty:
        return {}, []

    # Kerätään kaikki operaattorit operaattorit_-tiedostoista
    kaikki_operaattorit = set(TRENDI_OPERAATTORIT)
    kuukausi_data = {}  # {operaattori: {kuukausi: {ajettu, suunnitellut}}}

    for _, rivi in trendi_df.iterrows():
        paiva_str = rivi["paiva"].strftime("%Y-%m-%d")
        kuukausi = rivi["paiva"].strftime("%Y-%m")
        polku = os.path.join(TULOSKANSIO, f"operaattorit_{paiva_str}.csv")

        if os.path.exists(polku):
            oper_df = pd.read_csv(polku)
            for _, o in oper_df.iterrows():
                oper = o["oper"]
                kaikki_operaattorit.add(oper)
                if oper not in kuukausi_data:
                    kuukausi_data[oper] = {}
                if kuukausi not in kuukausi_data[oper]:
                    kuukausi_data[oper][kuukausi] = {"ajettu": 0, "suunnitellut": 0}
                kuukausi_data[oper][kuukausi]["ajettu"]       += int(o["ajettu"])
                kuukausi_data[oper][kuukausi]["suunnitellut"] += int(o["suunnitellut"])
        else:
            # Vanha data – käytetään trendi.csv:n neljää suurinta
            for oper in TRENDI_OPERAATTORIT:
                if oper in rivi and pd.notna(rivi[oper]):
                    if oper not in kuukausi_data:
                        kuukausi_data[oper] = {}
                    if kuukausi not in kuukausi_data[oper]:
                        kuukausi_data[oper][kuukausi] = {"ajettu": 0, "suunnitellut": 0}
                    # Arvioidaan ajetut trendi.csv:n prosentista
                    pct = rivi[oper] / 100
                    suunn = int(rivi["suunnitellut"] / len(TRENDI_OPERAATTORIT))
                    kuukausi_data[oper][kuukausi]["ajettu"]       += int(suunn * pct)
                    kuukausi_data[oper][kuukausi]["suunnitellut"] += suunn

    # Lasketaan prosentit
    historia = {}
    for oper, kk_dict in kuukausi_data.items():
        historia[oper] = {}
        for kk, luvut in kk_dict.items():
            if luvut["suunnitellut"] > 0:
                historia[oper][kk] = round(
                    luvut["ajettu"] / luvut["suunnitellut"] * 100, 2
                )

    # Järjestetään operaattorit: suurimmat ensin, sitten aakkosjärjestyksessä
    jarjestetty = TRENDI_OPERAATTORIT + sorted(
        [o for o in kaikki_operaattorit
         if o not in TRENDI_OPERAATTORIT
         and not o.startswith("Operaattori")]
    )
    return historia, jarjestetty


def generoi_html(trendi_df, reittinimet={}, viikonpaivat={}, kellonajat={}, viikonpaivat_oper={}, vuodenaika={}, saavaikutus={}):
    if trendi_df.empty:
        return "<p>Ei dataa saatavilla.</p>"

    viimeisin = trendi_df.iloc[-1]
    viimeisin_paiva = viimeisin["paiva"].strftime("%d.%m.%Y")
    viimeisin_pct = viimeisin["luotettavuus"]

    # Kokonaistrendi JSON
    trendi_json = json.dumps({
        "paivamaarat": trendi_df["paiva"].dt.strftime("%Y-%m-%d").tolist(),
        "luotettavuus": trendi_df["luotettavuus"].tolist(),
    })

    viikonpaiva_labels = json.dumps(list(viikonpaivat.keys()))
    viikonpaiva_arvot  = json.dumps(list(viikonpaivat.values()))
    vuodenaika_json = json.dumps(vuodenaika, ensure_ascii=False)
    saavaikutus_json = json.dumps(saavaikutus, ensure_ascii=False)
    
    kellonaika_labels  = json.dumps(list(kellonajat.keys()))
    kellonaika_arvot   = json.dumps(list(kellonajat.values()))

    alkupaiva_data = trendi_df["paiva"].min().strftime("%-d.%-m.%Y") if not trendi_df.empty else ""
    alkupaiva_kello = "19.6.2026"

    viikonpaiva_oper_json = json.dumps(viikonpaivat_oper)
    
    # Operaattoritrendi JSON
    oper_data = {}
    for oper in TRENDI_OPERAATTORIT:
        if oper in trendi_df.columns:
            arvot = trendi_df[oper].tolist()
            oper_data[oper] = arvot
    oper_json = json.dumps({
        "paivamaarat": trendi_df["paiva"].dt.strftime("%Y-%m-%d").tolist(),
        "operaattorit": oper_data,
        "varit": OPERAATTORI_VARIT,
    })

    # 1kk heikoiten suoriutuneet linjat
    heikoimmat = laske_1kk_linjat(trendi_df)
    heikoimmat_html = ""
    if not heikoimmat.empty:
        for _, rivi in heikoimmat.iterrows():
            vari = "#dc2626" if rivi["luotettavuus"] < 90 else "#d97706" if rivi["luotettavuus"] < 95 else "#2563eb"
            reitti = reittinimet.get(str(rivi['linja']), "")
            heikoimmat_html += f"""
            <tr>
                <td class="linja-nimi">{rivi['linja']}<span style="font-size:11px;color:#6b8caa;font-weight:400;margin-left:6px;">{reitti}</span></td>
                <td>{rivi['operaattori']}</td>
                <td style="color:{vari};font-weight:600">{rivi['luotettavuus']:.1f} %</td>
                <td class="muted">{int(rivi['ajettu']):,} / {int(rivi['suunnitellut']):,}</td>
            </tr>"""
    else:
        heikoimmat_html = '<tr><td colspan="4" class="muted">Linjakohtainen data kertyy päivittäin</td></tr>'

    # Hälytykset
    halytyslinjat = laske_halytyslinjat(trendi_df, HALYTYSTARAJA)
    halytykset_html = ""
    if halytyslinjat:
        for h in halytyslinjat[:20]:
                reitti = reittinimet.get(str(h['linja']), "")
                halytykset_html += f"""
            <tr>
                <td class="muted">{h['paiva']}</td>
                <td class="linja-nimi">{h['linja']}<span style="font-size:11px;color:#6b8caa;font-weight:400;margin-left:6px;">{reitti}</span></td>
                <td>{h['operaattori']}</td>
                <td style="color:#dc2626;font-weight:600">{h['luotettavuus']:.1f} %</td>
                <td class="muted">{h['ajettu']} / {h['suunnitellut']}</td>
            </tr>"""
    else:
        halytykset_html = f'<tr><td colspan="5" class="muted">Ei hälytyksiä viimeisen 5 päivän aikana (raja: {HALYTYSTARAJA} %)</td></tr>'

    # Kuukausihistoria
    kuukausihistoria, kaikki_operaattorit = laske_kuukausihistoria(trendi_df)
    kuukaudet = sorted(set(
        kk for oper_data in kuukausihistoria.values()
        for kk in oper_data.keys()
    ))
    kk_header = "".join(f"<th>{kk}</th>" for kk in kuukaudet)
    kk_rivit = ""
    for oper in kaikki_operaattorit:
        vari = OPERAATTORI_VARIT.get(oper, "#666")
        kk_rivit += f'<tr><td style="color:{vari};font-weight:600">{oper}</td>'
        for kk in kuukaudet:
            arvo = kuukausihistoria.get(oper, {}).get(kk)
            if arvo is not None:
                tekstivari = "#dc2626" if arvo < 98 else "#16a34a" if arvo >= 99 else "#d97706"
                kk_rivit += f'<td style="color:{tekstivari};font-weight:500">{arvo:.1f} %</td>'
            else:
                kk_rivit += '<td class="muted">–</td>'
        kk_rivit += "</tr>"

    # Eilisen operaattoridata
    eilinen_oper_html = ""
    for oper in TRENDI_OPERAATTORIT:
        if oper in trendi_df.columns:
            arvo = viimeisin.get(oper)
            if pd.notna(arvo):
                vari_oper = OPERAATTORI_VARIT.get(oper, "#666")
                tekstivari = "#dc2626" if arvo < 98 else "#16a34a" if arvo >= 99 else "#d97706"
                eilinen_oper_html += f"""
                <div class="oper-kortti">
                    <div class="oper-nimi" style="color:{vari_oper}">{oper}</div>
                    <div class="oper-pct" style="color:{tekstivari}">{arvo:.1f} %</div>
                </div>"""

    paivitys_aika = (datetime.datetime.utcnow() + 
                     datetime.timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")
    pct_vari = "#dc2626" if viimeisin_pct < 98 else "#16a34a" if viimeisin_pct >= 99 else "#d97706"

    html = f"""<!DOCTYPE html>
<html lang="fi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HSL Bussiliikenne – Luotettavuusseuranta</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        :root {{
            --hsl-blue:    #0071bc;
            --hsl-light:   #e8f4fd;
            --hsl-dark:    #1e3a5f;
            --hsl-mid:     #2d6a9f;
            --green:       #16a34a;
            --yellow:      #d97706;
            --red:         #dc2626;
            --bg:          #f0f6fc;
            --card:        #ffffff;
            --border:      #c8dff0;
            --text:        #1e3a5f;
            --muted:       #6b8caa;
            --radius:      12px;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Figtree', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
        }}
        header {{
            background: var(--hsl-dark);
            color: white;
            padding: 0;
            border-bottom: 4px solid var(--hsl-blue);
        }}
        .header-inner {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 24px 32px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .header-title {{
            display: flex;
            align-items: center;
            gap: 16px;
        }}
        .hsl-logo {{
            background: var(--hsl-blue);
            color: white;
            font-weight: 700;
            font-size: 18px;
            padding: 8px 14px;
            border-radius: 8px;
            letter-spacing: 1px;
        }}
        h1 {{
            font-size: 22px;
            font-weight: 700;
            letter-spacing: -0.3px;
        }}
        .header-sub {{
            font-size: 13px;
            opacity: 0.7;
            margin-top: 2px;
        }}
        .paivitys {{
            font-size: 12px;
            opacity: 0.6;
            font-family: 'DM Mono', monospace;
        }}
        main {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 32px;
        }}
        .hero {{
            background: var(--card);
            border-radius: var(--radius);
            border: 1px solid var(--border);
            padding: 32px;
            margin-bottom: 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 24px;
            box-shadow: 0 2px 8px rgba(0,113,188,0.08);
        }}
        .hero-left h2 {{
            font-size: 15px;
            font-weight: 500;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
        }}
        .hero-pct {{
            font-size: 72px;
            font-weight: 700;
            line-height: 1;
            color: {pct_vari};
            font-family: 'DM Mono', monospace;
        }}
        .hero-paiva {{
            font-size: 14px;
            color: var(--muted);
            margin-top: 8px;
        }}
        .oper-grid {{
            display: flex;
            gap: 16px;
            flex-wrap: wrap;
        }}
        .oper-kortti {{
            background: var(--bg);
            border-radius: 10px;
            padding: 16px 20px;
            min-width: 160px;
            border: 1px solid var(--border);
        }}
        .oper-nimi {{
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 6px;
        }}
        .oper-pct {{
            font-size: 28px;
            font-weight: 700;
            font-family: 'DM Mono', monospace;
        }}
        .grid-2 {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
            margin-bottom: 24px;
        }}
        @media (max-width: 768px) {{
            .grid-2 {{ grid-template-columns: 1fr; }}
            main {{ padding: 16px; }}
            .hero-pct {{ font-size: 56px; }}
        }}
        .kortti {{
            background: var(--card);
            border-radius: var(--radius);
            border: 1px solid var(--border);
            padding: 24px;
            box-shadow: 0 2px 8px rgba(0,113,188,0.06);
        }}
        .kortti-otsikko {{
            font-size: 13px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--muted);
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .kortti-otsikko span {{
            background: var(--hsl-light);
            color: var(--hsl-blue);
            border-radius: 6px;
            padding: 2px 8px;
            font-size: 11px;
        }}
        .full-width {{ grid-column: 1 / -1; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }}
        th {{
            text-align: left;
            padding: 8px 12px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--muted);
            border-bottom: 2px solid var(--border);
        }}
        td {{
            padding: 10px 12px;
            border-bottom: 1px solid var(--bg);
            vertical-align: middle;
        }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover td {{ background: var(--bg); }}
        .linja-nimi {{
            font-family: 'DM Mono', monospace;
            font-weight: 500;
            font-size: 15px;
            color: var(--hsl-dark);
        }}
        .muted {{ color: var(--muted); }}
        .halytys-badge {{
            background: #fef2f2;
            border: 1px solid #fecaca;
            color: #dc2626;
            border-radius: 6px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 600;
        }}
        .metodiikka {{
            background: var(--hsl-light);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px 24px;
            margin-top: 24px;
            font-size: 13px;
            color: var(--muted);
            line-height: 1.6;
        }}
        .metodiikka strong {{ color: var(--text); }}
        canvas {{ max-height: 280px; }}
    </style>
</head>
<body>
<header>
    <div class="header-inner">
        <div class="header-title">
            <img src="images/HSL.svg" alt="HSL" style="height:40px;">
            <img src="images/Bussi.svg" alt="Bussi" style="height:40px;">
            <div>
                <h1>Bussiliikenne – Luotettavuusseuranta</h1>
                <div class="header-sub">Päivittäinen suoritusdatan seuranta</div>
            </div>
        </div>
        <div class="paivitys">Päivitetty {paivitys_aika}</div>
    </div>
</header>

<main>
    <!-- Hero: eilinen tilanne -->
    <!-- Navigaatio linjastatussivuille -->
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:28px;">
        <a href="metro.html" style="display:flex;align-items:center;gap:8px;background:#ff6319;color:white;text-decoration:none;padding:10px 20px;border-radius:10px;font-weight:600;font-size:14px;">
            <img src="images/Metro.svg" alt="Metro" style="width:24px;height:24px;"> Metro
        </a>
        <a href="raitiovaunut.html" style="display:flex;align-items:center;gap:8px;background:#00985f;color:white;text-decoration:none;padding:10px 20px;border-radius:10px;font-weight:600;font-size:14px;">
            <img src="images/Ratikka.svg" alt="Ratikka" style="width:24px;height:24px;"> Raitiovaunut
        </a>
        <a href="junat.html" style="display:flex;align-items:center;gap:8px;background:#8c4799;color:white;text-decoration:none;padding:10px 20px;border-radius:10px;font-weight:600;font-size:14px;">
            <img src="images/Juna.svg" alt="Juna" style="width:24px;height:24px;"> Junat
        </a>
        <a href="bussit.html" style="display:flex;align-items:center;gap:8px;background:#ff6319;color:white;text-decoration:none;padding:10px 20px;border-radius:10px;font-weight:600;font-size:14px;">
            <img src="images/Runkolinja.svg" alt="Runkolinja" style="width:24px;height:24px;"> Runkolinjat
        </a>
        <a href="tilastot.html" style="display:flex;align-items:center;gap:8px;background:#1e3a5f;color:white;text-decoration:none;padding:10px 20px;border-radius:10px;font-weight:600;font-size:14px;">
            <img src="images/Bussi.svg" alt="Tilastot" style="width:24px;height:24px;"> Tilastot
        </a>
    </div>
    <div class="hero">
        <div class="hero-left">
            <h2>Kokonaisluotettavuus eilen</h2>
            <div class="hero-pct">{viimeisin_pct:.1f}<span style="font-size:32px">%</span></div>
            <div class="hero-paiva">📅 {viimeisin_paiva}</div>
        </div>
        <div class="oper-grid">
            {eilinen_oper_html}
        </div>
    </div>

    <!-- Kuvaajat -->
    <div class="kortti" style="margin-bottom:24px;">
        <div class="kortti-otsikko">Kokonaistrendi <i style="font-size:11px;font-weight:400;">alkaen {alkupaiva_data}</i></div>
        <canvas id="kokonaisChart"></canvas>
    </div>
    <div class="kortti" style="margin-bottom:24px;">
        <div class="kortti-otsikko">Operaattorikohtainen trendi <i style="font-size:11px;font-weight:400;">alkaen {alkupaiva_data}</i></div>
        <canvas id="operChart"></canvas>
    </div>

    <!-- Kuukausihistoria -->
    <div class="kortti" style="margin-bottom:24px;overflow-x:auto">
        <div class="kortti-otsikko">Operaattorikohtainen kuukausihistoria <span>painotettu ka</span></div>
        <table>
            <thead><tr><th>Operaattori</th>{kk_header}</tr></thead>
            <tbody>{kk_rivit}</tbody>
        </table>
    </div>

    <div class="grid-2">
        <!-- 10 heikointa linjaa -->
        <div class="kortti">
            <div class="kortti-otsikko">10 heikoiten suoriutunutta linjaa <span>1 kk liukuva</span></div>
            <table>
                <thead><tr><th>Linja</th><th>Operaattori</th><th>Luotettavuus</th><th>Ajettu/Suunn.</th></tr></thead>
                <tbody>{heikoimmat_html}</tbody>
            </table>
        </div>

        <!-- Hälytykset -->
        <div class="kortti">
            <div class="kortti-otsikko">
                Hälytykset <span>viim. 5 pv, raja {HALYTYSTARAJA:.0f} %</span>
            </div>
            <table>
                <thead><tr><th>Päivä</th><th>Linja</th><th>Operaattori</th><th>Luotettavuus</th><th>Ajettu/Suunn.</th></tr></thead>
                <tbody>{halytykset_html}</tbody>
            </table>
        </div>
    </div>

    <!-- Viikonpäiväanalyysi -->
    <div class="kortti" style="margin-bottom:24px;">
        <div class="kortti-otsikko">Luotettavuus viikonpäivittäin <span>12 kk keskiarvo</span> <i style="font-size:11px;font-weight:400;">alkaen {alkupaiva_data}</i></div>
        <canvas id="viikonpaivaChart"></canvas>
    </div>

    <!-- Kellonaika-analyysi -->
    <div class="kortti" style="margin-bottom:24px;">
        <div class="kortti-otsikko">Luotettavuus kellonajan mukaan <span>kumulatiivinen keskiarvo</span> <i style="font-size:11px;font-weight:400;">alkaen {alkupaiva_kello}</i></div>
        <canvas id="kellonaikaChart"></canvas>
    </div>

    <!-- Vuodenaikaluotettavuus -->
    <div class="kortti" style="margin-bottom:24px;">
        <div class="kortti-otsikko">Luotettavuus vuodenajoittain <span>2026</span> <i style="font-size:11px;font-weight:400;">kertyy kauden edetessä</i></div>
        <canvas id="vuodenaika-chart"></canvas>
    </div> 

    <!-- Metodiikka -->
    <div class="metodiikka">
        <strong>Mittausmetodista:</strong> Luotettavuus perustuu HFP-dataan (High-Frequency Positioning).
        Vuoro katsotaan ajetuksi jos ajoneuvolta on saapunut HFP-signaali kyseisen vuoron aikana.
        Jos HFP-data puuttuu (esim. laiterikko), vuoro merkitään ajamattomaksi vaikka se olisi ajettu –
        tämä voi aiheuttaa pientä systemaattista aliarviointia todelliseen luotettavuuteen nähden.
        Pienillä linjoilla (alle 10 vuoroa/kk) yksittäiset poikkeamat vaikuttavat prosenttiin merkittävästi.
    </div>

    <!-- Säävaikutusanalyysi -->
    <div class="kortti" style="margin-bottom:24px;">
        <div class="kortti-otsikko">Säävaikutus luotettavuuteen <span>talvi 2026</span> <i style="font-size:11px;font-weight:400;">1.1.–14.3.2026 · {saavaikutus.get('paivia', 0)} päivää</i></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;">
            <div>
                <div style="font-size:11px;color:#6b8caa;margin-bottom:8px;">Luotettavuus sääluokittain</div>
                <canvas id="saa-pylvas-chart" style="max-height:220px;"></canvas>
            </div>
            <div>
                <div style="font-size:11px;color:#6b8caa;margin-bottom:8px;">Operaattorivertailu: normaali vs. erittäin kylmä</div>
                <canvas id="saa-oper-chart" style="max-height:220px;"></canvas>
            </div>
        </div>
        <div style="font-size:11px;color:#6b8caa;margin-bottom:8px;">Lämpötila vs. luotettavuus (jokainen piste = yksi päivä)</div>
        <canvas id="saa-scatter-chart" style="max-height:300px;margin-bottom:16px;"></canvas>
        <div style="background:#f0f6fc;border-radius:8px;padding:12px 16px;font-size:11px;color:#6b8caa;line-height:1.7;">
            <strong style="color:#1e3a5f;">Analyysimenetelmä:</strong>
            Säädata: Ilmatieteen laitos, Helsinki Kaisaniemi -mittausasema.
            Luotettavuusdata: HSL:n HFP-data (toteutuneet lähdöt) verrattuna GTFS-aikatauluun –
            sama päivittäinen data joka näkyy etusivun trendikuvaajassa.
            Sääluokat: <strong style="color:#1e3a5f;">Normaali</strong> = alin lämpötila yli -10°C, ei lumisadetta ·
            <strong style="color:#1e3a5f;">Lumisade</strong> = sademäärä ≥3 mm ja keskilämpötila ≤+2°C ·
            <strong style="color:#1e3a5f;">Kylmä</strong> = alin lämpötila -10°C – -15°C ·
            <strong style="color:#1e3a5f;">Erittäin kylmä</strong> = alin lämpötila alle -15°C.
            Analyysi kattaa talvikauden 1.1.–14.3.2026 ({saavaikutus.get('paivia', 0)} päivää).
            Lumisade- ja yhdistelmäluokkien otokset ovat pieniä – tulokset suuntaa antavia.
        </div>
    </div>
    
</main>

<script>
const trendiData = {trendi_json};
const operData = {oper_json};

// Kokonaistrendi
const ctx1 = document.getElementById('kokonaisChart').getContext('2d');
new Chart(ctx1, {{
    type: 'line',
    data: {{
        labels: trendiData.paivamaarat,
        datasets: [{{
            label: 'Luotettavuus %',
            data: trendiData.luotettavuus,
            borderColor: '#0071bc',
            backgroundColor: 'rgba(0,113,188,0.08)',
            borderWidth: 2,
            pointRadius: 2,
            pointHoverRadius: 5,
            fill: true,
            tension: 0.3,
        }}]
    }},
    options: {{
        responsive: true,
        plugins: {{
            legend: {{ display: false }},
            tooltip: {{
                callbacks: {{
                    label: ctx => ctx.parsed.y.toFixed(2) + ' %'
                }}
            }}
        }},
        scales: {{
            y: {{
                min: 97,
                max: 100,
                ticks: {{
                    callback: v => v + ' %',
                    color: '#6b8caa',
                    font: {{ size: 11 }}
                }},
                grid: {{ color: 'rgba(0,113,188,0.08)' }}
            }},
            x: {{
                ticks: {{
                    color: '#6b8caa',
                    font: {{ size: 10 }},
                    maxTicksLimit: 8
                }},
                grid: {{ display: false }}
            }}
        }}
    }}
}});

// Viikonpäiväanalyysi (operaattoreittain)
const viikonpaivaOperData = {viikonpaiva_oper_json};
const operVarit = {{
    "Nobina Finland": "#00a650",
    "Koiviston Auto": "#ff6600",
    "Pohjolan Liikenne": "#7b2d8b",
    "Tammelundin Liikenne": "#0071bc"
}};
const ctxVko = document.getElementById('viikonpaivaChart').getContext('2d');
new Chart(ctxVko, {{
    type: 'line',
    data: {{
        labels: {viikonpaiva_labels},
        datasets: Object.entries(viikonpaivaOperData).map(([oper, data]) => ({{
            label: oper,
            data: Object.values(data),
            borderColor: operVarit[oper] || '#999',
            backgroundColor: 'transparent',
            borderWidth: 2.5,
            pointRadius: 3,
            tension: 0.3,
        }}))
    }},
    options: {{
        responsive: true,
        plugins: {{
            legend: {{ display: true, position: 'bottom' }},
            tooltip: {{
                callbacks: {{
                    label: ctx => ctx.parsed.y.toFixed(2) + ' %'
                }}
            }}
        }},
        scales: {{
            y: {{
                min: 97,
                max: 100,
                ticks: {{
                    callback: v => v + ' %',
                    color: '#6b8caa',
                    font: {{ size: 11 }}
                }},
                grid: {{ color: 'rgba(0,113,188,0.08)' }}
            }},
            x: {{
                ticks: {{
                    color: '#6b8caa',
                    font: {{ size: 12 }}
                }},
                grid: {{ display: false }}
            }}
        }}
    }}
}});

// Kellonaika-analyysi
const ctxKlo = document.getElementById('kellonaikaChart').getContext('2d');
new Chart(ctxKlo, {{
    type: 'bar',
    data: {{
        labels: {kellonaika_labels},
        datasets: [{{
            label: 'Luotettavuus %',
            data: {kellonaika_arvot},
            backgroundColor: '#00985f',
            borderRadius: 6,
        }}]
    }},
    options: {{
        responsive: true,
        plugins: {{
            legend: {{ display: false }},
            tooltip: {{
                callbacks: {{
                    label: ctx => ctx.parsed.y.toFixed(2) + ' %'
                }}
            }}
        }},
        scales: {{
            y: {{
                min: 95,
                max: 100,
                ticks: {{
                    callback: v => v + ' %',
                    color: '#6b8caa',
                    font: {{ size: 11 }}
                }},
                grid: {{ color: 'rgba(0,113,188,0.08)' }}
            }},
            x: {{
                ticks: {{
                    color: '#6b8caa',
                    font: {{ size: 10 }}
                }},
                grid: {{ display: false }}
            }}
        }}
    }}
}});

// Vuodenaikaluotettavuus
const vuodenaika = {vuodenaika_json};
const vuodenaika_varit = {{
    "Nobina Finland":   "#00a650",
    "Koiviston Auto":   "#ff6600",
    "Pohjolan Liikenne": "#7b2d8b",
    "Tammelundin Liikenne": "#0071bc",
}};

if (Object.keys(vuodenaika).length > 0) {{
    const kaudet = Object.keys(vuodenaika);
    const operaattorit = ["Nobina Finland","Koiviston Auto","Pohjolan Liikenne","Tammelundin Liikenne"];

    const ctxVa = document.getElementById('vuodenaika-chart').getContext('2d');
    new Chart(ctxVa, {{
        type: 'bar',
        data: {{
            labels: kaudet.map(k => `${{k}} (${{vuodenaika[k].alku}}–${{vuodenaika[k].loppu}})`),
            datasets: [
                {{
                    label: 'Koko HSL',
                    data: kaudet.map(k => vuodenaika[k].koko_hsl || null),
                    backgroundColor: '#93c5fd',
                    borderRadius: 4,
                }},
                ...operaattorit
                    .filter(op => kaudet.some(k => vuodenaika[k].operaattorit[op] !== undefined))
                    .map(op => ({{
                        label: op,
                        data: kaudet.map(k => vuodenaika[k].operaattorit[op] || null),
                        backgroundColor: vuodenaika_varit[op],
                        borderRadius: 4,
                    }}))
            ]
        }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{ display: true, position: 'bottom', labels: {{ font: {{ size: 11 }}, padding: 12, boxWidth: 16 }} }},
                tooltip: {{
                    callbacks: {{
                        label: ctx => ctx.parsed.y !== null ? `${{ctx.dataset.label}}: ${{ctx.parsed.y.toFixed(2)}} %` : null,
                        afterBody: (items) => {{
                            const k = kaudet[items[0].dataIndex];
                            return [`Päiviä datassa: ${{vuodenaika[k].paivat}}`];
                        }}
                    }}
                }}
            }},
            scales: {{
                y: {{
                    min: 97,
                    max: 100,
                    ticks: {{
                        callback: v => v + ' %',
                        color: '#6b8caa',
                        font: {{ size: 11 }}
                    }},
                    grid: {{ color: 'rgba(0,113,188,0.08)' }}
                }},
                x: {{
                    ticks: {{ color: '#6b8caa', font: {{ size: 10 }} }},
                    grid: {{ display: false }}
                }}
            }}
        }}
    }});
}}

// Säävaikutusanalyysi
const saavaikutus = {saavaikutus_json};

if (saavaikutus.pylvas && Object.keys(saavaikutus.pylvas).length > 0) {{
    const saaLuokat = ["Normaali","Lumisade","Kylmä","Erittäin kylmä"];
    const saaVarit = {{
        "Normaali":       "#0071bc",
        "Lumisade":       "#00a650",
        "Kylmä":          "#f59e0b",
        "Erittäin kylmä": "#dc2626",
    }};

    // Kuvaaja 1: Pylväs sääluokittain
    const pylvasLabels = saaLuokat.filter(l => saavaikutus.pylvas[l]);
    const ctxP = document.getElementById('saa-pylvas-chart').getContext('2d');
    new Chart(ctxP, {{
        type: 'bar',
        data: {{
            labels: pylvasLabels.map(l => `${{l}}\n(n=${{saavaikutus.pylvas[l].n}})`),
            datasets: [{{
                label: 'Luotettavuus %',
                data: pylvasLabels.map(l => saavaikutus.pylvas[l].ka),
                backgroundColor: pylvasLabels.map(l => saaVarit[l]),
                borderRadius: 4,
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{ display: false }},
                tooltip: {{ callbacks: {{
                    label: ctx => `Ka: ${{ctx.parsed.y.toFixed(2)}} % (min: ${{saavaikutus.pylvas[pylvasLabels[ctx.dataIndex]].min}} %)`
                }}}}
            }},
            scales: {{
                y: {{
                    min: 95, max: 100,
                    ticks: {{ callback: v => v + ' %', color: '#6b8caa', font: {{ size: 10 }} }},
                    grid: {{ color: 'rgba(0,113,188,0.08)' }}
                }},
                x: {{ ticks: {{ color: '#6b8caa', font: {{ size: 9 }} }}, grid: {{ display: false }} }}
            }}
        }}
    }});

    // Kuvaaja 2: Operaattorivertailu
    const operaattorit = ["Nobina Finland","Koiviston Auto","Pohjolan Liikenne","Tammelundin Liikenne"];
    const operVarit = {{
        "Nobina Finland": "#00a650",
        "Koiviston Auto": "#ff6600",
        "Pohjolan Liikenne": "#7b2d8b",
        "Tammelundin Liikenne": "#0071bc",
    }};
    const ctxO = document.getElementById('saa-oper-chart').getContext('2d');
    new Chart(ctxO, {{
        type: 'bar',
        data: {{
            labels: operaattorit,
            datasets: [
                {{
                    label: 'Normaali',
                    data: operaattorit.map(op => saavaikutus.oper[op]?.['Normaali'] || null),
                    backgroundColor: operaattorit.map(op => operVarit[op] + 'aa'),
                    borderRadius: 4,
                }},
                {{
                    label: 'Erittäin kylmä',
                    data: operaattorit.map(op => saavaikutus.oper[op]?.['Erittäin kylmä'] || null),
                    backgroundColor: operaattorit.map(op => operVarit[op]),
                    borderRadius: 4,
                }},
            ]
        }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{ position: 'bottom', labels: {{ font: {{ size: 10 }}, padding: 8, boxWidth: 12 }} }},
                tooltip: {{ callbacks: {{ label: ctx => `${{ctx.dataset.label}}: ${{ctx.parsed.y?.toFixed(2)}} %` }} }}
            }},
            scales: {{
                y: {{
                    min: 94, max: 100,
                    ticks: {{ callback: v => v + ' %', color: '#6b8caa', font: {{ size: 10 }} }},
                    grid: {{ color: 'rgba(0,113,188,0.08)' }}
                }},
                x: {{ ticks: {{ color: '#6b8caa', font: {{ size: 9 }} }}, grid: {{ display: false }} }}
            }}
        }}
    }});

    // Kuvaaja 3: Scatter lämpötila vs luotettavuus
    const ctxS = document.getElementById('saa-scatter-chart').getContext('2d');
    new Chart(ctxS, {{
        type: 'scatter',
        data: {{
            datasets: Object.keys(operVarit).map(op => ({{
                label: op,
                data: saavaikutus.scatter
                    .filter(p => p.operaattori === op)
                    .map(p => ({{ x: p.x, y: p.y, luokka: p.luokka, paiva: p.paiva }})),
                backgroundColor: operVarit[op] + 'aa',
                pointRadius: 4,
            }}))
        }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{ position: 'bottom', labels: {{ font: {{ size: 10 }}, padding: 8, boxWidth: 12 }} }},
                tooltip: {{ callbacks: {{
                    label: ctx => `${{ctx.parsed.y.toFixed(2)}} % · ${{ctx.parsed.x.toFixed(1)}}°C`
                }}}}
            }},
            scales: {{
                x: {{
                    title: {{ display: true, text: 'Alin lämpötila (°C)', color: '#6b8caa', font: {{ size: 10 }} }},
                    ticks: {{ color: '#6b8caa', font: {{ size: 10 }}, callback: v => v + '°' }},
                    grid: {{ color: 'rgba(0,113,188,0.08)' }}
                }},
                y: {{
                    min: 88, max: 100,
                    title: {{ display: true, text: 'Luotettavuus %', color: '#6b8caa', font: {{ size: 10 }} }},
                    ticks: {{ color: '#6b8caa', font: {{ size: 10 }}, callback: v => v + ' %' }},
                    grid: {{ color: 'rgba(0,113,188,0.08)' }}
                }}
            }}
        }}
    }});
}}

// Operaattoritrendi
const ctx2 = document.getElementById('operChart').getContext('2d');
const datasets = Object.entries(operData.operaattorit).map(([oper, arvot]) => ({{
    label: oper,
    data: arvot,
    borderColor: operData.varit[oper] || '#999',
    backgroundColor: 'transparent',
    borderWidth: 2,
    pointRadius: 2,
    pointHoverRadius: 5,
    tension: 0.3,
    spanGaps: true,
}}));

new Chart(ctx2, {{
    type: 'line',
    data: {{
        labels: operData.paivamaarat,
        datasets: datasets
    }},
    options: {{
        responsive: true,
        plugins: {{
            legend: {{
                display: true,
                position: 'bottom',
                labels: {{
                    color: '#1e3a5f',
                    font: {{ size: 11 }},
                    boxWidth: 12,
                    padding: 12
                }}
            }},
            tooltip: {{
                callbacks: {{
                    label: ctx => ctx.dataset.label + ': ' + (ctx.parsed.y ? ctx.parsed.y.toFixed(2) + ' %' : '–')
                }}
            }}
        }},
        scales: {{
            y: {{
                min: 95,
                max: 100,
                ticks: {{
                    callback: v => v + ' %',
                    color: '#6b8caa',
                    font: {{ size: 11 }}
                }},
                grid: {{ color: 'rgba(0,113,188,0.08)' }}
            }},
            x: {{
                ticks: {{
                    color: '#6b8caa',
                    font: {{ size: 10 }},
                    maxTicksLimit: 8
                }},
                grid: {{ display: false }}
            }}
        }}
    }}
}});
</script>
</body>
</html>"""
    return html


def main():
    print("🌐 Generoidaan dashboard...")
    os.makedirs(DOCS_KANSIO, exist_ok=True)
    # Injektoidaan Digitransit API-avain metro.html:ään
    api_avain = os.environ.get("DIGITRANSIT_API_KEY", "")
    metro_src = os.path.join(DOCS_KANSIO, "metro.html")
    if os.path.exists(metro_src) and api_avain:
        with open(metro_src, "r", encoding="utf-8") as f:
            metro_html = f.read()
        metro_html = metro_html.replace(
            'const DIGITRANSIT_KEY = "";',
            f'const DIGITRANSIT_KEY = "{api_avain}";'
        )
        with open(metro_src, "w", encoding="utf-8") as f:
            f.write(metro_html)
        print("✅ API-avain injektoitu metro.html:ään")
    # Injektoidaan myös raitiovaunut.html:ään
    raitio_src = os.path.join(DOCS_KANSIO, "raitiovaunut.html")
    if os.path.exists(raitio_src) and api_avain:
        with open(raitio_src, "r", encoding="utf-8") as f:
            raitio_html = f.read()
        raitio_html = raitio_html.replace(
            'const DIGITRANSIT_KEY = "";',
            f'const DIGITRANSIT_KEY = "{api_avain}";'
        )
        with open(raitio_src, "w", encoding="utf-8") as f:
            f.write(raitio_html)
        print("✅ API-avain injektoitu raitiovaunut.html:ään")

    # Injektoidaan myös junat.html:ään
    junat_src = os.path.join(DOCS_KANSIO, "junat.html")
    if os.path.exists(junat_src) and api_avain:
        with open(junat_src, "r", encoding="utf-8") as f:
            junat_html = f.read()
        junat_html = junat_html.replace(
            'const DIGITRANSIT_KEY = "";',
            f'const DIGITRANSIT_KEY = "{api_avain}";'
        )
        with open(junat_src, "w", encoding="utf-8") as f:
            f.write(junat_html)
        print("✅ API-avain injektoitu junat.html:ään")
        
    # Injektoidaan myös bussit.html:ään
    bussit_src = os.path.join(DOCS_KANSIO, "bussit.html")
    if os.path.exists(bussit_src) and api_avain:
        with open(bussit_src, "r", encoding="utf-8") as f:
            bussit_html = f.read()
        bussit_html = bussit_html.replace(
            'const DIGITRANSIT_KEY = "";',
            f'const DIGITRANSIT_KEY = "{api_avain}";'
        )
        with open(bussit_src, "w", encoding="utf-8") as f:
            f.write(bussit_html)
        print("✅ API-avain injektoitu bussit.html:ään")
        
    trendi = lataa_trendi()
    if trendi.empty:
        print("❌ Ei trenditietoja saatavilla")
        return

    api_avain = os.environ.get("DIGITRANSIT_API_KEY", "")
    reittinimet = hae_reittinimet(api_avain)
    print(f"  ✓ {len(reittinimet)} reittinimeä haettu")
    viikonpaivat, viikonpaivat_oper = laske_viikonpaivat(trendi)
    print(f"  ✓ Viikonpäiväkeskiarvot laskettu")
    vuodenaika = laske_vuodenaika(trendi)
    print(f"  ✓ Vuodenaikaluotettavuus laskettu")
    saavaikutus = laske_saavaikutus(trendi)
    print(f"  ✓ Säävaikutusanalyysi laskettu")
    kellonajat = laske_kellonaika()
    print(f"  ✓ Kellonaikakeskiarvot laskettu")
    html = generoi_html(trendi, reittinimet, viikonpaivat, kellonajat, viikonpaivat_oper, vuodenaika, saavaikutus)
    polku = os.path.join(DOCS_KANSIO, "index.html")
    with open(polku, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ Dashboard generoitu: {polku}")
    print(f"   {len(trendi)} päivää dataa")


if __name__ == "__main__":
    main()
