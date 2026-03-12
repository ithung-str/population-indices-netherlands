import streamlit as st

st.set_page_config(
    page_title="Dutch Municipality Data — Structural Collective",
    layout="wide",
)

pages = st.navigation([
    st.Page("pages/0_Population_Indices.py", title="Population Indices", icon=":material/bar_chart:"),
    st.Page("pages/1_CBS_Data_Explorer.py", title="CBS Data Explorer", icon=":material/search:"),
])

pages.run()
