"""
HSL Dashboard Generator
========================
Lukee tulokset/-kansion datan ja generoi docs/index.html -tiedoston.
Ajetaan GitHub Actionsissa joka päivä analyysin jälkeen.
"""

import os
import json
import datetime
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
    return df.sort_values("paiva").reset_index(drop=True)


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


def generoi_html(trendi_df):
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
        for _, r in heikoimmat.iterrows():
            vari = "#dc2626" if r["luotettavuus"] < 90 else "#d97706" if r["luotettavuus"] < 95 else "#2563eb"
            heikoimmat_html += f"""
            <tr>
                <td class="linja-nimi">{r['linja']}</td>
                <td>{r['operaattori']}</td>
                <td style="color:{vari};font-weight:600">{r['luotettavuus']:.1f} %</td>
                <td class="muted">{int(r['ajettu']):,} / {int(r['suunnitellut']):,}</td>
            </tr>"""
    else:
        heikoimmat_html = '<tr><td colspan="4" class="muted">Linjakohtainen data kertyy päivittäin</td></tr>'

    # Hälytykset
    halytyslinjat = laske_halytyslinjat(trendi_df, HALYTYSTARAJA)
    halytykset_html = ""
    if halytyslinjat:
        for h in halytyslinjat[:20]:
            halytykset_html += f"""
            <tr>
                <td class="muted">{h['paiva']}</td>
                <td class="linja-nimi">{h['linja']}</td>
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
                tekstivari = "#dc2626" if arvo < 97 else "#16a34a" if arvo >= 99 else "#1e3a5f"
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
                tekstivari = "#dc2626" if arvo < 97 else "#16a34a" if arvo >= 99 else "#1e3a5f"
                eilinen_oper_html += f"""
                <div class="oper-kortti">
                    <div class="oper-nimi" style="color:{vari_oper}">{oper}</div>
                    <div class="oper-pct" style="color:{tekstivari}">{arvo:.1f} %</div>
                </div>"""

    paivitys_aika = (datetime.datetime.utcnow() + 
                     datetime.timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")
    pct_vari = "#dc2626" if viimeisin_pct < 97 else "#16a34a" if viimeisin_pct >= 99 else "#d97706"

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
            <div class="hsl-logo">HSL</div>
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
    <div class="grid-2">
        <div class="kortti">
            <div class="kortti-otsikko">Kokonaistrendi <span>3 kk</span></div>
            <canvas id="kokonaisChart"></canvas>
        </div>
        <div class="kortti">
            <div class="kortti-otsikko">Operaattorikohtainen trendi <span>3 kk</span></div>
            <canvas id="operChart"></canvas>
        </div>
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

    <!-- Metodiikka -->
    <div class="metodiikka">
        <strong>Mittausmetodista:</strong> Luotettavuus perustuu HFP-dataan (High-Frequency Positioning).
        Vuoro katsotaan ajetuksi jos ajoneuvolta on saapunut HFP-signaali kyseisen vuoron aikana.
        Jos HFP-data puuttuu (esim. laiterikko), vuoro merkitään ajamattomaksi vaikka se olisi ajettu –
        tämä voi aiheuttaa pientä systemaattista aliarviointia todelliseen luotettavuuteen nähden.
        Pienillä linjoilla (alle 10 vuoroa/kk) yksittäiset poikkeamat vaikuttavat prosenttiin merkittävästi.
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
                min: Math.max(85, Math.min(...trendiData.luotettavuus) - 2),
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
                min: 90,
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

    trendi = lataa_trendi()
    if trendi.empty:
        print("❌ Ei trenditietoja saatavilla")
        return

    html = generoi_html(trendi)
    polku = os.path.join(DOCS_KANSIO, "index.html")
    with open(polku, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ Dashboard generoitu: {polku}")
    print(f"   {len(trendi)} päivää dataa")


if __name__ == "__main__":
    main()
