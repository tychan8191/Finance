##############################################################################
# SEC EDGAR DATA PULL
# Project: EauRouge_1 Regression Model | Raidillon Capital
# Author: Ty Chan
# Description: Pulls CAG quarterly financials from SEC EDGAR XBRL API and
#              computes gross margin. Outputs a clean quarterly DataFrame
#              ready for the main regression file.
##############################################################################


##############################################################################
# IMPORTS
##############################################################################

import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
from datetime import datetime


##############################################################################
# CONFIG
# No API key needed for SEC EDGAR — just a descriptive User-Agent header.
# The SEC requires this so they can identify who is making requests.
# Format: "First Last email@domain.com"
# Change the values below to your own name and email before running.
##############################################################################

USER_AGENT = "Ty Chan chan.ty8191@gmail.com"

# CAG (Conagra Brands) CIK — zero-padded to 10 digits as SEC requires
# To look up a different company: https://www.sec.gov/cgi-bin/browse-edgar
CAG_CIK = "0000023217"

# Base URL for the XBRL company facts endpoint
EDGAR_BASE_URL = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CAG_CIK}.json"

# Fiscal year start — CAG's fiscal year begins in June
# Used to help align fiscal quarters to calendar quarters later
FISCAL_YEAR_START_MONTH = 6

# Date range filter — only keep filings from this date onward
START_DATE = "2015-01-01"

# Global plot style
sns.set_theme(style="whitegrid", palette="muted")


##############################################################################
# XBRL CONCEPTS TO PULL
# These are the three standardized accounting tags we need.
# Key: what we want to call the column
# Value: the XBRL concept name as it appears in the SEC JSON
##############################################################################

CONCEPTS = {
    "revenue": "Revenues",
    "cogs":    "CostOfGoodsAndServicesSold",
}

# Fallback tags to try if the primary ones return no data.
# GrossProfit is intentionally excluded — CAG rarely reports it in 10-Q filings.
# We compute it directly as revenue - cogs instead (see build_financials).
CONCEPT_FALLBACKS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "cogs":    ["CostOfRevenue", "CostOfGoodsSold"],
}


##############################################################################
# FETCH RAW COMPANY FACTS
# Pulls the entire XBRL JSON for the company in one call.
# This is a large payload (~5-10MB) but only needs to be fetched once.
##############################################################################

def fetch_company_facts(cik, user_agent):
    """
    Fetches the full XBRL company facts JSON from SEC EDGAR.

    Parameters:
        cik        (str): Zero-padded 10-digit CIK e.g. '0000023217'
        user_agent (str): Your name and email for the SEC User-Agent header

    Returns:
        dict: Raw JSON response from EDGAR
    """

    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

    headers = {"User-Agent": user_agent}

    print(f"Fetching EDGAR company facts for CIK {cik}...")

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        raise ConnectionError(f"EDGAR request failed: HTTP {response.status_code}")

    data = response.json()

    company_name = data.get("entityName", "Unknown")
    print(f"  Retrieved: {company_name}")

    return data


##############################################################################
# EXTRACT A SINGLE CONCEPT
# Navigates the nested JSON to pull quarterly values for one accounting concept.
# Filters to 10-Q filings only (quarterly, not annual).
##############################################################################

