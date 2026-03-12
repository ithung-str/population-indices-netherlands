import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import cbsodata

_copy_counter = 0


def copy_button(text, label="Copy to clipboard"):
    """Render a button that copies text to clipboard via JS."""
    global _copy_counter
    _copy_counter += 1
    uid = f"_cb_{_copy_counter}"
    import html as html_mod
    escaped = html_mod.escape(text).replace("`", "&#96;")
    components.html(
        f"""
        <button onclick="navigator.clipboard.writeText(document.getElementById('{uid}').innerText)"
                style="padding:0.4em 1em;border:1px solid #ccc;border-radius:6px;
                       background:#f0f2f6;cursor:pointer;font-size:14px;">
            {label}
        </button>
        <span id="{uid}" style="display:none">{escaped}</span>
        """,
        height=45,
    )


# ── Cached data loaders ─────────────────────────────────────────────────────


@st.cache_data(ttl=86400, show_spinner="Loading CBS table catalogue...")
def load_table_list():
    tables = pd.DataFrame(cbsodata.get_table_list())
    mask = (
        tables["Title"].str.contains("regio|gemeente|wijk|buurt|provinc", case=False, na=False)
        | tables["Summary"].str.contains("gemeente", case=False, na=False)
    )
    relevant = tables[mask][
        ["Identifier", "Title", "Summary", "Period", "RecordCount", "Updated"]
    ].copy()
    return relevant.sort_values("Updated", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=86400, show_spinner="Fetching table metadata...")
def load_table_info(table_id):
    meta = cbsodata.get_meta(table_id, "DataProperties")
    props = pd.DataFrame(meta)
    return props[["Key", "Title", "Description", "Type"]].dropna(subset=["Key"])


@st.cache_data(ttl=86400, show_spinner="Fetching dimension values...")
def load_dimension_values(table_id, dimension_key):
    try:
        values = cbsodata.get_meta(table_id, dimension_key)
        return [(v.get("Key", "").strip(), v.get("Title", "").strip()) for v in values]
    except Exception:
        return []


@st.cache_data(ttl=86400, show_spinner="Fetching data from CBS...")
def load_table_data(table_id, odata_filter):
    if odata_filter:
        data = cbsodata.get_data(table_id, filters=odata_filter)
    else:
        data = cbsodata.get_data(table_id)
    return pd.DataFrame(data)


# ── Prompt builders ──────────────────────────────────────────────────────────


@st.cache_data(ttl=86400)
def build_catalogue_prompt(cat_df):
    lines = [
        "Below is a catalogue of CBS (Statistics Netherlands) tables with municipality-level data.",
        "I need your help finding the right table for my use case.",
        "",
        "## Instructions",
        "",
        "1. I will describe what data I need.",
        "2. Recommend the best table(s) from the catalogue below.",
        "3. For each recommendation, explain what data it contains and why it fits.",
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
    lines.extend(["", "---", "", "What data am I looking for: <DESCRIBE YOUR NEED HERE>"])
    return "\n".join(lines)


def build_table_prompt(table_id, props_df):
    dimensions = props_df[props_df["Type"].isin(["Dimension", "GeoDimension", "TimeDimension"])]
    topics = props_df[props_df["Type"] == "Topic"]

    lines = [
        f"I need help querying CBS table `{table_id}`.",
        "",
        "## Table columns",
        "",
        "### Dimensions (used in OData filters)",
    ]

    for _, row in dimensions.iterrows():
        lines.append(f"\n**{row['Key']}** ({row['Title']}, {row['Type']})")
        values = load_dimension_values(table_id, row["Key"])
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
        "DO NOT return Python code. Return ONLY:",
        "",
        "1. **OData filter** — a single string I can paste into a filter field.",
        "2. **Columns** — a comma-separated list of column keys to select.",
        "",
        "## Required response format",
        "",
        "**OData filter:**",
        "`substringof('GM',RegioS) and Perioden eq '2024JJ00'`",
        "",
        "**Columns:**",
        "`RegioS, Perioden, ColumnA, ColumnB`",
        "",
        "**Explanation:**",
        "(brief explanation of what the filter does and why these columns were chosen)",
        "",
        "## OData filter syntax",
        "",
        "- Equality: `Perioden eq '2024JJ00'`",
        "- Substring match: `substringof('GM',RegioS)` (municipalities only)",
        "- Combine with `and`: `substringof('GM',RegioS) and Perioden eq '2024JJ00'`",
        "- Year format: `'YYYYJJnn'` (e.g. `'2024JJ00'`), month: `'YYYYMMnn'`",
        "- Dimension keys must match exactly (including trailing spaces if any)",
        "",
        "For municipality data, always filter with `substringof('GM',RegioS)` to get only gemeenten.",
    ])

    return "\n".join(lines)


