# Workflow & runtime flow

How this project actually runs, from `docker build` to a rendered answer in your browser. Read alongside [README.md](README.md) (architecture overview) and [explanation.md](explanation.md) (chronological setup walkthrough — local only).

---

## TL;DR — the path of one user query

```
docker run …
   │
   ▼
app/main.py  spawns two processes inside the container:
   ├── uvicorn  app.backend.api:app   on  127.0.0.1:9999   (internal)
   └── streamlit run app/frontend/ui.py on 0.0.0.0:8501   (exposed)
   
You browse  http://localhost:8501
   │
   ▼
You fill in the form → click "Ask Agents"
   │
   ▼
ui.py POSTs JSON to  http://127.0.0.1:9999/chat
   │
   ▼
api.py validates the request, calls ai_agent.get_response_from_ai_agents(...)
   │
   ▼
ai_agent.py runs the compiled LangGraph StateGraph:
   START → Researcher → Writer → Critic → (revise? back to Writer : Finalize) → END
   │
   ▼
FastAPI wraps the result as  {response, trace}  and returns
   │
   ▼
ui.py renders the Final Answer and a collapsible trace in Streamlit
```

---

## 1. The Dockerfile, line by line

[`Dockerfile`](Dockerfile):

```dockerfile
FROM python:3.10-slim
```
Tiny Debian-based image (~80 MB) with Python 3.10 pre-installed. Slim means it has no compiler/headers/man pages — we add what we need explicitly.

```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
```
- `PYTHONDONTWRITEBYTECODE=1` — don't litter `__pycache__` `.pyc` files. Slightly cleaner image.
- `PYTHONUNBUFFERED=1` — flush `print` / log output immediately rather than buffering. Critical so `docker logs -f multi-agent` shows things as they happen instead of blob-by-blob.

```dockerfile
WORKDIR /app
```
All subsequent `COPY` / `RUN` / `CMD` operate relative to `/app`. The application code will live here as `/app/app/...` once we copy.

```dockerfile
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*
```
- `build-essential` — gcc + make. Some pip dependencies (e.g. `numpy`, `pyarrow`) ship binary wheels on PyPI but a few packages still compile from source on `python:3.10-slim`. This is insurance.
- `curl` — handy for one-off in-container debugging (e.g. `docker exec multi-agent curl http://127.0.0.1:9999/chat ...`).
- `rm -rf /var/lib/apt/lists/*` — wipe the apt cache so it doesn't bloat the image layer.

```dockerfile
COPY . .
```
Copy everything from the build context (the project root) into `/app`. **`.dockerignore` controls what's actually copied** — it excludes `.git`, `.env`, `venv/`, `__pycache__/`, etc., so the image stays small and no secrets leak in.

```dockerfile
RUN pip install --no-cache-dir -e .
```
"`-e`" = editable install. `setup.py` reads `requirements.txt` and pip installs everything (`langchain-groq`, `streamlit`, `fastapi`, `langgraph`, `tavily-python`, etc.) plus registers the local `app/` package. `--no-cache-dir` keeps the image small.

```dockerfile
EXPOSE 8501
EXPOSE 9999
```
Pure documentation — declares which ports the app listens on. **It does NOT actually publish them to the host**; that's what `-p 8501:8501` on `docker run` does. Tools like `docker inspect` and ECS read these declarations to wire up health checks / load balancers, but nothing breaks if you publish a port that wasn't declared.

```dockerfile
CMD ["python", "app/main.py"]
```
The default command run when the container starts. From `WORKDIR=/app`, this resolves to `python /app/app/main.py`.

---

## 2. The entry point — `app/main.py`

[`app/main.py`](app/main.py) is the **process supervisor**. One container, two co-located services.