def extract_concept(facts_json, concept_name, col_name, start_date):
    """
    Extracts quarterly observations for a single XBRL concept.

    Parameters:
        facts_json   (dict): Raw EDGAR JSON from fetch_company_facts()
        concept_name (str):  XBRL tag e.g. 'Revenues'
        col_name     (str):  Column name for output DataFrame
        start_date   (str):  Filter out observations before this date 'YYYY-MM-DD'

    Returns:
        pd.DataFrame with columns: ['end_date', 'filed', 'form', 'fiscal_period', col_name]
        Returns empty DataFrame if concept not found.
    """

    try:
        # Navigate: facts > us-gaap > {concept} > units > USD > [list of observations]
        observations = facts_json["facts"]["us-gaap"][concept_name]["units"]["USD"]
    except KeyError:
        print(f"  WARNING: Concept '{concept_name}' not found in EDGAR data.")
        return pd.DataFrame()

    df = pd.DataFrame(observations)

    # Keep only quarterly 10-Q filings — exclude 10-K annual filings
    # 'form' column indicates the filing type
    df = df[df["form"] == "10-Q"].copy()

    # Keep only the columns we need
    # 'end' = period end date, 'filed' = date filed with SEC
    # 'fp' = fiscal period label e.g. Q1, Q2, Q3
    # 'fy' = fiscal year
    keep_cols = [c for c in ["end", "filed", "fp", "fy", "val"] if c in df.columns]
    df = df[keep_cols].copy()

    df.rename(columns={
        "end":   "end_date",
        "filed": "filed_date",
        "fp":    "fiscal_period",
        "fy":    "fiscal_year",
        "val":   col_name,
    }, inplace=True)

    # Convert dates
    df["end_date"]   = pd.to_datetime(df["end_date"])
    df["filed_date"] = pd.to_datetime(df["filed_date"])

    # Filter to start date
    df = df[df["end_date"] >= start_date].copy()

    # Drop duplicates — same period can be restated; keep most recently filed
    df.sort_values("filed_date", inplace=True)
    df.drop_duplicates(subset=["end_date"], keep="last", inplace=True)

    df.sort_values("end_date", inplace=True)
    df.reset_index(drop=True, inplace=True)

    print(f"  Extracted '{concept_name}' ({col_name}): {len(df)} quarterly observations")

    return df


##############################################################################
# EXTRACT WITH FALLBACK
# Tries the primary concept tag first, then falls back to alternates
# if the primary returns no data — handles XBRL naming inconsistencies.
##############################################################################

def extract_with_fallback(facts_json, col_name, primary_concept, fallback_concepts, start_date):
    """
    Attempts to extract a concept using primary tag, then fallbacks if needed.
    """

    df = extract_concept(facts_json, primary_concept, col_name, start_date)

    if df.empty:
        for fallback in fallback_concepts:
            print(f"  Trying fallback: {fallback}")
            df = extract_concept(facts_json, fallback, col_name, start_date)
            if not df.empty:
                break

    if df.empty:
        print(f"  ERROR: Could not find data for '{col_name}' under any known tag.")

    return df


##############################################################################
# BUILD FINANCIALS DATAFRAME
# Merges revenue, COGS, and gross profit into a single quarterly DataFrame
# and computes gross margin.
##############################################################################

def build_financials(facts_json, concepts, fallbacks, start_date):
    """
    Extracts all three financial concepts and merges them on end_date.
    Computes gross_margin_q = (revenue - cogs) / revenue.

    Returns:
        pd.DataFrame indexed by end_date with financial columns + gross_margin_q
    """

    print("\nExtracting financial concepts...\n")

    dfs = {}

    for col_name, concept in concepts.items():
        fb = fallbacks.get(col_name, [])
        df = extract_with_fallback(facts_json, col_name, concept, fb, start_date)

        if not df.empty:
            # Keep only end_date + value for merging
            dfs[col_name] = df[["end_date", "fiscal_period", "fiscal_year", col_name]]

    # Merge all three on end_date
    merged = None

    for col_name, df in dfs.items():
        if merged is None:
            merged = df
        else:
            merged = pd.merge(
                merged,
                df[["end_date", col_name]],
                on="end_date",
                how="outer"
            )

    if merged is None or merged.empty:
        raise ValueError("No financial data could be extracted. Check CIK and concept tags.")

    merged.sort_values("end_date", inplace=True)
    merged.reset_index(drop=True, inplace=True)

    # Compute gross profit and gross margin directly from revenue - cogs.
    # CAG does not consistently report GrossProfit in 10-Q filings,
    # so we derive it ourselves rather than pulling it as a separate concept.
    if "revenue" in merged.columns and "cogs" in merged.columns:
        merged["gross_profit"]   = merged["revenue"] - merged["cogs"]
        merged["gross_margin_q"] = merged["gross_profit"] / merged["revenue"]
    else:
        print("WARNING: Could not compute gross_margin_q — missing revenue or cogs.")

    # Express as percentage
    merged["gross_margin_pct"] = merged["gross_margin_q"] * 100

    print(f"\nFinancials DataFrame built. Shape: {merged.shape}")
    print(f"Date range: {merged['end_date'].min().date()} to {merged['end_date'].max().date()}")

    return merged


