import streamlit as st
import requests

from app.config.settings import settings
from app.common.logger import get_logger
from app.common.custom_exception import CustomException

logger = get_logger(__name__)

st.set_page_config(page_title="Multi AI Agent", layout="centered")
st.title("Multi-Agent LLMOps")
st.caption("Researcher → Writer → Critic, powered by Groq + LangGraph")

system_prompt = st.text_area("Persona / style for the Writer agent:", height=70)
selected_model = st.selectbox("Select your AI model:", settings.ALLOWED_MODEL_NAMES)

allow_web_search = st.checkbox("Allow web search (Tavily) for the Researcher agent")

user_query = st.text_area("Enter your query:", height=150)

API_URL = "http://127.0.0.1:9999/chat"

if st.button("Ask Agents") and user_query.strip():

    payload = {
        "model_name": selected_model,
        "system_prompt": system_prompt,
        "messages": [user_query],
        "allow_search": allow_web_search,
    }

    try:
        logger.info("Sending request to backend")

        with st.spinner("Researcher → Writer → Critic working..."):
            response = requests.post(API_URL, json=payload, timeout=180)

        if response.status_code == 200:
            data = response.json()
            agent_response = data.get("response", "")
            trace = data.get("trace") or {}
            logger.info("Sucesfully recived response from backend")

            st.subheader("Final Answer")
            st.markdown(agent_response.replace("\n", "<br>"), unsafe_allow_html=True)

            iterations = trace.get("iterations", 0)
            with st.expander(f"Show agent reasoning trace ({iterations} writer iteration(s))"):
                st.markdown("#### 1. Researcher agent — collected notes")
                st.markdown(trace.get("research_notes", "_(empty)_") or "_(empty)_")

                st.markdown("#### 2. Writer agent — final draft")
                st.markdown(trace.get("draft", "_(empty)_") or "_(empty)_")

                st.markdown("#### 3. Critic agent — review")
                st.markdown(trace.get("critique", "_(empty)_") or "_(empty)_")

        else:
            logger.error("Backend error")
            st.error(f"Error with backend (status {response.status_code})")

    except Exception as e:
        logger.error("Error occured while sending request to backend")
        st.error(str(CustomException("Failed to communicate to backend")))