```python
from dotenv import load_dotenv
load_dotenv()
```
Loads `GROQ_API_KEY` and `TAVILY_API_KEY` from the project's `.env` file *if present*. In production (ECS), `.env` doesn't exist in the image (it's `.dockerignore`d) — the env vars come from the ECS task definition's environment block. Either way, they end up in `os.environ` by the time the app needs them.

```python
def run_backend():
    subprocess.run(["uvicorn", "app.backend.api:app",
                    "--host", "127.0.0.1", "--port", "9999"], check=True)

def run_frontend():
    subprocess.run(["streamlit", "run", "app/frontend/ui.py"], check=True)
```
Two subprocess wrappers. Each launches one of the two web servers.

```python
if __name__ == "__main__":
    threading.Thread(target=run_backend).start()
    time.sleep(2)
    run_frontend()
```
- A daemon-ish thread starts uvicorn (FastAPI backend).
- 2-second sleep gives uvicorn time to bind its port before Streamlit starts firing requests at it.
- Streamlit runs in the *main* thread (synchronously) — it never returns. When you Ctrl+C / `docker stop`, both stop.

### Why two processes, not one?

Streamlit and FastAPI have different runtime models. Streamlit reruns the script top-to-bottom on every UI interaction; FastAPI is a long-lived ASGI app. Easiest to run them as separate servers and have Streamlit POST to FastAPI when it needs the agent.

### The 127.0.0.1 vs 0.0.0.0 distinction

- **uvicorn** (FastAPI backend) binds `--host 127.0.0.1`. That means it listens *only* on the loopback interface inside the container. Nothing outside the container can reach it. The host port mapping `-p 9999:9999` is therefore vestigial — it forwards a host port to a container interface that nothing's listening on.
- **streamlit** binds `0.0.0.0:8501` by default. That's the externally-reachable interface. Combined with `-p 8501:8501`, the host's `localhost:8501` reaches Streamlit.

Streamlit calls FastAPI on `http://127.0.0.1:9999/chat` *from inside the container* — and that works because both processes share the loopback interface. The backend stays internal, which is good for security: the LLM API isn't accidentally exposed to the public internet.

---

## 3. What loads when you visit localhost:8501

Streamlit serves [`app/frontend/ui.py`](app/frontend/ui.py). On every page load (and every interaction), Streamlit re-runs the script top-to-bottom. The script defines four widgets and one button:

| Widget | Variable bound |
|---|---|
| Text area "Persona / style for the Writer agent:" | `system_prompt` |
| Selectbox "Select your AI model:" | `selected_model` (from `settings.ALLOWED_MODEL_NAMES`) |
| Checkbox "Allow web search (Tavily) for the Researcher agent" | `allow_web_search` |
| Text area "Enter your query:" | `user_query` |
| Button "Ask Agents" | `st.button("Ask Agents")` |

The model dropdown reads its options from [`app/config/settings.py`](app/config/settings.py:10-12) — currently just `llama-3.3-70b-versatile`.

Until you click the button, nothing else runs. Streamlit just renders the form.

---

## 4. What happens when you click "Ask Agents"

### Step 4.1 — `ui.py` builds the request

```python
payload = {
    "model_name": selected_model,
    "system_prompt": system_prompt,
    "messages": [user_query],
    "allow_search": allow_web_search,
}
response = requests.post("http://127.0.0.1:9999/chat", json=payload, timeout=180)
```

A 3-minute timeout because the multi-agent pipeline can take a while if the Critic decides to revise.

### Step 4.2 — FastAPI receives the request

[`app/backend/api.py`](app/backend/api.py) defines:

```python
class RequestState(BaseModel):
    model_name: str
    system_prompt: str
    messages: List[str]
    allow_search: bool

@app.post("/chat")
def chat_endpoint(request: RequestState):
    ...
```

FastAPI auto-validates the JSON body against `RequestState` (Pydantic). Bad JSON → automatic 422. Good JSON → typed `request` object passed in.

```python
if request.model_name not in settings.ALLOWED_MODEL_NAMES:
    raise HTTPException(status_code=400, detail="Invalid model name")
```

Hard whitelist on model name. Stops a malicious or buggy client from invoking unsupported / decommissioned Groq models.

### Step 4.3 — Backend invokes the agent graph

```python
result = get_response_from_ai_agents(
    request.model_name,
    request.messages,
    request.allow_search,
    request.system_prompt,
)
```

Calls into [`app/core/ai_agent.py`](app/core/ai_agent.py). This is the multi-agent layer.

### Step 4.4 — `ai_agent.py` runs the StateGraph

The graph is built **once at module import** (`_GRAPH = _build_graph()` at [app/core/ai_agent.py:153](app/core/ai_agent.py#L153)) and reused for every request — graph compilation is non-trivial work, no point repeating it.

`get_response_from_ai_agents(...)` constructs an initial `AgentState`:

```python
initial_state = {
    "user_query": "<the user's question>",
    "system_prompt": "<their persona>",
    "allow_search": True/False,
    "model_name": "llama-3.3-70b-versatile",
    "research_notes": "",
    "draft": "",
    "critique": "",
    "needs_revision": False,
    "iteration": 0,
    "final_answer": "",
}
```

Then `_GRAPH.invoke(initial_state)`. LangGraph traverses the graph:

#### 4.4a — `researcher_node`

If `allow_search=True`:
```python
researcher = create_react_agent(
    model=ChatGroq(model="llama-3.3-70b-versatile"),
    tools=[TavilySearchResults(max_results=3)],
    prompt="You are the RESEARCHER agent ...",
)
result = researcher.invoke({"messages": [HumanMessage(content=user_query)]})
```
This is a **real ReAct agent**. The LLM may decide to call the Tavily search tool zero or many times, examining each result and deciding when it has enough info. Eventually it emits a final AI message — those are the research notes.

If `allow_search=False`: just `llm.invoke(prompt).content` with a "you are a researcher, list facts from your training data" prompt.

State update: `{"research_notes": "..."}`.

#### 4.4b — `writer_node`

Single Groq call:
```
Persona / style guidance: <user's system_prompt>

You are the WRITER agent in a multi-agent pipeline. Use the research notes
below to write a clear, complete, well-structured answer to the user's query...

USER QUERY: ...
RESEARCH NOTES: <whatever Researcher produced>
[on revision: PREVIOUS DRAFT + CRITIC FEEDBACK appended here]
```
State update: `{"draft": "...", "iteration": +1}`.

#### 4.4c — `critic_node`

Single Groq call:
```
You are the CRITIC agent. Review the following draft for accuracy,
completeness, clarity. Output:
ASSESSMENT: ...
VERDICT: REVISE or APPROVE
```
The verdict is parsed with a regex (`re.search(r"VERDICT\s*:\s*(REVISE|APPROVE)", ...)`). State update: `{"critique": "...", "needs_revision": True/False}`.

#### 4.4d — Conditional edge `_route_after_critic`

```python
def _route_after_critic(state):
    if state["needs_revision"] and state["iteration"] <= MAX_REVISIONS:
        return "writer"   # loop back
    return "finalize"
```
- `MAX_REVISIONS = 1` ⇒ the Writer can run at most twice (initial draft + one revision). After that we accept whatever the Writer produced even if the Critic still wants more.
- This is the cyclic edge that elevates the design from "pipeline" to "graph".

#### 4.4e — `finalize_node`

```python
return {"final_answer": state["draft"]}
```
Just promotes the current draft to `final_answer`. Then `END`.

### Step 4.5 — Backend wraps the response

```python
return {
    "response": result["final_answer"],
    "trace": {
        "research_notes": result["research_notes"],
        "draft": result["draft"],
        "critique": result["critique"],
        "iterations": result["iterations"],
    },
}
```

FastAPI serializes that dict to JSON and sends 200 OK.

### Step 4.6 — Streamlit renders

Back in `ui.py`:
```python
if response.status_code == 200:
    data = response.json()
    agent_response = data.get("response", "")
    trace = data.get("trace") or {}

    st.subheader("Final Answer")
    st.markdown(agent_response.replace("\n", "<br>"), unsafe_allow_html=True)

    with st.expander(f"Show agent reasoning trace ({trace.get('iterations', 0)} writer iteration(s))"):
        st.markdown("#### 1. Researcher agent — collected notes")
        st.markdown(trace.get("research_notes", ...) ...)
        st.markdown("#### 2. Writer agent — final draft")
        st.markdown(trace.get("draft", ...) ...)
        st.markdown("#### 3. Critic agent — review")
        st.markdown(trace.get("critique", ...) ...)
```

The user sees the Final Answer, plus a collapsible expander showing what each of the three agents contributed.

---

## 5. File map — who does what

| File | Role |
|---|---|
| [Dockerfile](Dockerfile) | Builds the container image (covered in §1) |
| [.dockerignore](.dockerignore) | Controls what gets copied into the image (excludes `.env`, `.git`, etc.) |
| [setup.py](setup.py) | Reads `requirements.txt` and registers the `app/` package as importable |
| [requirements.txt](requirements.txt) | Pinned-by-name (unpinned by version) Python deps |
| [**app/main.py**](app/main.py) | **Entry point**. Spawns uvicorn (backend) and Streamlit (frontend). Runs as the container's `CMD` |
| [app/backend/api.py](app/backend/api.py) | FastAPI app exposing `POST /chat`. Validates input, dispatches to the agent graph |
| [app/core/ai_agent.py](app/core/ai_agent.py) | LangGraph `StateGraph`. Defines 4 nodes (researcher/writer/critic/finalize) + conditional edge. Compiled once at import |
| [app/frontend/ui.py](app/frontend/ui.py) | Streamlit UI. Builds the request, posts to FastAPI, renders the response + trace |
| [app/config/settings.py](app/config/settings.py) | Reads `os.getenv` for keys, defines `ALLOWED_MODEL_NAMES` whitelist |
| [app/common/logger.py](app/common/logger.py) | Centralised logger. Writes to `logs/log_<date>.log` |
| [app/common/custom_exception.py](app/common/custom_exception.py) | Wraps exceptions with file/line context for clearer error messages |
| [Jenkinsfile](Jenkinsfile) | CI/CD pipeline — clone, SonarQube scan, ECR push, ECS redeploy |
| [custom_jenkins/Dockerfile](custom_jenkins/Dockerfile) | The Jenkins host (`jenkins-dind`) image — Jenkins LTS + Docker CLI |

---

## 6. Sequence diagram — one Ask Agents click

```
You          Browser            Streamlit             FastAPI            ai_agent.py        Groq         Tavily
 │              │                   │                    │                    │              │             │
 │── click ────▶│                   │                    │                    │              │             │
 │              │                   │                    │                    │              │             │
 │              │── re-run script ─▶│                    │                    │              │             │
 │              │                   │                    │                    │              │             │
 │              │                   │── POST /chat ─────▶│                    │              │             │
 │              │                   │  {model, prompt,   │                    │              │             │
 │              │                   │   query, allow_    │                    │              │             │
 │              │                   │   search}          │                    │              │             │
 │              │                   │                    │                    │              │             │
 │              │                   │                    │── validate         │              │             │
 │              │                   │                    │── invoke graph ───▶│              │             │
 │              │                   │                    │                    │              │             │
 │              │                   │                    │                    │── researcher.invoke()      │
 │              │                   │                    │                    │              │             │
 │              │                   │                    │                    │── (search?) ─▶│            │
 │              │                   │                    │                    │              │── search ──▶│
 │              │                   │                    │                    │              │◀── results ─│
 │              │                   │                    │                    │◀── notes ────│             │
 │              │                   │                    │                    │              │             │
 │              │                   │                    │                    │── writer.invoke()─▶│       │
 │              │                   │                    │                    │◀── draft ────│             │
 │              │                   │                    │                    │              │             │
 │              │                   │                    │                    │── critic.invoke()─▶│       │
 │              │                   │                    │                    │◀── verdict ──│             │
 │              │                   │                    │                    │              │             │
 │              │                   │                    │                    │  (REVISE?  → loop back to writer)
 │              │                   │                    │                    │  (APPROVE? → finalize)
 │              │                   │                    │                    │              │             │
 │              │                   │                    │◀── {final_answer,  │              │             │
 │              │                   │                    │      trace}        │              │             │
 │              │                   │                    │                    │              │             │
 │              │                   │◀── 200 OK ─────────│                    │              │             │
 │              │                   │   {response,       │                    │              │             │
 │              │                   │    trace}          │                    │              │             │
 │              │                   │                    │                    │              │             │
 │              │◀── re-render ─────│                    │                    │              │             │
 │              │   Final Answer +  │                    │                    │              │             │
 │              │   trace expander  │                    │                    │              │             │
 │◀── see ──────│                   │                    │                    │              │             │
```

---

## 7. What's the same between local and ECS?

The image and the runtime are identical. The only differences:

| Aspect | Local Docker | ECS Fargate |
|---|---|---|
| Image source | Built locally with `docker build` | Pulled from ECR (`<account>.dkr.ecr.eu-north-1.amazonaws.com/multi-agent-llmops:latest`) |
| Env vars | `--env-file .env` reads `.env` | Container definition's environment block |
| Network | Docker bridge → host port 8501 | AWS VPC → ENI public IP → port 8501 |
| Logs | `docker logs multi-agent` | CloudWatch Logs `/ecs/multi-agent-task` |
| Restart on crash | `--restart unless-stopped` (if set) | ECS service controller auto-replaces failed tasks |

Same container, same Python, same agent graph, same request/response. The interesting plumbing is at the edges (image distribution, network, logging) — the application layer doesn't know or care whether it's on your laptop or in Stockholm.
