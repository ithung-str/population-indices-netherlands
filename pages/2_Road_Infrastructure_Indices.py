import streamlit as st
import pandas as pd
import altair as alt
import cbsodata

st.title("Road Infrastructure Indices for Dutch Municipalities")
st.caption(
    "Quick insight by Structural Collective · Data: [CBS StatLine](https://opendata.cbs.nl/) — table 70806ned (Lengte van wegen). "
    "Road length is measured within the geographic boundaries of each municipality, regardless of road manager."
)

ROAD_TYPES = {
    "T001491": "Total road length",
    "A047344": "Municipal roads",
    "A047352": "Provincial roads",
    "A047360": "National roads (Rijkswegen)",
}


@st.cache_data(ttl=86400)
def load_road_data(road_type_key, year):
    data = cbsodata.get_data(
        "70806ned",
        filters=(
            f"Perioden eq '{year}JJ00'"
            f" and SoortRijbanen eq '{road_type_key}'"
            " and substringof('GM',RegioS)"
        ),
        select=["RegioS", "Weglengte_1"],
    )
    records = [r for r in data if r["Weglengte_1"] is not None]
    df = pd.DataFrame(records)
    df.columns = ["Municipality", "Road Length (km)"]
    df["Municipality"] = df["Municipality"].str.strip()
    return df.sort_values("Municipality").reset_index(drop=True)


# Controls
ctrl1, ctrl2 = st.columns(2)
road_type = ctrl1.selectbox("Road type", list(ROAD_TYPES.values()))
road_type_key = [k for k, v in ROAD_TYPES.items() if v == road_type][0]
year = ctrl2.selectbox("Year", list(range(2025, 2000, -1)), index=0)

df = load_road_data(road_type_key, year)
VALUE_COL = "Road Length (km)"

st.markdown(f"**Showing: {road_type} — {year}**")

# Compute indices
mean_val = df[VALUE_COL].mean()
median_val = df[VALUE_COL].median()

df["Index vs Mean"] = (df[VALUE_COL] / mean_val).round(2)
df["Index vs Median"] = (df[VALUE_COL] / median_val).round(2)

# Summary metrics
col1, col2, col3, col4 = st.columns(4)
col1.metric("Municipalities", len(df))
col2.metric("Mean road length", f"{mean_val:,.0f} km")
col3.metric("Median road length", f"{median_val:,.0f} km")
col4.metric("Total road length", f"{df[VALUE_COL].sum():,.0f} km")

st.markdown("---")

# Search / filter
search = st.text_input("Search municipality", placeholder="e.g. Amsterdam", key="road_search")
filtered = df[df["Municipality"].str.contains(search, case=False, na=False)] if search else df

st.markdown(
    f"**Index vs Mean**: road length / mean road length. "
    f"**Index vs Median**: road length / median road length. "
    "A value of 1.0 = equal to the reference."
)

# Display table
st.dataframe(
    filtered.style.format({VALUE_COL: "{:,.0f}", "Index vs Mean": "{:.2f}", "Index vs Median": "{:.2f}"}),
    width="stretch",
    height=600,
)

# Distribution chart
st.subheader(f"Road Length Distribution — {road_type} ({year})")
sort_col1, sort_col2 = st.columns(2)
sort_by = sort_col1.selectbox("Sort by", [VALUE_COL, "Index vs Mean", "Index vs Median", "Municipality"], key="road_sort")
sort_order = sort_col2.selectbox("Order", ["Descending", "Ascending"], key="road_order")
ascending = sort_order == "Ascending"

sorted_df = df.sort_values("Municipality" if sort_by == "Municipality" else sort_by, ascending=ascending)

municipality_order = sorted_df["Municipality"].tolist()
chart = (
    alt.Chart(sorted_df)
    .mark_bar()
    .encode(
        x=alt.X("Municipality:N", sort=municipality_order, axis=alt.Axis(labels=False)),
        y=alt.Y(f"{VALUE_COL}:Q"),
        tooltip=["Municipality", VALUE_COL, "Index vs Mean", "Index vs Median"],
    )
    .properties(height=400)
)
st.altair_chart(chart, width="stretch")

