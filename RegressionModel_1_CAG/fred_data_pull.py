##############################################################################
# FRED DATA PULL
# Project: EauRouge_1 Regression Model | Raidillon Capital
# Author: Ty Chan
# Description: Pulls macro/CPI control variables from FRED API and outputs
#              a clean quarterly DataFrame ready for the main regression file.
##############################################################################


##############################################################################
# IMPORTS
##############################################################################

import requests
import pandas as pd
import time
import os
from datetime import datetime
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns


##############################################################################
# CONFIG
# API key is loaded from a .env file in the same directory as this script.
# Create a file called .env and add this line to it:
#     FRED_API_KEY=your_actual_key_here
# Get a free key at: https://fred.stlouisfed.org/docs/api/api_key.html
# NEVER hardcode your key here and NEVER commit your .env to Git.
##############################################################################

load_dotenv()
FRED_API_KEY = os.getenv("FRED_API_KEY")

if not FRED_API_KEY:
    raise ValueError("FRED_API_KEY not found. Make sure your .env file exists and contains FRED_API_KEY=your_key")

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# Date range — go back to 2015 to give us room for YoY calcs starting 2016
START_DATE = "2015-01-01"
END_DATE   = datetime.today().strftime("%Y-%m-%d")

# Global plot style
sns.set_theme(style="whitegrid", palette="muted")


##############################################################################
# SERIES DEFINITIONS
# Each entry: "column_name": "FRED series ID"
# These are the control variables specified in the model brief
##############################################################################

SERIES = {
    "cpi_food_home":   "CUSR0000SAF11",  # CPI: Food at Home (monthly)
    "umich_sentiment": "UMCSENT",         # U of Michigan Consumer Sentiment (monthly)
    "real_dpi":        "DSPIC96",         # Real Disposable Personal Income (monthly)
    "unemployment":    "UNRATE",          # Unemployment Rate (monthly)
    "ppi_frozen":      "PCU311412311412", # PPI: Frozen Specialty Food Manufacturing (monthly)
    "ppi_snack":       "PCU3119131191",   # PPI: Snack Food Manufacturing (monthly)
    "ppi_grocery":     "WPU057",          # PPI: Grocery & Related Products (monthly)
}


##############################################################################
# FETCH FUNCTION
# Hits the FRED observations endpoint for a single series.
# Returns a raw DataFrame with date + value columns.
##############################################################################

def fetch_fred_series(series_id, series_name, api_key, start, end):
    """
    Pulls a single FRED series and returns a cleaned DataFrame.

    Parameters:
        series_id   (str): FRED series identifier e.g. 'UNRATE'
        series_name (str): What we want to call the column in our output
        api_key     (str): Your FRED API key
        start       (str): Start date 'YYYY-MM-DD'
        end         (str): End date   'YYYY-MM-DD'

    Returns:
        pd.DataFrame with columns: ['date', series_name]
    """

    params = {
        "series_id":         series_id,
        "api_key":           api_key,
        "file_type":         "json",
        "observation_start": start,
        "observation_end":   end,
    }

    response = requests.get(FRED_BASE_URL, params=params)

    # Basic error handling — FRED returns 200 even on bad keys, so check content
    if response.status_code != 200:
        raise ConnectionError(f"FRED API call failed for {series_id}: HTTP {response.status_code}")

    data = response.json()

    if "observations" not in data:
        raise ValueError(f"No observations returned for {series_id}. Check your API key and series ID.")

    df = pd.DataFrame(data["observations"])[["date", "value"]]

    # FRED uses "." for missing values — replace with NaN
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df.rename(columns={"value": series_name}, inplace=True)
    df["date"] = pd.to_datetime(df["date"])

    print(f"  Pulled {series_id} ({series_name}): {len(df)} observations")

    return df


##############################################################################
# PULL ALL SERIES
# Loops through SERIES dict, fetches each one, merges into a single DataFrame
##############################################################################

def pull_all_series(series_dict, api_key, start, end):
    """
    Iterates through all series, fetches each, and outer-merges on date.

    Returns:
        pd.DataFrame — wide format, one row per date, one column per series
    """

    print("\nPulling FRED series...\n")

    merged = None

    for name, sid in series_dict.items():
        df = fetch_fred_series(sid, name, api_key, start, end)

        if merged is None:
            merged = df
        else:
            merged = pd.merge(merged, df, on="date", how="outer")

        # Be polite to the API — small pause between calls
        time.sleep(0.3)

    merged.sort_values("date", inplace=True)
    merged.reset_index(drop=True, inplace=True)

    print(f"\nAll series pulled. Raw DataFrame shape: {merged.shape}")

    return merged


