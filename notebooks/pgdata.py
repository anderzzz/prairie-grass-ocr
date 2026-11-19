"""Load the reviewed Volume I dataset for exploration.

Reads output/volume1/dataset/{arcs,towers}.csv (built by `make dataset`).
No reference data is read here.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DATASET = REPO / "output" / "volume1" / "dataset"
ARCS_M = [50, 100, 200, 400, 800]
TOWER_HEIGHTS_M = [0.5, 1.0, 1.5, 2.5, 4.5, 7.5, 10.5, 13.5, 17.5]


def run_order(run: str) -> float:
    """Printed order: 35S before 35, 48S before 48."""
    n = int("".join(c for c in str(run) if c.isdigit()))
    return n + (0.0 if str(run).endswith("S") else 0.5)


def _common(df: pd.DataFrame) -> pd.DataFrame:
    df["run"] = df["run"].astype(str)
    df["run_order"] = df["run"].map(run_order)
    df["concentration_mg_m3"] = pd.to_numeric(df["concentration_mg_m3"], errors="coerce")
    for c in ("estimated", "reviewed", "flagged", "suspect"):
        df[c] = df[c].astype(str).eq("True")
    df["status"] = pd.Categorical(df["status"], ["value", "not_measurable", "missing", "unread"])
    return df


def arcs() -> pd.DataFrame:
    """One row per arc sampler cell (Table 5.2). bearing_unwrapped runs 270..450
    so that west -> north -> east is continuous."""
    df = _common(pd.read_csv(DATASET / "arcs.csv", dtype={"run": str, "token": str}, keep_default_na=False))
    df["bearing_unwrapped"] = df["bearing_deg"].where(df["bearing_deg"] >= 270, df["bearing_deg"] + 360)
    return df


def towers() -> pd.DataFrame:
    """One row per tower sampler cell (Table 5.3)."""
    return _common(pd.read_csv(DATASET / "towers.csv", dtype={"run": str, "token": str}, keep_default_na=False))


def runs_in_order(df: pd.DataFrame) -> list[str]:
    return df.drop_duplicates("run").sort_values("run_order")["run"].tolist()


# Shared plot look: three validated categorical slots (blue, orange, aqua) and a
# single-hue sequential ramp for distance. Stability regimes always get the same colour.
REGIME_COLORS = {"stable": "#2a78d6", "convective": "#eb6834", "near-neutral": "#1baf7a"}
ARC_COLORS = dict(zip(ARCS_M, ["#9ec5f4", "#6ba5ec", "#2a78d6", "#1d5aa6", "#123a6e"]))
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def style() -> None:
    """Quiet matplotlib defaults: thin marks, recessive grid, no top/right spines."""
    import matplotlib as mpl
    mpl.rcParams.update({
        "figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
        "lines.linewidth": 1.6, "lines.markersize": 5, "legend.frameon": False,
        "axes.titlelocation": "left", "axes.titlesize": 11, "axes.titleweight": "bold",
        "axes.prop_cycle": mpl.cycler(color=["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                                             "#e87ba4", "#008300", "#6250d6", "#e34948"]),
    })


# ---------------------------------------------------------------------------
# Run-level helpers for the analysis notebooks (04-07).
# Everything below reads only output/volume{1,2}/dataset/. Values are used as
# printed; any derived quantity is computed here and named as such.
# ---------------------------------------------------------------------------

VOL2 = REPO / "output" / "volume2" / "dataset"
SOURCE_HEIGHT_M = 0.46   # release height of the SO2 point source (Vol. I, ch. 2)
G = 9.81                 # m s-2
KAPPA = 0.4              # von Karman constant
GAMMA_D = 0.0098         # dry adiabatic lapse rate, K/m


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.replace("", None), errors="coerce")


def source_strength() -> pd.Series:
    """Release rate Q (g/s) per run, Table 5.1."""
    d = _read(DATASET / "source_strength.csv")
    return pd.Series(_num(d["value"]).to_numpy(), index=d["run"], name="Q_g_s")


def evaporation_correction() -> pd.DataFrame:
    """Table 5.4 factors, wide: run x arc_m. NaN where printed 'missing data'."""
    d = _read(DATASET / "evaporation_correction.csv")
    d["value"] = _num(d["value"])
    return d.pivot(index="run", columns="arc_m", values="value").rename(columns=int)


def slow_wind() -> pd.DataFrame:
    """Table 6.1, one row per release. Columns like u_source_10 (m/s),
    dir_source_10 (deg), sigma_theta_source_10 (deg), plus date and time_cst."""
    d = _read(DATASET / "slow_response_wind.csv")
    keys = d.drop_duplicates("release").set_index("release")[["date", "time_cst"]]
    v = d[~d["quantity"].str.startswith("key")].copy()
    v["value"] = _num(v["value"])
    short = {"wind_speed": "u", "wind_direction": "dir", "sigma_theta": "sigma_theta"}
    v["col"] = v["quantity"].map(short) + "_" + v["location"] + "_" + v["period_min"]
    wide = v.pivot(index="release", columns="col", values="value")
    return keys.join(wide)


def micromet(table: str = "8.1") -> pd.DataFrame:
    """Tidy Table 8.1 (or 8.2): numeric `value`, `height_m`, only status == value.
    Wind speed is converted from the printed cm/s to m/s in `value_si`."""
    d = _read(VOL2 / f"table_{table}.csv")
    d = d[d["status"] == "value"].copy()
    d["value"] = _num(d["value"])
    d["height_m"] = _num(d["height_m"])
    d["value_si"] = np.where(d["section"] == "wind_speed", d["value"] / 100.0, d["value"])
    return d


def profiles(section: str, table: str = "8.1") -> pd.DataFrame:
    """Wide profile: one row per release (8.1) or (date, cst) (8.2), one column per height.
    Release 48S has two printed rows in 8.1 (1205 and 1255); the first, the one
    nearest the Table 6.1 release time 1225 and the one with data, is kept."""
    d = micromet(table)
    d = d[d["section"] == section]
    if table == "8.1":
        first = d.groupby("release")["cst"].min()
        d = d[d["cst"] == d["release"].map(first)]
        return d.pivot_table(index="release", columns="height_m", values="value_si", aggfunc="first")
    return d.pivot_table(index=["date", "cst"], columns="height_m", values="value_si", aggfunc="first")


def arc_summary(corrected: bool = False) -> pd.DataFrame:
    """One row per (run, arc): plume statistics from the crosswind profile.

    Printed blanks ('no measurable concentration') count as 0 in the integrals,
    missing (M) cells are dropped. Distances along the arc are y = r * theta.
    - peak: highest printed value on the arc
    - cwic: crosswind-integrated concentration, sum(c * dy), mg m-2
    - centroid_deg: concentration-weighted mean bearing (0-360)
    - sigma_y_m: concentration-weighted standard deviation of y (lateral spread)
    corrected=True multiplies by the Table 5.4 evaporation factor first.
    """
    a = arcs()
    a = a[a["status"].isin(["value", "not_measurable"])].copy()
    a["c"] = a["concentration_mg_m3"].fillna(0.0)
    if corrected:
        f = evaporation_correction().stack().rename("f").reset_index()
        f.columns = ["run", "arc_m", "f"]
        a = a.merge(f, on=["run", "arc_m"], how="left")
        a["c"] = a["c"] * a["f"]
    a["dtheta"] = np.where(a["arc_m"] == 800, 1.0, 2.0)
    a["r"] = a["arc_m"].astype(float)
    a["y"] = a["r"] * np.deg2rad(a["bearing_unwrapped"])
    a["w"] = a["c"] * a["arc_m"] * np.deg2rad(a["dtheta"])   # c * dy

    def stats(g: pd.DataFrame) -> pd.Series:
        w = g["w"].to_numpy()
        tot = w.sum()
        n = int((g["c"] > 0).sum())
        if tot <= 0:
            return pd.Series({"n_posts": len(g), "n_detect": n, "peak": 0.0, "cwic": 0.0,
                              "centroid_deg": np.nan, "sigma_y_m": np.nan})
        ybar = (w * g["y"]).sum() / tot
        sig = np.sqrt((w * (g["y"] - ybar) ** 2).sum() / tot)
        cen = (ybar / g["r"].iloc[0] * 180 / np.pi) % 360
        return pd.Series({"n_posts": len(g), "n_detect": n, "peak": g["c"].max(), "cwic": tot,
                          "centroid_deg": cen, "sigma_y_m": sig})

    out = a.groupby(["run", "arc_m"])[["c", "w", "y", "r"]].apply(stats).reset_index()
    out["run_order"] = out["run"].map(run_order)
    return out.sort_values(["run_order", "arc_m"]).reset_index(drop=True)


def run_table() -> pd.DataFrame:
    """One row per run: when, how much gas, wind, stability and the plume on each arc.

    Derived columns (not printed anywhere):
    - dT_16_05: T(16 m) - T(0.5 m), degC  (positive = inversion)
    - dtheta_dz: potential temperature gradient between 0.5 and 16 m, K/m
    - Ri_b: bulk Richardson number from T and u at 0.5 and 8 m (4 m where 8 m is not
            printed) - a crude but standard stability number; < 0 convective, > 0 stable
    - wind_exp_p: power-law exponent p in u ~ z^p fitted over 0.5-8 m
    - u_star, z0: log-law fit over 0.25-2 m (neutral form, crude outside neutral)
    - regime: 'convective' (Ri_b < -0.01), 'near-neutral', 'stable' (Ri_b > 0.01)
    - u_ref: transport speed, m/s (Table 6.1 source 2 m, else Table 8.1 2 m)
    Radiation values above the solar constant are dropped (one misprint, release 16).
    """
    q = source_strength()
    w = slow_wind()
    T = profiles("temperature")
    U = profiles("wind_speed")
    rad = micromet()
    rad = rad[rad["section"] == "radiation"]
    # physical bound: nothing at the surface exceeds the solar constant, ~0.033 cal cm-2 s-1.
    # Catches release 16 insolation printed '0183' (no decimal point; quality printed_inconsistent).
    rad = rad[rad["value"].abs() < 0.033].drop_duplicates(["release", "quantity"]) \
        .pivot(index="release", columns="quantity", values="value")

    met = pd.DataFrame(index=T.index)
    met["T_1m"] = T.get(1.0)
    met["dT_16_05"] = T.get(16.0) - T.get(0.5)
    met["dtheta_dz"] = (met["dT_16_05"] + GAMMA_D * 15.5) / 15.5
    met["u_1m"] = U.get(1.0)
    met["u_2m"] = U.get(2.0)
    met["u_8m"] = U.get(8.0)

    # bulk Richardson number, 0.5 -> 8 m for both T and u; 0.5 -> 4 m where 8 m is not printed
    def ri(top: float) -> pd.Series:
        dz = top - 0.5
        th = T.get(top) - T.get(0.5) + GAMMA_D * dz
        du = U.get(top) - U.get(0.5)
        return (G / (met["T_1m"] + 273.15)) * th * dz / du.clip(lower=0.05) ** 2
    met["Ri_b"] = ri(8.0).fillna(ri(4.0))

    def fit(row: pd.Series, zs, log_x=True):
        z = np.array([h for h in zs if h in row.index and pd.notna(row[h]) and row[h] > 0])
        if len(z) < 3:
            return np.nan, np.nan
        u = row[z].to_numpy(dtype=float)
        x = np.log(z)
        y = np.log(u) if not log_x else u
        b, a = np.polyfit(x, y, 1)
        return b, a

    p, us, z0 = [], [], []
    for r, row in U.iterrows():
        b, _ = fit(row, [0.5, 1.0, 2.0, 4.0, 8.0], log_x=False)
        p.append(b)
        slope, icpt = fit(row, [0.25, 0.5, 1.0, 2.0], log_x=True)
        us.append(slope * KAPPA)
        z0.append(np.exp(-icpt / slope) if slope and slope > 0 else np.nan)
    met["wind_exp_p"] = p
    met["u_star"] = us
    met["z0_m"] = z0
    met = met.join(rad.add_prefix("rad_"))

    reg = pd.cut(met["Ri_b"], [-np.inf, -0.01, 0.01, np.inf],
                 labels=["convective", "near-neutral", "stable"])
    met["regime"] = reg

    s = arc_summary()
    wide = s.pivot(index="run", columns="arc_m", values=["peak", "cwic", "sigma_y_m", "centroid_deg"])
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]

    out = pd.DataFrame(index=q.index)
    out = out.join(q).join(w).join(met).join(wide)
    out.index.name = "run"
    # transport speed for normalising concentrations: Table 6.1 2 m speed at the source
    # over the release, else the Table 8.1 2 m cup
    out["u_ref"] = out["u_source_10"].fillna(out["u_2m"])
    out["run_order"] = out.index.map(run_order)
    out["hour"] = _num(out["time_cst"]) // 100 + (_num(out["time_cst"]) % 100) / 60
    out["day_night"] = np.where((out["hour"] > 7) & (out["hour"] < 18), "day", "night")
    return out.sort_values("run_order")
