import streamlit as st, requests, pandas as pd

API = "http://localhost:8000"

st.set_page_config(page_title="eCFR snapshot", layout="wide")

st.title("eCFR snapshot – today")

df = pd.DataFrame(requests.get(f"{API}/metrics").json())

st.dataframe(df.sort_values("word_count", ascending=False))

st.bar_chart(df.set_index("agency")["word_count"], height=400)

if "rvi" in df.columns:
    st.subheader("Regulatory Volatility Index (RVI)")
    st.line_chart(df.set_index("agency")["rvi"], height=300)