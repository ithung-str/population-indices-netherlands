import streamlit as st
import pandas as pd
import cbsodata

st.title("CBS Municipality Data Explorer")
st.caption(
    "Quick insight by Structural Collective · "
    "Browse and query any [CBS StatLine](https://opendata.cbs.nl/) table with municipality-level data"
)


@st.cache_data(ttl=86400, show_spinner="Loading CBS table catalogue...")
def load_table_list():
    """Fetch the full CBS table catalogue and filter for municipality-relevant tables."""
    tables = pd.DataFrame(cbsodata.get_table_list())
    # Keep tables that mention gemeente/regio in title or summary
    mask = (
        tables["Title"].str.contains("regio|gemeente|wijk|buurt|provinc", case=False, na=False)
        | tables["Summary"].str.contains("gemeente", case=False, na=False)
    )
    relevant = tables[mask][
        ["Identifier", "Title", "Summary", "Period", "RecordCount", "Updated"]
    ].copy()
    relevant = relevant.sort_values("Updated", ascending=False).reset_index(drop=True)
    return relevant


@st.cache_data(ttl=86400, show_spinner="Fetching table metadata...")
def load_table_info(table_id):
    """Get column metadata for a CBS table."""
    meta = cbsodata.get_meta(table_id, "DataProperties")
    props = pd.DataFrame(meta)
    return props[["Key", "Title", "Description", "Type"]].dropna(subset=["Key"])


@st.cache_data(ttl=86400, show_spinner="Fetching data from CBS...")
def load_table_data(table_id, odata_filter):
    """Fetch data from a CBS table with an optional OData filter."""
    if odata_filter:
        data = cbsodata.get_data(table_id, filters=odata_filter)
    else:
        data = cbsodata.get_data(table_id)
    return pd.DataFrame(data)


# --- Table catalogue ---
st.subheader("Available tables")
catalogue = load_table_list()

search = st.text_input(
    "Search tables",
    placeholder="e.g. inkomen, wonen, bodemgebruik, criminaliteit, wegen...",
)
if search:
    terms = search.lower().split()
    mask = pd.Series(True, index=catalogue.index)
    for term in terms:
        mask &= (
            catalogue["Title"].str.lower().str.contains(term, na=False)
            | catalogue["Summary"].str.lower().str.contains(term, na=False)
        )
    display_cat = catalogue[mask]
else:
    display_cat = catalogue

st.caption(f"{len(display_cat)} tables found")
st.dataframe(display_cat, use_container_width=True, height=300)

# --- Table selection ---
st.markdown("---")
st.subheader("Explore a table")

table_id = st.text_input(
    "Enter a table ID from the list above",
    placeholder="e.g. 70072ned",
)

if table_id:
    table_id = table_id.strip()

    # Show column metadata
    try:
        props = load_table_info(table_id)
    except Exception as e:
        st.error(f"Could not load metadata for '{table_id}': {e}")
        st.stop()

    st.markdown(f"**Columns in `{table_id}`** ({len(props)} fields)")
    st.dataframe(props, use_container_width=True, height=300)

    # Filter builder
    st.markdown("---")
    st.subheader("Query data")
    st.markdown(
        "Tip: use OData filters to narrow results. For municipality data, try: "
        "`substringof('GM',RegioS)` to get only municipalities. "
        "Combine with `and` — e.g. `substringof('GM',RegioS) and Perioden eq '2024JJ00'`"
    )

    odata_filter = st.text_input(
        "OData filter (optional — leave empty to fetch all rows)",
        placeholder="substringof('GM',RegioS) and Perioden eq '2024JJ00'",
    )

    col_options = props["Key"].tolist()
    selected_cols = st.multiselect(
        "Select columns to display (leave empty for all)",
        options=col_options,
    )

    if st.button("Fetch data", type="primary"):
        with st.spinner("Querying CBS..."):
            try:
                data = load_table_data(table_id, odata_filter if odata_filter else None)
            except Exception as e:
                st.error(f"Query failed: {e}")
                st.stop()

        if selected_cols:
            # Always keep region/period columns if present
            available = [c for c in selected_cols if c in data.columns]
            if available:
                data = data[available]

        st.success(f"Loaded {len(data):,} rows × {len(data.columns)} columns")

        # Summary stats
        numeric_cols = data.select_dtypes(include="number").columns.tolist()
        if numeric_cols:
            st.markdown("**Quick stats for numeric columns**")
            st.dataframe(data[numeric_cols].describe().round(1), use_container_width=True)

        # Data table
        st.markdown("**Data**")
        st.dataframe(data, use_container_width=True, height=500)

        # Download
        csv = data.to_csv(index=False).encode("utf-8")
        st.download_button("Download as CSV", csv, f"{table_id}.csv", "text/csv")