# ── Page layout ──────────────────────────────────────────────────────────────

st.title("CBS Municipality Data Explorer")
st.caption(
    "Quick insight by Structural Collective · "
    "Browse and query any [CBS StatLine](https://opendata.cbs.nl/) table with municipality-level data"
)

st.info(
    "**How to use this page:**\n\n"
    "**Step 1** — Find a table: search the catalogue below, or copy the catalogue prompt "
    "and ask an LLM to recommend a table.\n\n"
    "**Step 2** — Enter the table ID to see its columns and dimensions.\n\n"
    "**Step 3** — Build your query: either copy the table prompt and ask an LLM for the "
    "right OData filter + columns, or fill them in yourself.\n\n"
    "**Step 4** — Paste the LLM's filter and columns into the query fields, then click Fetch."
)

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: Find a table
# ═══════════════════════════════════════════════════════════════════════════════

st.header("Step 1: Find a table")

catalogue = load_table_list()

search = st.text_input(
    "Search tables",
    placeholder="e.g. inkomen, wonen, bodemgebruik, criminaliteit, wegen, zonnepanelen...",
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

st.markdown(
    "**Not sure which table?** Copy the full catalogue and ask an LLM. "
    "Replace `<DESCRIBE YOUR NEED HERE>` at the bottom with your question."
)
catalogue_prompt = build_catalogue_prompt(catalogue)
copy_button(catalogue_prompt, f"Copy catalogue prompt ({len(catalogue)} tables)")

with st.expander("Preview catalogue prompt"):
    st.markdown(catalogue_prompt)

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: Explore a table
# ═══════════════════════════════════════════════════════════════════════════════

st.header("Step 2: Explore a table")

table_id = st.text_input(
    "Enter a table ID",
    placeholder="e.g. 70072ned, 85005NED",
)

if not table_id:
    st.stop()

table_id = table_id.strip()

try:
    props = load_table_info(table_id)
except Exception as e:
    st.error(f"Could not load metadata for '{table_id}': {e}")
    st.stop()

st.markdown(f"**Columns in `{table_id}`** ({len(props)} fields)")
st.dataframe(props, width="stretch", height=300)

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: Get the right filter from an LLM
# ═══════════════════════════════════════════════════════════════════════════════

st.header("Step 3: Get the right filter")
st.markdown(
    "Copy the table prompt below and paste it into an LLM (ChatGPT, Claude, etc.). "
    "Describe what you want to query. The LLM will return an **OData filter** and "
    "**column list** — paste those into Step 4."
)

llm_prompt = build_table_prompt(table_id, props)
copy_button(llm_prompt, f"Copy table prompt ({table_id})")

with st.expander("Preview table prompt"):
    st.markdown(llm_prompt)

llm_response = st.text_area(
    "Paste LLM response here (for your reference)",
    placeholder="The LLM will give you an OData filter and column list — paste it here to keep it visible while you fill in Step 4 below.",
    height=150,
    key="table_llm_response",
)
if llm_response:
    st.markdown(llm_response)

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4: Fetch data
# ═══════════════════════════════════════════════════════════════════════════════

st.header("Step 4: Fetch data")
st.markdown("Paste the **OData filter** and select the **columns** from the LLM response above, then click Fetch.")

odata_filter = st.text_input(
    "OData filter",
    placeholder="substringof('GM',RegioS) and Perioden eq '2025JJ00'",
)

col_options = props["Key"].tolist()
selected_cols = st.multiselect(
    "Columns (leave empty for all)",
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
        available = [c for c in selected_cols if c in data.columns]
        if available:
            data = data[available]

    st.success(f"Loaded {len(data):,} rows x {len(data.columns)} columns")

    numeric_cols = data.select_dtypes(include="number").columns.tolist()
    if numeric_cols:
        st.markdown("**Quick stats**")
        st.dataframe(data[numeric_cols].describe().round(1), width="stretch")

    st.markdown("**Data**")
    st.dataframe(data, width="stretch", height=500)

    csv = data.to_csv(index=False).encode("utf-8")
    st.download_button("Download as CSV", csv, f"{table_id}.csv", "text/csv")
