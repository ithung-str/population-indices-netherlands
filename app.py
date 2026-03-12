import streamlit as st
import pandas as pd
import altair as alt
import cbsodata

st.set_page_config(page_title="Population Indices - Dutch Municipalities", layout="wide")
st.title("Population Indices for Dutch Municipalities")


@st.cache_data(ttl=86400)
def load_population_data():
    """Fetch municipality population data from CBS (table 03759ned)."""
    data = cbsodata.get_data(
        "03759ned",
        filters=(
            "Perioden eq '2025JJ00'"
            " and Geslacht eq 'T001038'"
            " and Leeftijd eq '10000'"
            " and BurgerlijkeStaat eq 'T001019'"
            " and substringof('GM',RegioS)"
        ),
        select=["RegioS", "BevolkingOp1Januari_1"],
    )
    # Filter out defunct municipalities (no population value)
    records = [r for r in data if r["BevolkingOp1Januari_1"] is not None]
    df = pd.DataFrame(records)
    df.columns = ["Municipality", "Population"]
    df["Municipality"] = df["Municipality"].str.strip()
    df = df.sort_values("Municipality").reset_index(drop=True)
    return df


df = load_population_data()

# Compute indices
mean_pop = df["Population"].mean()
median_pop = df["Population"].median()

df["Index vs Mean"] = (df["Population"] / mean_pop).round(2)
df["Index vs Median"] = (df["Population"] / median_pop).round(2)

# Summary metrics
col1, col2, col3, col4 = st.columns(4)
col1.metric("Municipalities", len(df))
col2.metric("Mean Population", f"{mean_pop:,.0f}")
col3.metric("Median Population", f"{median_pop:,.0f}")
col4.metric("Total Population", f"{df['Population'].sum():,.0f}")

st.markdown("---")

# Search / filter
search = st.text_input("Search municipality", placeholder="e.g. Amsterdam")
filtered = df[df["Municipality"].str.contains(search, case=False, na=False)] if search else df

st.markdown(
    "**Index vs Mean**: municipality population / mean population. "
    "**Index vs Median**: municipality population / median population. "
    "A value of 1.0 = equal to the reference."
)

# Display table
st.dataframe(
    filtered.style.format({"Population": "{:,.0f}", "Index vs Mean": "{:.2f}", "Index vs Median": "{:.2f}"}),
    use_container_width=True,
    height=600,
)

# Distribution chart
st.subheader("Population Distribution")
sort_col1, sort_col2 = st.columns(2)
sort_by = sort_col1.selectbox("Sort by", ["Population", "Index vs Mean", "Index vs Median", "Municipality"])
sort_order = sort_col2.selectbox("Order", ["Descending", "Ascending"])
ascending = sort_order == "Ascending"

if sort_by == "Municipality":
    sorted_df = df.sort_values("Municipality", ascending=ascending)
else:
    sorted_df = df.sort_values(sort_by, ascending=ascending)

municipality_order = sorted_df["Municipality"].tolist()
chart = (
    alt.Chart(sorted_df)
    .mark_bar()
    .encode(
        x=alt.X("Municipality:N", sort=municipality_order, axis=alt.Axis(labels=False)),
        y=alt.Y("Population:Q"),
        tooltip=["Municipality", "Population", "Index vs Mean", "Index vs Median"],
    )
    .properties(height=400)
)
st.altair_chart(chart, use_container_width=True)

# Range explorer
st.markdown("---")
st.subheader("Population Range Explorer")

ranked = df.sort_values("Population", ascending=False).reset_index(drop=True)
ranked.index += 1  # 1-based rank
total_pop = df["Population"].sum()
n = len(ranked)

rank_range = st.slider(
    "Select rank range (1 = largest municipality)",
    min_value=1,
    max_value=n,
    value=(1, 10),
)

selected = ranked.loc[rank_range[0]:rank_range[1]]
selected_pop = selected["Population"].sum()
selected_pct = selected_pop / total_pop * 100

