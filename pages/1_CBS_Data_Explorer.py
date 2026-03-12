import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import cbsodata


def copy_button(text, label="Copy to clipboard"):
    """Render a button that copies text to clipboard via JS."""
    import html as html_mod
    escaped = html_mod.escape(text).replace("`", "&#96;")
    components.html(
        f"""
        <button onclick="navigator.clipboard.writeText(document.getElementById('_cb').innerText)"
                style="padding:0.4em 1em;border:1px solid #ccc;border-radius:6px;
                       background:#f0f2f6;cursor:pointer;font-size:14px;">
            {label}
        </button>
        <span id="_cb" style="display:none">{escaped}</span>
        """,
        height=45,
    )

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

# --- Full catalogue LLM prompt ---
st.markdown("---")
st.subheader("Ask an LLM which table to use")
st.markdown(
    "Don't know which table you need? Copy the full catalogue below and paste it into "
    "an LLM. Describe what data you're looking for and it will recommend a table ID. "
    "Then enter that ID in the section below to explore it."
)


@st.cache_data(ttl=86400)
def build_catalogue_prompt(cat_df):
    lines = [
        "Below is a catalogue of CBS (Statistics Netherlands) tables that contain municipality-level data.",
        "I need your help finding the right table for my use case.",
        "",
        "## Instructions",
        "",
        "1. I will describe what data I need.",
        "2. Recommend the best table(s) from the catalogue below.",
        "3. For each recommendation, explain what data the table contains and why it fits.",
        "4. Give me the table ID (Identifier) so I can explore it further.",
        "",
        "## Available tables",
        "",
    ]
    for _, row in cat_df.iterrows():
        lines.append(f"- **{row['Identifier']}**: {row['Title']}")
        if row.get("Summary"):
            lines.append(f"  {row['Summary']}")
        if row.get("Period"):
            lines.append(f"  Period: {row['Period']}")
    lines.extend([
        "",
        "---",
        "",
        "What data am I looking for: <DESCRIBE YOUR NEED HERE>",
    ])
    return "\n".join(lines)


catalogue_prompt = build_catalogue_prompt(catalogue)

copy_button(catalogue_prompt, f"Copy catalogue prompt ({len(catalogue)} tables)")

with st.expander("Preview full catalogue prompt"):
    st.markdown(catalogue_prompt)

llm_table_response = st.text_area(
    "Paste LLM response here",
    placeholder="Paste the LLM's table recommendation here...",
    height=150,
    key="catalogue_llm_response",
)
if llm_table_response:
    st.markdown("**LLM recommendation:**")
    st.markdown(llm_table_response)

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

    copy_button(llm_prompt, f"Copy table prompt ({table_id})")

    with st.expander("Preview full table prompt"):
        st.markdown(llm_prompt)

    # Paste LLM response
    st.markdown("---")
    st.subheader("Paste LLM response")
    st.markdown(
        "Got a response from the LLM? Paste it below for reference while you fill in "
        "the query fields."
    )
    llm_response = st.text_area(
        "LLM response",
        placeholder="Paste the LLM's suggested query here...",
        height=200,
        key="table_llm_response",
    )
    if llm_response:
        st.markdown("**LLM suggestion:**")
        st.markdown(llm_response)

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
