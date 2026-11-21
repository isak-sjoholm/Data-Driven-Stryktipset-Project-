import re
from datetime import datetime, timezone
import streamlit as st
import pandas as pd
import altair as alt
import gspread
from google.oauth2.service_account import Credentials

SERVICE_ACCOUNT_FILE = "stryktipset-priors-automation-27f390beda4d.json"
SHEET_ID = "1O7dHCXAblAGXLAzOKYQ93hr7DTkFUv7iqEg2aUkaidY"
SKRIV_FLIK = "Current Round"

try:
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
except Exception:
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )

sh = gspread.authorize(creds).open_by_key(SHEET_ID)

v = st.session_state.get("v", 0)

st.title("Stryktipset")

st.markdown(
    """
    <style>
    [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 0.5rem !important; }
    [data-testid="stColumn"], [data-testid="column"] { min-width: 0 !important; width: auto !important; flex: 1 1 0 !important; }
    .stButton button { height: 3.5rem; font-size: 1.3rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

if "klar" in st.session_state:
    st.success(st.session_state.pop("klar"))

rader_plats = st.empty()
namn = st.text_input("Your Name (Required)", key=f"namn_{v}")

st.subheader("Matcher")

values = sh.worksheet("Current Round").get_all_values()
kupong_kol = [h.strip().lower() for h in values[0]].index("kupong_raw_stryktipset")
celler = [rad[kupong_kol] for rad in values[1:] if len(rad) > kupong_kol and rad[kupong_kol].strip() != ""]

if len(celler) == 0:
    st.warning("Ingen kupong i Current Round just nu.")
else:
    matcher = []
    for s in celler[0].split(";"):
        d = [p.strip() for p in s.split(",")]
        m = re.match(r"Game\s+(\d+)", d[0], re.I)
        if len(d) >= 9 and m and 1 <= int(m.group(1)) <= 13:
            matcher.append({
                "R": int(m.group(1)),
                "Hemmalag": d[1],
                "Bortalag": d[2],
                "Folk 1 %": d[3],
                "Folk X %": d[4],
                "Folk 2 %": d[5],
                "Odds 1": d[6],
                "Odds X": d[7],
                "Odds 2": d[8],
            })
    games = pd.DataFrame(matcher).sort_values("R")
    for col in games.columns[3:]:
        games[col] = pd.to_numeric(games[col].str.replace("%", "").str.replace(",", "."), errors="coerce")

    k1, kx, k2, plats = [], [], [], []
    for _, g in games.iterrows():
        nr = int(g["R"])
        with st.container(border=True):
            c = st.columns([1, 3, 3, 2, 2, 2])
            c[0].markdown(f"**{nr}**")
            c[1].write(g["Hemmalag"])
            c[2].write(g["Bortalag"])
            k1.append(c[3].checkbox("1", key=f"{v}_{nr}_1"))
            c[3].caption(f"{g['Folk 1 %']:.0f}%  \n{g['Odds 1']:.2f}")
            kx.append(c[4].checkbox("X", key=f"{v}_{nr}_X"))
            c[4].caption(f"{g['Folk X %']:.0f}%  \n{g['Odds X']:.2f}")
            k2.append(c[5].checkbox("2", key=f"{v}_{nr}_2"))
            c[5].caption(f"{g['Folk 2 %']:.0f}%  \n{g['Odds 2']:.2f}")
            plats.append(st.empty())

    edited = games.copy()
    edited["1"], edited["X"], edited["2"] = k1, kx, k2

    valda = edited[["1", "X", "2"]].sum(axis=1).clip(lower=1)
    rader_plats.metric("Antal rader", int(valda.prod()))

    kryss = edited[["1", "X", "2"]].astype(float)
    e = kryss.div(kryss.sum(axis=1).replace(0, float("nan")), axis=0) * 100
    f = edited[["Folk 1 %", "Folk X %", "Folk 2 %"]].fillna(0).set_axis(["1", "X", "2"], axis=1)
    inv = (1 / edited[["Odds 1", "Odds X", "Odds 2"]]).set_axis(["1", "X", "2"], axis=1)
    op = inv.div(inv.sum(axis=1), axis=0) * 100
    w = op - f

    skrall = edited[["R", "Hemmalag", "Bortalag"]].copy()
    skrall["Skräll-index"] = (e - f).abs().sum(axis=1) / 2
    skrall["Värdebaserat skräll-index"] = ((e - f) * w).sum(axis=1)

    # (antal tecken, favoriten med, positivt värde) -> kommentar
    texter = {
        (1, True, True): "Du är mycket säkrare på favoriten än folket, och oddsmarknaden håller med dig – folket underspelar den här.",
        (1, True, False): "Du är säkrare på favoriten än folket, men oddsmarknaden tyder på att den är överspelad. Fundera på om du verkligen vill spika här.",
        (1, False, True): "Du släpper favoriten helt och oddsmarknaden stödjer dig – det här är potentiellt värde.",
        (1, False, False): "Du släpper favoriten helt, men har trots det dåligt värde. Fundera på att gardera, eller om det är värt att ha med favoriten ändå.",
        (2, True, True): "Du tar med en skräll mot folket och oddsmarknaden stödjer dig – det här är potentiellt värde.",
        (2, True, False): "Du tar med både favorit och en skräll mot folket, men har trots det dåligt värde. Fundera på om favoriten är överstreckad och kan släppas, eller om en helgardering kan hjälpa.",
        (2, False, True): "Du släpper favoriten helt och oddsmarknaden stödjer dig – det här är potentiellt värde.",
        (2, False, False): "Du släpper favoriten helt, men har trots det dåligt värde. Fundera på om det är värt att ha med favoriten ändå.",
        (3, True, True): "Du helgarderar och oddsmarknaden stödjer dig – det här är potentiellt värde.",
        (3, True, False): "Du helgarderar men har svagt värde, i denna match kan det vara smartare att spika eller halvgardera.",
    }

    for p, i in zip(plats, edited.index):
        val = skrall.loc[i, "Värdebaserat skräll-index"]
        n = int(kryss.loc[i].sum())
        if pd.isna(val) or n == 0:
            p.caption("-")
        else:
            p.caption(texter[(n, bool(kryss.loc[i, op.loc[i].idxmax()]), val >= 0)])

    st.subheader("Skräll-index")
    st.dataframe(
        skrall,
        hide_index=True,
        use_container_width=True,
        column_config={c: st.column_config.NumberColumn(format="%.1f") for c in ["Skräll-index", "Värdebaserat skräll-index"]},
    )

    _, mitt, _ = st.columns([1, 3, 1])
    if mitt.button("Skicka in din kupong", type="primary", use_container_width=True):
        if not namn.strip():
            st.error("Please enter your name before submitting.")
        elif (kryss.sum(axis=1) == 0).any():
            st.error(f"Please select at least one outcome for all {len(edited)} games.")
        else:
            speltext = [",".join(t for t, ok in zip(["1", "X", "2"], rad) if ok) for rad in edited[["1", "X", "2"]].values]
            tid = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            ny_rad = [tid, namn.strip(), "Stryktipset"] + speltext

            try:
                ws = sh.worksheet(SKRIV_FLIK)
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(SKRIV_FLIK, rows=100, cols=16)
            kol_a = ws.col_values(1)
            if len(kol_a) == 0:
                ws.update(values=[["timestamp", "player_name", "game_type"] + [f"game_{i}" for i in range(1, 14)]], range_name="A1:P1", value_input_option="USER_ENTERED")
                kol_a = ["timestamp"]
            rad_nr = len(kol_a) + 1
            ws.update(values=[ny_rad], range_name=f"A{rad_nr}:P{rad_nr}", value_input_option="USER_ENTERED")
            st.session_state["klar"] = f"Your selections have been submitted successfully! (flik: {SKRIV_FLIK}, rad {rad_nr})"
            st.session_state["v"] = v + 1
            st.rerun()

st.subheader("Historik")

values = sh.worksheet("Stats").get_all_values()
stats = pd.DataFrame(values[1:], columns=values[0])
for col in stats.columns[1:]:
    stats[col] = pd.to_numeric(stats[col].str.replace("−", "-").str.replace(",", "."))
stats = stats.drop(columns=["Omgångar", "Total ROI (kr)"], errors="ignore")
stats = stats.rename(columns={"Snitt rätt": "Snitt Antal rätt", "Max rätt": "Max Antal rätt"})

tal_kolumner = list(stats.columns[1:])
st.dataframe(
    stats.style.apply(
        lambda s: [
            "background-color: #A0E883; color: black" if x == s.max()
            else "background-color: #E28787; color: black" if x == s.min()
            else "background-color: #F4F48C; color: black"
            for x in s
        ],
        subset=tal_kolumner,
        axis=0,
    ).format("{:g}", subset=tal_kolumner),
    hide_index=True,
)

values = sh.worksheet("Stats Rounds").get_all_values()
rounds = pd.DataFrame(values[1:], columns=values[0])
rounds = rounds[rounds["Omgång"] != ""]
rounds["Omgång"] = pd.to_datetime(rounds["Omgång"])
rounds["Rätt"] = pd.to_numeric(rounds["Rätt"])

experter = ["Isak", "Ludde", "Fredrik"]

ratt = rounds.pivot_table(index="Omgång", columns="Expert", values="Rätt").reset_index()
ratt["Omgång"] = ratt["Omgång"].dt.strftime("%Y-%m-%d")
for x in experter:
    ratt["t_" + x] = ratt[x].astype("Int64").astype(str).add(" Rätt").replace("<NA> Rätt", "–")

lang = ratt.melt(id_vars="Omgång", value_vars=experter, var_name="Expert", value_name="Rätt")

nearest = alt.selection_point(fields=["Omgång"], nearest=True, on="mouseover", empty=False)

linjer = alt.Chart(lang).mark_line(point=True, strokeWidth=1.5).encode(
    x=alt.X("Omgång:O", title=None, axis=alt.Axis(labels=False, ticks=False)),
    y=alt.Y("Rätt:Q", title=None, scale=alt.Scale(domain=[0, 13])),
    color=alt.Color("Expert:N", sort=experter),
).add_params(nearest)

regel = alt.Chart(ratt).mark_rule(color="gray").encode(
    x=alt.X("Omgång:O"),
    tooltip=[alt.Tooltip("Omgång:N", title="Omgång")] + [alt.Tooltip("t_" + x + ":N", title=x) for x in experter],
).transform_filter(nearest)

st.subheader("Rätt per omgång")
st.altair_chart(linjer + regel, use_container_width=True)