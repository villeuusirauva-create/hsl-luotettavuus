"""
generate_suoriutuminen.py
=========================
Lukee suoriutuminen_pohja.xlsx -tiedoston ja generoi docs/suoriutuminen_data.js
jota kaikki suoriutumissivut käyttävät datalähteenä.

Ajo: python generate_suoriutuminen.py
Vaatii: pip install openpyxl pandas
"""

import os
import json
import pandas as pd
from datetime import datetime

EXCEL_POLKU = "suoriutuminen_pohja.xlsx"
OUTPUT_POLKU = os.path.join("docs", "suoriutuminen_data.js")

OPERAATTORIT = ["Koiviston Auto", "Nobina Finland", "Pohjolan Liikenne",
                "Pohjolan kaupunkiliikenne", "Tammelundin Liikenne", "Transdev"]

AKTIIVISET = ["Koiviston Auto", "Nobina Finland", "Pohjolan Liikenne", "Tammelundin Liikenne"]

VARIT = {
    "Koiviston Auto":            "#ff6600",
    "Nobina Finland":            "#00a650",
    "Pohjolan Liikenne":         "#7b2d8b",
    "Pohjolan kaupunkiliikenne": "#0071bc",
    "Tammelundin Liikenne":      "#0071bc",
    "Transdev":                  "#94a3b8",
}


# ── APUFUNKTIOT ─────────────────────────────────────────────────

def lue_luotettavuus():
    df = pd.read_excel(EXCEL_POLKU, sheet_name="Luotettavuus", skiprows=3, header=0)
    df = df.iloc[:, 1:6]
    df.columns = ["vuosi","kuukausi","operaattori","luotettavuus_pct","euroarvo_kk"]
    df = df[df["vuosi"].notna()].copy()
    df["vuosi"] = df["vuosi"].astype(int)
    df["kuukausi"] = df["kuukausi"].astype(int)
    df["pvm"] = pd.to_datetime({"year":df["vuosi"],"month":df["kuukausi"],"day":1})
    print(f"  Luotettavuus: {len(df)} riviä, {df['pvm'].min().strftime('%m/%Y')}–{df['pvm'].max().strftime('%m/%Y')}")
    return df


def lue_asty():
    df = pd.read_excel(EXCEL_POLKU, sheet_name="ASTY", skiprows=3, header=0)
    df = df.iloc[:, 1:8]
    df.columns = ["vuosi","kausi","operaattori","sopimus_id","asty_arvo","euroarvo_puolivuosi","bonus_eur"]
    df = df[df["vuosi"].notna()].copy()
    df["vuosi"] = df["vuosi"].astype(int)
    print(f"  ASTY: {len(df)} riviä, {df['vuosi'].min()}–{df['vuosi'].max()}")
    return df


def lue_jola():
    df = pd.read_excel(EXCEL_POLKU, sheet_name="JOLA", skiprows=3, header=0)
    df = df.iloc[:, 1:8]
    df.columns = ["vuosi","kausi","operaattori","sopimus_id","jola_arvo","euroarvo_puolivuosi","bonus_eur"]
    df = df[df["vuosi"].notna()].copy()
    df["vuosi"] = df["vuosi"].astype(int)
    print(f"  JOLA: {len(df)} riviä, {df['vuosi'].min()}–{df['vuosi'].max()}")
    return df


def lue_luka():
    df = pd.read_excel(EXCEL_POLKU, sheet_name="LUKA", skiprows=3, header=0)
    df = df.iloc[:, 1:12]
    df.columns = ["vuosi","kuukausi","operaattori","sopimus_id",
                  "A_kattavuus","K1_pct","K2_pct","K3_pct",
                  "kannuste_pct","korvaus_eur","kannuste_eur"]
    df = df[df["vuosi"].notna()].copy()
    df["vuosi"] = df["vuosi"].astype(int)
    df["kuukausi"] = df["kuukausi"].astype(int)
    df["pvm"] = pd.to_datetime({"year":df["vuosi"],"month":df["kuukausi"],"day":1})
    print(f"  LUKA: {len(df)} riviä, {df['pvm'].min().strftime('%m/%Y')}–{df['pvm'].max().strftime('%m/%Y')}")
    return df


def painotettu_ka(df, arvo_col, paino_col):
    """Laskee painotetun keskiarvon jos painoja saatavilla, muuten tavallinen ka."""
    valid = df[[arvo_col, paino_col]].dropna()
    if len(valid) > 0 and valid[paino_col].sum() > 0:
        return (valid[arvo_col] * valid[paino_col]).sum() / valid[paino_col].sum()
    return df[arvo_col].mean()


