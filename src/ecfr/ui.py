# ui.py
import streamlit as st, requests, pandas as pd, altair as alt

API = "http://localhost:8000"
df  = pd.DataFrame(requests.get(f"{API}/metrics").json())

st.title("eCFR snapshot – today")
st.dataframe(df.sort_values("word_count", ascending=False))

st.altair_chart(alt.Chart(df).mark_bar().encode(
    x="agency", y="word_count").properties(title="Word count by agency"))