##############################################################################
# CALENDAR QUARTER ALIGNMENT
# CAG's fiscal year starts in June, so fiscal quarters don't match calendar
# quarters. This adds a calendar_quarter column so we can merge with FRED data
# which runs on calendar quarters.
##############################################################################

def add_calendar_quarter(df):
    """
    Adds calendar year and quarter columns based on the period end date.
    This is what we use to align with FRED macro data later.

    CAG fiscal quarter mapping (approximate):
        FQ1: June - August    → Calendar Q3
        FQ2: September - Nov  → Calendar Q4
        FQ3: December - Feb   → Calendar Q1 (next year)
        FQ4: March - May      → Calendar Q2
    """

    df = df.copy()
    df["calendar_year"]    = df["end_date"].dt.year
    df["calendar_quarter"] = df["end_date"].dt.quarter
    df["period_label"]     = (
        df["calendar_year"].astype(str) + " Q" +
        df["calendar_quarter"].astype(str)
    )

    return df


##############################################################################
# FEATURE ENGINEERING
# Adds QoQ and YoY changes in gross margin — used as alternate dependent
# variables in the regression robustness checks.
##############################################################################

def build_margin_features(df):
    """
    Computes QoQ and YoY changes in gross margin percentage.
    """

    df = df.copy()

    df["gross_margin_qoq"] = df["gross_margin_pct"].diff(periods=1)
    df["gross_margin_yoy"] = df["gross_margin_pct"].diff(periods=4)

    print("\nMargin features built.")
    print("Columns:", list(df.columns))

    return df


##############################################################################
# MISSINGNESS CHECK
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
# 1. Gross margin level over time
# 2. Gross margin QoQ and YoY changes combined
# 3. Missingness heatmap
# 4. Distribution of gross margin level + changes
##############################################################################