def n(v, decimals=3):
    """Muuttaa NaN:n None:ksi ja pyöristää."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return round(float(v), decimals)


# ── LUOTETTAVUUS-DATA ────────────────────────────────────────────

def laske_luotettavuus_data(df):
    data = {}

    # Vuositaso
    vuodet = sorted(df["vuosi"].unique().tolist())
    data["vuodet"] = vuodet
    data["vuosi_kaikki"] = [n(df[df["vuosi"]==v]["luotettavuus_pct"].mean()) for v in vuodet]
    data["vuosi_oper"] = {}
    for op in OPERAATTORIT:
        sub = df[df["operaattori"]==op]
        data["vuosi_oper"][op] = [
            n(sub[sub["vuosi"]==v]["luotettavuus_pct"].mean()) for v in vuodet
        ]

    # Kuukausitaso 12kk
    viimeisin_pvm = df["pvm"].max()
    raja = viimeisin_pvm - pd.DateOffset(months=12)
    df12 = df[df["pvm"] > raja].sort_values("pvm")
    kk_pvmt = sorted(df12["pvm"].unique())
    data["kk_labels"] = [pd.Timestamp(p).strftime("%m/%y") for p in kk_pvmt]
    data["kk_kaikki"] = [n(df12[df12["pvm"]==p]["luotettavuus_pct"].mean()) for p in kk_pvmt]
    data["kk_oper"] = {}
    for op in OPERAATTORIT:
        sub12 = df12[df12["operaattori"]==op]
        data["kk_oper"][op] = [
            n(sub12[sub12["pvm"]==p]["luotettavuus_pct"].values[0])
            if len(sub12[sub12["pvm"]==p]) > 0 else None
            for p in kk_pvmt
        ]

    # Hero
    data["hero"] = {}
    for op in OPERAATTORIT:
        sub = df[df["operaattori"]==op].sort_values("pvm")
        if len(sub) > 0:
            viim = sub.iloc[-1]
            data["hero"][op] = {
                "arvo": n(viim["luotettavuus_pct"], 2),
                "kk": f"{int(viim['kuukausi'])}/{int(viim['vuosi'])}"
            }

    aktiiviset_viim = df[df["operaattori"].isin(AKTIIVISET) & (df["pvm"]==viimeisin_pvm)]
    data["hsl_viimeisin"] = n(aktiiviset_viim["luotettavuus_pct"].mean(), 2)
    data["hsl_kk"] = f"{int(viimeisin_pvm.month)}/{int(viimeisin_pvm.year)}"

    return data


# ── ASTY-DATA ────────────────────────────────────────────────────

def laske_asty_data(df):
    data = {}

    # Vuositaso (painotettu euroarvoilla)
    vuodet = sorted(df["vuosi"].unique().tolist())
    data["vuodet"] = vuodet
    data["vuosi_kaikki"] = [n(painotettu_ka(df[df["vuosi"]==v], "asty_arvo", "euroarvo_puolivuosi"), 3) for v in vuodet]
    data["vuosi_oper"] = {}
    for op in OPERAATTORIT:
        sub = df[df["operaattori"]==op]
        data["vuosi_oper"][op] = [
            n(painotettu_ka(sub[sub["vuosi"]==v], "asty_arvo", "euroarvo_puolivuosi"), 3)
            if len(sub[sub["vuosi"]==v]) > 0 else None
            for v in vuodet
        ]

    # Puolivuositaso 6 kautta taaksepäin
    kaudet = df.sort_values(["vuosi","kausi"],
                             key=lambda c: c.map({"kevät":0,"syksy":1}) if c.name=="kausi" else c)
    viimeiset_kaudet = kaudet[["vuosi","kausi"]].drop_duplicates().tail(6)
    data["kk_labels"] = [f"{r['kausi']} {r['vuosi']}" for _,r in viimeiset_kaudet.iterrows()]
    data["kk_kaikki"] = []
    data["kk_oper"] = {op: [] for op in OPERAATTORIT}
    for _,r in viimeiset_kaudet.iterrows():
        sub = df[(df["vuosi"]==r["vuosi"]) & (df["kausi"]==r["kausi"])]
        data["kk_kaikki"].append(n(painotettu_ka(sub, "asty_arvo", "euroarvo_puolivuosi"), 3))
        for op in OPERAATTORIT:
            s = sub[sub["operaattori"]==op]
            data["kk_oper"][op].append(
                n(painotettu_ka(s, "asty_arvo", "euroarvo_puolivuosi"), 3) if len(s) > 0 else None
            )

    # Viimeisin kausi – sopimuskohtainen hajonta
    viim_r = viimeiset_kaudet.iloc[-1]
    viim_sub = df[(df["vuosi"]==viim_r["vuosi"]) & (df["kausi"]==viim_r["kausi"])]
    data["viimeisin_kausi_label"] = f"{viim_r['kausi']} {viim_r['vuosi']}"
    data["sopimukset"] = viim_sub[["operaattori","sopimus_id","asty_arvo","euroarvo_puolivuosi"]]\
        .dropna(subset=["asty_arvo"])\
        .sort_values("asty_arvo", ascending=False)\
        .to_dict(orient="records")

    # Hero
    data["hero"] = {}
    for op in OPERAATTORIT:
        sub = df[df["operaattori"]==op]
        if len(sub) > 0:
            viim = sub.sort_values(["vuosi","kausi"],
                                    key=lambda c: c.map({"kevät":0,"syksy":1}) if c.name=="kausi" else c).iloc[-1]
            data["hero"][op] = {
                "arvo": n(painotettu_ka(df[(df["vuosi"]==viim["vuosi"]) &
                          (df["kausi"]==viim["kausi"]) & (df["operaattori"]==op)],
                          "asty_arvo","euroarvo_puolivuosi"), 3),
                "kk": f"{viim['kausi']} {viim['vuosi']}"
            }

    viim_kaikki = df[(df["vuosi"]==viim_r["vuosi"]) & (df["kausi"]==viim_r["kausi"])]
    data["hsl_viimeisin"] = n(painotettu_ka(viim_kaikki,"asty_arvo","euroarvo_puolivuosi"), 3)
    data["hsl_kk"] = f"{viim_r['kausi']} {viim_r['vuosi']}"

    return data


# ── JOLA-DATA ────────────────────────────────────────────────────

def laske_jola_data(df):
    data = {}

    vuodet = sorted(df["vuosi"].unique().tolist())
    data["vuodet"] = vuodet
    data["vuosi_kaikki"] = [n(painotettu_ka(df[df["vuosi"]==v], "jola_arvo", "euroarvo_puolivuosi"), 2) for v in vuodet]
    data["vuosi_oper"] = {}
    for op in OPERAATTORIT:
        sub = df[df["operaattori"]==op]
        data["vuosi_oper"][op] = [
            n(painotettu_ka(sub[sub["vuosi"]==v], "jola_arvo", "euroarvo_puolivuosi"), 2)
            if len(sub[sub["vuosi"]==v]) > 0 else None
            for v in vuodet
        ]

    kaudet = df.sort_values(["vuosi","kausi"],
                             key=lambda c: c.map({"kevät":0,"syksy":1}) if c.name=="kausi" else c)
    viimeiset_kaudet = kaudet[["vuosi","kausi"]].drop_duplicates().tail(6)
    data["kk_labels"] = [f"{r['kausi']} {r['vuosi']}" for _,r in viimeiset_kaudet.iterrows()]
    data["kk_kaikki"] = []
    data["kk_oper"] = {op: [] for op in OPERAATTORIT}
    for _,r in viimeiset_kaudet.iterrows():
        sub = df[(df["vuosi"]==r["vuosi"]) & (df["kausi"]==r["kausi"])]
        data["kk_kaikki"].append(n(painotettu_ka(sub, "jola_arvo", "euroarvo_puolivuosi"), 2))
        for op in OPERAATTORIT:
            s = sub[sub["operaattori"]==op]
            data["kk_oper"][op].append(
                n(painotettu_ka(s, "jola_arvo", "euroarvo_puolivuosi"), 2) if len(s) > 0 else None
            )

    viim_r = viimeiset_kaudet.iloc[-1]
    viim_sub = df[(df["vuosi"]==viim_r["vuosi"]) & (df["kausi"]==viim_r["kausi"])]
    data["viimeisin_kausi_label"] = f"{viim_r['kausi']} {viim_r['vuosi']}"
    data["sopimukset"] = viim_sub[["operaattori","sopimus_id","jola_arvo","euroarvo_puolivuosi"]]\
        .dropna(subset=["jola_arvo"])\
        .sort_values("jola_arvo")\
        .to_dict(orient="records")

    data["hero"] = {}
    for op in OPERAATTORIT:
        sub = df[df["operaattori"]==op]
        if len(sub) > 0:
            viim = sub.sort_values(["vuosi","kausi"],
                                    key=lambda c: c.map({"kevät":0,"syksy":1}) if c.name=="kausi" else c).iloc[-1]
            data["hero"][op] = {
                "arvo": n(painotettu_ka(df[(df["vuosi"]==viim["vuosi"]) &
                          (df["kausi"]==viim["kausi"]) & (df["operaattori"]==op)],
                          "jola_arvo","euroarvo_puolivuosi"), 2),
                "kk": f"{viim['kausi']} {viim['vuosi']}"
            }

    data["hsl_viimeisin"] = n(painotettu_ka(viim_sub, "jola_arvo", "euroarvo_puolivuosi"), 2)
    data["hsl_kk"] = f"{viim_r['kausi']} {viim_r['vuosi']}"

    return data


# ── LUKA-DATA ────────────────────────────────────────────────────

def laske_luka_data(df):
    data = {}

    vuodet = sorted(df["vuosi"].unique().tolist())
    data["vuodet"] = vuodet
    data["vuosi_kaikki"] = [n(df[df["vuosi"]==v]["K2_pct"].mean(), 4) for v in vuodet]
    data["vuosi_oper"] = {}
    for op in OPERAATTORIT:
        sub = df[df["operaattori"]==op]
        data["vuosi_oper"][op] = [
            n(sub[sub["vuosi"]==v]["K2_pct"].mean(), 4)
            if len(sub[sub["vuosi"]==v]) > 0 else None
            for v in vuodet
        ]

    viimeisin_pvm = df["pvm"].max()
    raja = viimeisin_pvm - pd.DateOffset(months=12)
    df12 = df[df["pvm"] > raja].sort_values("pvm")
    kk_pvmt = sorted(df12["pvm"].unique())
    data["kk_labels"] = [pd.Timestamp(p).strftime("%m/%y") for p in kk_pvmt]

    for indik in ["K1_pct","K2_pct","K3_pct","A_kattavuus","kannuste_pct"]:
        data[f"kk_{indik}"] = [n(df12[df12["pvm"]==p][indik].mean(), 4) for p in kk_pvmt]

    data["kk_oper_K2"] = {}
    for op in OPERAATTORIT:
        sub12 = df12[df12["operaattori"]==op]
        data["kk_oper_K2"][op] = [
            n(sub12[sub12["pvm"]==p]["K2_pct"].mean(), 4)
            if len(sub12[sub12["pvm"]==p]) > 0 else None
            for p in kk_pvmt
        ]

    # Viimeisin kuukausi – sopimuskohtainen
    viim_sub = df[df["pvm"]==viimeisin_pvm]
    data["viimeisin_kk_label"] = viimeisin_pvm.strftime("%m/%Y")
    data["sopimukset"] = viim_sub[["operaattori","sopimus_id","K2_pct","A_kattavuus","kannuste_pct","korvaus_eur"]]\
        .dropna(subset=["K2_pct"])\
        .sort_values("K2_pct", ascending=False)\
        .to_dict(orient="records")

    data["hero"] = {}
    for op in OPERAATTORIT:
        sub = df[df["operaattori"]==op]
        if len(sub) > 0:
            viim = sub.sort_values("pvm").iloc[-1]
            data["hero"][op] = {
                "arvo": n(df[(df["pvm"]==viim["pvm"]) & (df["operaattori"]==op)]["K2_pct"].mean(), 4),
                "kk": viim["pvm"].strftime("%m/%Y")
            }

    aktiiviset_viim = df[df["operaattori"].isin(AKTIIVISET) & (df["pvm"]==viimeisin_pvm)]
    data["hsl_viimeisin"] = n(aktiiviset_viim["K2_pct"].mean(), 4)
    data["hsl_kk"] = viimeisin_pvm.strftime("%m/%Y")

    return data


# ── PÄÄOHJELMA ───────────────────────────────────────────────────

def main():
    print()
    print("📊 Generoidaan suoriutumisdata...")
    print("─" * 50)

    if not os.path.exists(EXCEL_POLKU):
        print(f"❌ Tiedostoa ei löydy: {EXCEL_POLKU}")
        print("   Varmista että suoriutuminen_pohja.xlsx on samassa kansiossa.")
        return

    print("📥 Luetaan Excel-tietokanta...")
    df_luot = lue_luotettavuus()
    df_asty = lue_asty()
    df_jola = lue_jola()
    df_luka = lue_luka()

    print()
    print("⚙️  Lasketaan data kuvaajia varten...")
    data = {
        "paivitetty": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "varit": VARIT,
        "aktiiviset": AKTIIVISET,
        "kaikki_oper": OPERAATTORIT,
        "luotettavuus": laske_luotettavuus_data(df_luot),
        "asty":         laske_asty_data(df_asty),
        "jola":         laske_jola_data(df_jola),
        "luka":         laske_luka_data(df_luka),
    }

    os.makedirs("docs", exist_ok=True)
    js_content = f"// Generoitu automaattisesti: {data['paivitetty']}\n"
    js_content += f"// Älä muokkaa käsin – aja generate_suoriutuminen.py uudelleen\n"
    js_content += f"const SUORIUTUMINEN = {json.dumps(data, ensure_ascii=False, indent=2)};\n"

    with open(OUTPUT_POLKU, "w", encoding="utf-8") as f:
        f.write(js_content)

    print()
    print(f"✅ Tallennettu: {OUTPUT_POLKU}")
    print(f"   Päivitetty: {data['paivitetty']}")
    print()


if __name__ == "__main__":
    main()
