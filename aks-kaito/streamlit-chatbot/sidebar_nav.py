from __future__ import annotations

import streamlit as st


def render_sidebar_nav(*, current: str) -> None:
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNav"] { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.page_link("app.py", label="Home", icon="🏠", disabled=current == "home")
    st.sidebar.page_link(
        "pages/1_Prompt_Library.py",
        label="Prompt Library",
        icon="🗂️",
        disabled=current == "prompt-library",
    )
    st.sidebar.page_link(
        "pages/2_Document_Ingestion.py",
        label="Document Ingestion",
        icon="📥",
        disabled=current == "document-ingestion",
    )
    st.sidebar.divider()
