# Multi-Agent LLMOps

A production-ready multi-agent AI system powered by **Groq LLM** and **LangGraph**, with a full **LLMOps pipeline** — from local development to automated deployment on **AWS ECS Fargate** via Jenkins CI/CD.

---

## Architecture

![Multi AI Agent Workflow](assets/workflow.png)

The system is split into two parts:

**Application Layer**
- User query enters via a **Streamlit** frontend
- Frontend sends a POST request to a **FastAPI** backend
- Backend routes the request to a **LangGraph ReAct agent**
- The agent calls **Groq LLM** (llama3) and optionally uses **Tavily** for live web search
- Response is returned back through the chain to the UI

**CI/CD Pipeline**
- Every `git push` triggers **Jenkins** via GitHub webhook
- Jenkins fetches the code, runs a **SonarQube** code quality scan, builds the Docker image, pushes it to **AWS ECR**, and force-deploys to **AWS ECS Fargate**

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Groq (llama3-70b-8192, llama-3.3-70b-versatile) |
| Agent Framework | LangGraph (ReAct pattern), LangChain |
| Web Search | Tavily |
| Backend API | FastAPI + Uvicorn |
| Frontend UI | Streamlit |
| Containerization | Docker |
| CI/CD | Jenkins (Docker-in-Docker) |
| Code Quality | SonarQube |
| Container Registry | AWS ECR |
| Cloud Deployment | AWS ECS Fargate |

---

## Local Setup

### 1. Clone the repo

```bash
git clone https://github.com/uddipan77/multi-agent-llmops.git
cd multi-agent-llmops
```

### 2. Create a virtual environment

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux/Mac
```

### 3. Install dependencies

```bash
pip install -e .
```

### 4. Create a `.env` file in the project root

```
GROQ_API_KEY=your_groq_api_key
TAVILY_API_KEY=your_tavily_api_key
```

- Get your Groq API key at [console.groq.com](https://console.groq.com)
- Get your Tavily API key at [tavily.com](https://tavily.com)

### 5. Run the app

```bash
python app/main.py
```

This starts two services:
- Streamlit UI → `http://localhost:8501`
- FastAPI backend → `http://localhost:9999`

---

## How to Use

1. Open `http://localhost:8501` in your browser
2. **Define your AI Agent** — write a system prompt describing the agent's role (e.g. "You are a helpful research assistant")
3. **Select a model** — choose between the available Groq LLaMA models
4. **Allow web search** — tick the checkbox to enable live Tavily web search
5. **Enter your query** and click **Ask Agent**
6. The agent's response appears below with markdown formatting

---

## Docker

```bash
# Build
docker build -t multi-agent-llmops .

# Run
docker run -d \
  -p 8501:8501 \
  -p 9999:9999 \
  -e GROQ_API_KEY=your_key \
  -e TAVILY_API_KEY=your_key \
  multi-agent-llmops
```

---

## CI/CD Pipeline

The Jenkins pipeline (defined in `Jenkinsfile`) runs automatically on every push to `main`:

| Stage | What it does |
|---|---|
| Clone | Pulls latest code from GitHub into Jenkins workspace |
| SonarQube Analysis | Scans code quality and reports to SonarQube dashboard |
| Build & Push to ECR | Builds Docker image and pushes to AWS ECR |
| Deploy to ECS Fargate | Triggers a force-new-deployment on the ECS service |

Jenkins and SonarQube both run as Docker containers locally (via WSL). See `custom_jenkins/Dockerfile` for the Jenkins Docker-in-Docker setup.

---

## Project Structure

```
├── app/
│   ├── main.py              # Entry point — starts backend + frontend threads
│   ├── backend/
│   │   └── api.py           # FastAPI /chat endpoint
│   ├── core/
│   │   └── ai_agent.py      # LangGraph ReAct agent
│   ├── frontend/
│   │   └── ui.py            # Streamlit UI
│   ├── config/
│   │   └── settings.py      # Env vars + allowed model list
│   └── common/
│       ├── logger.py
│       └── custom_exception.py
├── custom_jenkins/
│   └── Dockerfile           # Jenkins with Docker-in-Docker
├── assets/
│   └── workflow.png
├── Dockerfile
├── Jenkinsfile
└── requirements.txt
```