def plot_gross_margin(df):
    """
    Time series of gross margin percentage with fiscal quarter labels.
    """

    fig, ax = plt.subplots(figsize=(10, 4))

    ax.plot(df["end_date"], df["gross_margin_pct"], linewidth=1.5, color="#2563EB", marker="o", markersize=3)
    ax.axhline(df["gross_margin_pct"].mean(), color="grey", linewidth=0.8, linestyle="--", label="Mean")

    # Shade post-2021 regime
    post_2021 = pd.Timestamp("2021-01-01")
    ax.axvspan(post_2021, df["end_date"].max(), alpha=0.07, color="#DC2626", label="Post-2021")

    ax.set_title("CAG Gross Margin % — Quarterly", fontsize=12, fontweight="bold")
    ax.set_ylabel("Gross Margin %", fontsize=9)
    ax.set_xlabel("")
    ax.legend(fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_major_locator(mdates.YearLocator())

    plt.tight_layout()
    plt.savefig("outputs/plot_cag_gross_margin.png", dpi=120, bbox_inches="tight")
    print("Built: plot_gross_margin")


def plot_margin_changes(df):
    """
    Combined chart: QoQ change (top) and YoY change (bottom) in gross margin.
    """

    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    fig.suptitle("CAG Gross Margin — QoQ and YoY Changes", fontsize=12, fontweight="bold")

    for ax, col, label, color in zip(
        axes,
        ["gross_margin_qoq", "gross_margin_yoy"],
        ["Quarter-over-Quarter Change (pp)", "Year-over-Year Change (pp)"],
        ["#7C3AED", "#DC2626"]
    ):
        ax.bar(df["end_date"], df[col], width=60, color=color, alpha=0.7)
        ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
        ax.set_title(label, fontsize=10)
        ax.set_ylabel("pp change", fontsize=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.xaxis.set_major_locator(mdates.YearLocator())

    plt.tight_layout()
    plt.savefig("outputs/plot_cag_margin_changes.png", dpi=120, bbox_inches="tight")
    print("Built: plot_margin_changes")


def plot_missingness_heatmap(df):
    """
    Heatmap showing where nulls exist across the DataFrame.
    """

    fig, ax = plt.subplots(figsize=(10, 3))

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    missing_mask = df[numeric_cols].isnull().T

    sns.heatmap(missing_mask, cmap="Reds", cbar=False, ax=ax,
                linewidths=0.3, linecolor="lightgrey")

    ax.set_title("Missingness Heatmap — Red = Missing", fontsize=11, fontweight="bold")
    ax.set_xlabel("Quarter Index", fontsize=8)

    plt.tight_layout()
    plt.savefig("outputs/plot_cag_missingness.png", dpi=120, bbox_inches="tight")
    print("Built: plot_missingness_heatmap")


def plot_margin_distributions(df):
    """
    Distribution plots for gross margin level, QoQ, and YoY changes.
    """

    cols   = ["gross_margin_pct", "gross_margin_qoq", "gross_margin_yoy"]
    titles = ["Gross Margin % — Level", "QoQ Change (pp)", "YoY Change (pp)"]
    colors = ["#2563EB", "#7C3AED", "#DC2626"]

    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    fig.suptitle("CAG Gross Margin — Distributions", fontsize=12, fontweight="bold")

    for ax, col, title, color in zip(axes, cols, titles, colors):
        sns.histplot(df[col].dropna(), kde=True, ax=ax, color=color)
        ax.axvline(df[col].mean(), color="black", linewidth=0.8, linestyle="--", label="Mean")
        ax.set_title(title, fontsize=9)
        ax.set_xlabel("")
        ax.legend(fontsize=7)

    plt.tight_layout()
    plt.savefig("outputs/plot_cag_distributions.png", dpi=120, bbox_inches="tight")
    print("Built: plot_margin_distributions")


def run_all_plots(df):
    """
    Runs all visualization functions then shows all at once.
    """
    print("\nGenerating visualizations...\n")
    plot_gross_margin(df)
    plot_margin_changes(df)
    plot_missingness_heatmap(df)
    plot_margin_distributions(df)
    plt.show()
    print("\nAll plots generated and saved.")


##############################################################################
# MAIN — runs everything top to bottom
##############################################################################

def main():

    # --- 1. Fetch full EDGAR company facts JSON ---
    facts = fetch_company_facts(CAG_CIK, USER_AGENT)

    # --- 2. Extract and merge financial concepts ---
    df = build_financials(facts, CONCEPTS, CONCEPT_FALLBACKS, START_DATE)

    # --- 3. Add calendar quarter alignment ---
    df = add_calendar_quarter(df)

    # --- 4. Build margin change features ---
    df = build_margin_features(df)

    # --- 5. Missingness check ---
    missingness_summary(df)

    # --- 6. Preview ---
    print("\n--- FINAL DATAFRAME PREVIEW (last 8 quarters) ---")
    print(df.tail(8).to_string())

    # --- 7. Export to CSV for use in main regression notebook ---
    import os
    os.makedirs("outputs", exist_ok=True)
    output_path = "outputs/cag_financials_quarterly.csv"
    df.to_csv(output_path, index=False)
    print(f"\nSaved to: {output_path}")

    return df


##############################################################################
# ENTRY POINT
##############################################################################

if __name__ == "__main__":
    df = main()
    run_all_plots(df)