# Range explorer
st.markdown("---")
st.subheader(f"Road Length Range Explorer — {road_type} ({year})")

ranked = df.sort_values(VALUE_COL, ascending=False).reset_index(drop=True)
ranked.index += 1
total_val = df[VALUE_COL].sum()
n = len(ranked)

rank_range = st.slider(
    "Select rank range (1 = most road km)",
    min_value=1,
    max_value=n,
    value=(1, 10),
    key="road_range",
)

selected = ranked.loc[rank_range[0]:rank_range[1]]
selected_val = selected[VALUE_COL].sum()
selected_pct = selected_val / total_val * 100

mc1, mc2, mc3 = st.columns(3)
mc1.metric("Municipalities selected", len(selected))
mc2.metric("Combined road length", f"{selected_val:,.0f} km")
mc3.metric("Share of total", f"{selected_pct:.1f}%")

st.dataframe(
    selected[["Municipality", VALUE_COL, "Index vs Mean", "Index vs Median"]]
    .style.format({VALUE_COL: "{:,.0f}", "Index vs Mean": "{:.2f}", "Index vs Median": "{:.2f}"}),
    width="stretch",
)

# Road length bins
st.markdown("---")
st.subheader(f"Road Length Classification — {road_type} ({year})")

BIN_EDGES = [0, 100, 200, 400, 600, 1000, 2000, float("inf")]
BIN_LABELS = [
    "< 100 km",
    "100 – 200 km",
    "200 – 400 km",
    "400 – 600 km",
    "600 – 1,000 km",
    "1,000 – 2,000 km",
    "2,000+ km",
]

df["Category"] = pd.cut(df[VALUE_COL], bins=BIN_EDGES, labels=BIN_LABELS, right=False)

bin_summary = (
    df.groupby("Category", observed=False)
    .agg(
        Municipalities=("Municipality", "count"),
        Total_Road_Length=( VALUE_COL, "sum"),
        Mean_Road_Length=(VALUE_COL, "mean"),
    )
    .reset_index()
)
bin_summary["Share of Total"] = (bin_summary["Total_Road_Length"] / total_val * 100).round(1)
bin_summary["Mean_Road_Length"] = bin_summary["Mean_Road_Length"].round(0)

st.dataframe(
    bin_summary.style.format({
        "Total_Road_Length": "{:,.0f}",
        "Mean_Road_Length": "{:,.0f}",
        "Share of Total": "{:.1f}%",
    }),
    width="stretch",
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
    st.altair_chart(count_chart, width="stretch")

with bin_col2:
    st.markdown("**Share of total road length per category**")
    share_chart = (
        alt.Chart(bin_summary)
        .mark_bar()
        .encode(
            x=alt.X("Category:N", sort=BIN_LABELS, title=None),
            y=alt.Y("Share of Total:Q", title="% of total road length"),
            tooltip=["Category", "Share of Total"],
        )
        .properties(height=300)
    )
    st.altair_chart(share_chart, width="stretch")

# Merge adjacent bins
st.markdown("**Combine adjacent categories**")
from_bin, to_bin = st.select_slider(
    "Select range of categories to combine",
    options=BIN_LABELS,
    value=(BIN_LABELS[0], BIN_LABELS[-1]),
    key="road_bins",
)
from_idx = BIN_LABELS.index(from_bin)
to_idx = BIN_LABELS.index(to_bin)
selected_labels = BIN_LABELS[from_idx : to_idx + 1]

combined_df = df[df["Category"].isin(selected_labels)]
combined_val = combined_df[VALUE_COL].sum()
combined_pct = combined_val / total_val * 100

cc1, cc2, cc3 = st.columns(3)
cc1.metric("Municipalities", len(combined_df))
cc2.metric("Combined road length", f"{combined_val:,.0f} km")
cc3.metric("Share of total", f"{combined_pct:.1f}%")

st.dataframe(
    combined_df.sort_values(VALUE_COL, ascending=False)[["Municipality", VALUE_COL, "Category", "Index vs Mean", "Index vs Median"]]
    .style.format({VALUE_COL: "{:,.0f}", "Index vs Mean": "{:.2f}", "Index vs Median": "{:.2f}"}),
    width="stretch",
)