mc1, mc2, mc3 = st.columns(3)
mc1.metric("Municipalities selected", len(selected))
mc2.metric("Combined population", f"{selected_pop:,.0f}")
mc3.metric("Share of total", f"{selected_pct:.1f}%")

st.dataframe(
    selected[["Municipality", "Population", "Index vs Mean", "Index vs Median"]]
    .style.format({"Population": "{:,.0f}", "Index vs Mean": "{:.2f}", "Index vs Median": "{:.2f}"}),
    use_container_width=True,
)

# Population bins
st.markdown("---")
st.subheader("Population Classification")

BIN_EDGES = [0, 10_000, 25_000, 50_000, 100_000, 200_000, 500_000, 1_000_000, float("inf")]
BIN_LABELS = [
    "< 10k",
    "10k – 25k",
    "25k – 50k",
    "50k – 100k",
    "100k – 200k",
    "200k – 500k",
    "500k – 1M",
    "1M+",
]

df["Category"] = pd.cut(df["Population"], bins=BIN_EDGES, labels=BIN_LABELS, right=False)

bin_summary = (
    df.groupby("Category", observed=False)
    .agg(
        Municipalities=("Municipality", "count"),
        Total_Population=("Population", "sum"),
        Mean_Population=("Population", "mean"),
    )
    .reset_index()
)
bin_summary["Share of Total"] = (bin_summary["Total_Population"] / total_pop * 100).round(1)
bin_summary["Mean_Population"] = bin_summary["Mean_Population"].round(0)

st.dataframe(
    bin_summary.style.format({
        "Total_Population": "{:,.0f}",
        "Mean_Population": "{:,.0f}",
        "Share of Total": "{:.1f}%",
    }),
    use_container_width=True,
)

# Bin charts side by side
bin_col1, bin_col2 = st.columns(2)

with bin_col1:
    st.markdown("**Number of municipalities per category**")
    count_chart = (
        alt.Chart(bin_summary)
        .mark_bar()
        .encode(
            x=alt.X("Category:N", sort=BIN_LABELS, title=None),
            y=alt.Y("Municipalities:Q"),
            tooltip=["Category", "Municipalities"],
        )
        .properties(height=300)
    )
    st.altair_chart(count_chart, use_container_width=True)

with bin_col2:
    st.markdown("**Share of total population per category**")
    share_chart = (
        alt.Chart(bin_summary)
        .mark_bar()
        .encode(
            x=alt.X("Category:N", sort=BIN_LABELS, title=None),
            y=alt.Y("Share of Total:Q", title="% of total population"),
            tooltip=["Category", "Share of Total"],
        )
        .properties(height=300)
    )
    st.altair_chart(share_chart, use_container_width=True)

# Merge adjacent bins
st.markdown("**Combine adjacent categories**")
from_bin, to_bin = st.select_slider(
    "Select range of categories to combine",
    options=BIN_LABELS,
    value=(BIN_LABELS[0], BIN_LABELS[-1]),
)
from_idx = BIN_LABELS.index(from_bin)
to_idx = BIN_LABELS.index(to_bin)
selected_labels = BIN_LABELS[from_idx : to_idx + 1]
combined_label = f"{from_bin} to {to_bin}" if from_bin != to_bin else from_bin

combined_df = df[df["Category"].isin(selected_labels)]
combined_pop = combined_df["Population"].sum()
combined_pct = combined_pop / total_pop * 100

cc1, cc2, cc3 = st.columns(3)
cc1.metric("Municipalities", len(combined_df))
cc2.metric("Combined population", f"{combined_pop:,.0f}")
cc3.metric("Share of total", f"{combined_pct:.1f}%")

st.dataframe(
    combined_df.sort_values("Population", ascending=False)[["Municipality", "Population", "Category", "Index vs Mean", "Index vs Median"]]
    .style.format({"Population": "{:,.0f}", "Index vs Mean": "{:.2f}", "Index vs Median": "{:.2f}"}),
    use_container_width=True,
)
