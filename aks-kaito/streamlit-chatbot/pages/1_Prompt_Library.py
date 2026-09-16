from __future__ import annotations

import streamlit as st

from prompt_library_store import delete_prompt, ensure_prompt_library_file, load_prompts, upsert_prompt
from sidebar_nav import render_sidebar_nav

st.set_page_config(page_title="Prompt Library", layout="wide")

render_sidebar_nav(current="prompt-library")

st.title("Prompt Library")
st.caption("Create, edit, and delete reusable prompts stored in a local CSV file.")

library_path = ensure_prompt_library_file()
prompts = load_prompts()

st.subheader("Saved Prompts")
if prompts:
    st.dataframe(
        [
            {
                "Short name": item["name"],
                "Prompt": item["prompt"],
                "Updated": item["updated_at"],
            }
            for item in prompts
        ],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No prompts saved yet. Create one below.")

create_tab, edit_tab, delete_tab = st.tabs(["Create", "Edit", "Delete"])

with create_tab:
    with st.form("create_prompt_form", clear_on_submit=True):
        new_name = st.text_input(
            "Short name",
            max_chars=15,
            help="A short label that appears in the prompt dropdown in chat.",
        )
        new_prompt = st.text_area(
            "Prompt text",
            height=200,
            help="Instruction text to apply when asking questions.",
        )
        submitted = st.form_submit_button("Save prompt", type="primary")
        if submitted:
            try:
                upsert_prompt(name=new_name, prompt=new_prompt)
                st.success(f"Saved prompt '{new_name.strip()}'.")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(str(e))

with edit_tab:
    if not prompts:
        st.info("Create a prompt first to enable editing.")
    else:
        names = [item["name"] for item in prompts]
        selected_name = st.selectbox("Prompt to edit", names, index=0)
        selected = next((item for item in prompts if item["name"] == selected_name), None)
        current_text = (selected or {}).get("prompt", "")

        with st.form("edit_prompt_form"):
            updated_name = st.text_input("Short name", value=selected_name, max_chars=15)
            updated_prompt = st.text_area("Prompt text", value=current_text, height=220)
            updated = st.form_submit_button("Save changes", type="primary")
            if updated:
                try:
                    upsert_prompt(name=updated_name, prompt=updated_prompt, original_name=selected_name)
                    st.success(f"Updated prompt '{updated_name.strip()}'.")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(str(e))

with delete_tab:
    if not prompts:
        st.info("Create a prompt first to enable deletion.")
    else:
        names = [item["name"] for item in prompts]
        to_delete = st.selectbox("Prompt to delete", names, index=0)
        confirm = st.checkbox(f"I understand this will permanently delete '{to_delete}'.")
        if st.button("Delete prompt", type="secondary", disabled=not confirm):
            deleted = delete_prompt(to_delete)
            if deleted:
                st.success(f"Deleted prompt '{to_delete}'.")
                st.rerun()
            else:
                st.error("Prompt could not be deleted.")

st.divider()
st.caption(f"Storage file: {library_path}")
