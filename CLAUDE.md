# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
pip install -e .
```

Requires a `.env` file with:
```
GROQ_API_KEY=...
TAVILY_API_KEY=...   # optional, needed for web search
```

## Running the Application

```bash
python app/main.py
```

This launches two services concurrently:
- FastAPI backend at `http://127.0.0.1:9999`
- Streamlit frontend at `http://127.0.0.1:8501`

## Architecture

Three-tier design with two processes running in threads from a single entry point:

```
Streamlit UI (port 8501)
  → POST /chat → FastAPI backend (port 9999)
    → get_response_from_ai_agents()
      → LangGraph ReAct agent → Groq LLM
                               → Tavily search (optional)
```

**Key files:**
- [app/main.py](app/main.py) — Entry point; spawns backend and frontend threads
- [app/backend/api.py](app/backend/api.py) — Single `POST /chat` endpoint; validates model against whitelist in `settings.py`
- [app/core/ai_agent.py](app/core/ai_agent.py) — `get_response_from_ai_agents()`: creates a LangGraph `create_react_agent` with Groq LLM; Tavily tool added only when `allow_search=True`
- [app/frontend/ui.py](app/frontend/ui.py) — Streamlit interface; collects system prompt, model choice, query, and search toggle; calls backend
- [app/config/settings.py](app/config/settings.py) — Loads env vars; defines the allowed model whitelist (`llama3-70b-8192`, `llama-3.3-70b-versatile`)
- [app/common/logger.py](app/common/logger.py) — Centralized logging; writes to `logs/` directory (gitignored)
- [app/common/custom_exception.py](app/common/custom_exception.py) — Custom exception that captures full traceback detail

## Deployment

The project uses a Jenkins → AWS ECR → AWS ECS Fargate pipeline defined in [Jenkinsfile](Jenkinsfile). Stages: SonarQube analysis → Docker build/push to ECR → `ecs update-service --force-new-deployment`.

Docker build:
```bash
docker build -t <image-name> .
docker run -d -p 8501:8501 -p 9999:9999 <image-name>
```

See [FULL_DOCUMENTATION.md](FULL_DOCUMENTATION.md) for step-by-step AWS/Jenkins setup instructions.