##############################################################################
# QUARTERLY CONVERSION
# All FRED series here are monthly. We need quarterly to match CAG financials.
# Convention: take the LAST observation in each calendar quarter (end-of-quarter)
# This matches how we'll align SEC filing dates later.
##############################################################################

def to_quarterly(df):
    """
    Resamples a monthly DataFrame to quarterly frequency.
    Uses last observation in each quarter (end-of-quarter convention).

    Returns:
        pd.DataFrame indexed by quarter-end date
    """

    df = df.copy()
    df.set_index("date", inplace=True)

    df_q = df.resample("QE").last()

    print(f"\nConverted to quarterly. Shape: {df_q.shape}")
    print(f"Date range: {df_q.index.min().date()} to {df_q.index.max().date()}")

    return df_q


##############################################################################
# FEATURE ENGINEERING
# Build the YoY % change versions of each series — these are what the
# regression models actually use as control variables per the brief.
##############################################################################

def build_yoy_features(df_q):
    """
    Computes year-over-year % change for each series.
    Adds new columns with suffix '_yoy'.

    Returns:
        pd.DataFrame with original levels + YoY columns appended
    """

    df = df_q.copy()

    for col in SERIES.keys():
        if col in df.columns:
            df[f"{col}_yoy"] = df[col].pct_change(periods=4, fill_method=None) * 100

    print("\nYoY features built.")
    print("Columns:", list(df.columns))

    return df


##############################################################################
# MISSINGNESS CHECK
# Quick summary of where we have gaps — important for the missingness
# heatmap required in the output spec.
##############################################################################

def missingness_summary(df):
    """
    Prints a simple missingness table showing null counts per column.
    """

    print("\n--- MISSINGNESS SUMMARY ---")
    missing = df.isnull().sum()
    pct     = (df.isnull().mean() * 100).round(2)
    summary = pd.DataFrame({"null_count": missing, "pct_missing": pct})
    print(summary.to_string())
    print("---------------------------\n")

    return summary


##############################################################################
# VISUALIZATION
# Generates 5 sets of charts for exploratory review:
#   1. Time series line charts — levels for all four series
#   2. Time series line charts — YoY % change for all four series
#   3. Missingness heatmap
#   4. Correlation matrix
#   5. Distribution / histogram plots for all series + YoY versions
##############################################################################

def plot_levels_and_yoy(df):
    """
    Combined chart: for each series, shows the raw level (blue, left y-axis)
    and YoY % change (red dashed, right y-axis) on the same subplot.
    One row per series, stacked vertically.
    """

    series_list = [c for c in SERIES.keys() if c in df.columns and f"{c}_yoy" in df.columns]
    n = len(series_list)

    fig, axes = plt.subplots(n, 1, figsize=(10, 3 * n), sharex=True)
    fig.suptitle("FRED Series — Level vs YoY % Change (Quarterly)", fontsize=12, fontweight="bold", y=1.01)

    labels = {
        "cpi_food_home":   "CPI Food at Home",
        "umich_sentiment": "Consumer Sentiment",
        "real_dpi":        "Real Disposable Income",
        "unemployment":    "Unemployment Rate",
        "ppi_frozen":      "PPI Frozen Specialty Food",
        "ppi_snack":       "PPI Snack Food",
        "ppi_grocery":     "PPI Grocery & Related Products",
    }

    for ax, col in zip(axes, series_list):
        yoy_col = f"{col}_yoy"

        # Left axis — level in blue
        ax.plot(df.index, df[col], linewidth=1.5, color="#2563EB", label="Level")
        ax.set_ylabel("Level", fontsize=8, color="#2563EB")
        ax.tick_params(axis="y", labelcolor="#2563EB", labelsize=7)

        # Right axis — YoY % in red dashed
        ax2 = ax.twinx()
        ax2.plot(df.index, df[yoy_col], linewidth=1.2, color="#DC2626", linestyle="--", label="YoY %")
        ax2.axhline(0, color="#DC2626", linewidth=0.5, linestyle=":")
        ax2.set_ylabel("YoY %", fontsize=8, color="#DC2626")
        ax2.tick_params(axis="y", labelcolor="#DC2626", labelsize=7)

        ax.set_title(labels.get(col, col), fontsize=10)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.xaxis.set_major_locator(mdates.YearLocator())

        # Combined legend
        lines_1, labels_1 = ax.get_legend_handles_labels()
        lines_2, labels_2 = ax2.get_legend_handles_labels()
        ax.legend(lines_1 + lines_2, labels_1 + labels_2, fontsize=7, loc="upper left")

    plt.tight_layout()
    plt.savefig("outputs/plot_levels_yoy.png", dpi=120, bbox_inches="tight")
    print("Built: plot_levels_and_yoy")


