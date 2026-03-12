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


@st.cache_data(ttl=86400, show_spinner="Fetching dimension values...")
def load_dimension_values(table_id, dimension_key):
    """Fetch the valid keys/titles for a dimension."""
    try:
        values = cbsodata.get_meta(table_id, dimension_key)
        return [(v.get("Key", "").strip(), v.get("Title", "").strip()) for v in values]
    except Exception:
        return []


def build_llm_prompt(table_id, props_df):
    """Build a prompt with all metadata an LLM needs to write a CBS query."""
    dimensions = props_df[props_df["Type"].isin(["Dimension", "GeoDimension", "TimeDimension"])]
    topics = props_df[props_df["Type"] == "Topic"]

    lines = [
        f"I need help writing a Python query for CBS table `{table_id}` using the `cbsodata` package.",
        "",
        "## Table columns",
        "",
        "### Dimensions (used in OData filters)",
    ]

    for _, row in dimensions.iterrows():
        key = row["Key"]
        title = row["Title"]
        dim_type = row["Type"]
        lines.append(f"\n**{key}** ({title}, {dim_type})")
        values = load_dimension_values(table_id, key)
        if values:
            lines.append("Valid keys:")
            for k, t in values[:50]:
                lines.append(f"  - `{k}` = {t}")
            if len(values) > 50:
                lines.append(f"  - ... and {len(values) - 50} more values")

    lines.append("\n### Data columns (topic columns)")
    for _, row in topics.iterrows():
        desc = f" — {row['Description']}" if row["Description"] else ""
        lines.append(f"- `{row['Key']}`: {row['Title']}{desc}")

    lines.extend([
        "",
        "## Instructions",
        "",
        "Write a Python snippet using `cbsodata.get_data()` to query this table.",
        "Use the `filters` parameter for OData filtering and `select` to pick columns.",
        "",
        "Example pattern:",
        "```python",
        "import cbsodata",
        f"data = cbsodata.get_data('{table_id}',",
        "    filters=\"<OData filter here>\",",
        "    select=['<col1>', '<col2>']",
        ")",
        "```",
        "",
        "OData filter syntax:",
        "- Equality: `Perioden eq '2024JJ00'`",
        "- Substring match: `substringof('GM',RegioS)` (municipalities only)",
        "- Combine with `and`: `substringof('GM',RegioS) and Perioden eq '2024JJ00'`",
        "- Year format: `'YYYYJJnn'` (e.g. `'2024JJ00'`), month: `'YYYYMMnn'`",
        "- Dimension keys must match exactly (including trailing spaces if any)",
        "",
        "For municipality data, always filter with `substringof('GM',RegioS)` to get only gemeenten.",
        "Filter out rows with None values in the result — defunct municipalities return None for recent periods.",
    ])

    return "\n".join(lines)


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
st.dataframe(display_cat, width="stretch", height=300)

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
    st.dataframe(props, width="stretch", height=300)

    # LLM prompt copy button
    st.markdown("---")
    st.subheader("Ask an LLM to build your query")
    st.markdown(
        "Click the button below to copy the full table metadata (dimensions, valid filter "
        "values, and data columns) along with instructions. Paste it into ChatGPT, Claude, "
        "or any LLM to get a ready-to-use `cbsodata` query. Then paste the OData filter "
        "and column selection back into the query section below."
    )

    llm_prompt = build_llm_prompt(table_id, props)

    with st.expander("Preview & copy LLM prompt"):
        st.code(llm_prompt, language="markdown")
        st.caption("Use the copy icon in the top-right of the code block above to copy the prompt.")

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
            st.dataframe(data[numeric_cols].describe().round(1), width="stretch")

        # Data table
        st.markdown("**Data**")
        st.dataframe(data, width="stretch", height=500)

        # Download
        csv = data.to_csv(index=False).encode("utf-8")
        st.download_button("Download as CSV", csv, f"{table_id}.csv", "text/csv")