def plot_missingness(df):
    """
    Heatmap showing where nulls exist across the DataFrame.
    White = data present, red = missing.
    """

    fig, ax = plt.subplots(figsize=(10, 3))

    missing_mask = df.isnull().T

    sns.heatmap(
        missing_mask,
        cmap="Reds",
        cbar=False,
        ax=ax,
        linewidths=0.3,
        linecolor="lightgrey"
    )

    ax.set_title("Missingness Heatmap — Red = Missing", fontsize=11, fontweight="bold")
    ax.set_xlabel("Quarter", fontsize=8)
    ax.set_ylabel("Series", fontsize=8)

    xticks = range(0, len(df), 4)
    ax.set_xticks(list(xticks))
    ax.set_xticklabels(
        [str(df.index[i].year) + " Q" + str(df.index[i].quarter) for i in xticks],
        rotation=45, ha="right", fontsize=7
    )

    plt.tight_layout()
    plt.savefig("outputs/plot_missingness.png", dpi=120, bbox_inches="tight")
    print("Built: plot_missingness")


def plot_correlation(df):
    """
    Correlation matrix heatmap across all level + YoY columns.
    Annotated with correlation coefficients.
    """

    numeric_df = df.select_dtypes(include="number").dropna()
    corr = numeric_df.corr()

    fig, ax = plt.subplots(figsize=(9, 7))

    sns.heatmap(
        corr,
        annot=True,
        fmt=".2f",
        cmap="coolwarm",
        center=0,
        linewidths=0.5,
        ax=ax,
        annot_kws={"size": 8}
    )

    ax.set_title("Correlation Matrix — FRED Macro Series", fontsize=11, fontweight="bold")
    plt.tight_layout()
    plt.savefig("outputs/plot_correlation.png", dpi=120, bbox_inches="tight")
    print("Built: plot_correlation")


def plot_distributions(df):
    """
    Histogram + KDE distribution plots for all level and YoY series.
    Left column = level, right column = YoY version.
    """

    series_pairs = [
        (col, f"{col}_yoy")
        for col in SERIES.keys()
        if col in df.columns and f"{col}_yoy" in df.columns
    ]

    n = len(series_pairs)
    fig, axes = plt.subplots(n, 2, figsize=(10, 3 * n))
    fig.suptitle("Distributions — Levels vs YoY % Change", fontsize=12, fontweight="bold", y=1.01)

    for i, (level_col, yoy_col) in enumerate(series_pairs):

        sns.histplot(df[level_col].dropna(), kde=True, ax=axes[i][0], color="#2563EB")
        axes[i][0].set_title(f"{level_col} — Level", fontsize=9)
        axes[i][0].set_xlabel("")

        sns.histplot(df[yoy_col].dropna(), kde=True, ax=axes[i][1], color="#DC2626")
        axes[i][1].set_title(f"{yoy_col} — YoY %", fontsize=9)
        axes[i][1].set_xlabel("")
        axes[i][1].axvline(0, color="black", linewidth=0.8, linestyle="--")

    plt.tight_layout()
    plt.savefig("outputs/plot_distributions.png", dpi=120, bbox_inches="tight")
    print("Built: plot_distributions")


def run_all_plots(df):
    """
    Builds all figures, then calls plt.show() once at the end.
    In Jupyter, charts render inline automatically without needing show().
    In terminal, this will open all windows together.
    """
    print("\nGenerating visualizations...\n")
    plot_levels_and_yoy(df)
    plot_missingness(df)
    plot_correlation(df)
    plot_distributions(df)
    plt.show()
    print("\nAll plots generated and saved.")


##############################################################################
# MAIN — runs everything top to bottom
##############################################################################

def main():

    # --- 1. Pull raw monthly data from FRED ---
    df_raw = pull_all_series(SERIES, FRED_API_KEY, START_DATE, END_DATE)

    # --- 2. Convert to quarterly (end-of-quarter) ---
    df_q = to_quarterly(df_raw)

    # --- 3. Build YoY features ---
    df_final = build_yoy_features(df_q)

    # --- 4. Missingness check ---
    missingness_summary(df_final)

    # --- 5. Preview ---
    print("\n--- FINAL DATAFRAME PREVIEW (last 8 quarters) ---")
    print(df_final.tail(8).to_string())

    # --- 6. Export to CSV for use in main regression notebook ---
    import os
    os.makedirs("outputs", exist_ok=True)
    output_path = "outputs/fred_macro_quarterly.csv"
    df_final.to_csv(output_path)
    print(f"\nSaved to: {output_path}")

    return df_final


##############################################################################
# ENTRY POINT
##############################################################################

if __name__ == "__main__":
    df = main()
    run_all_plots(df)