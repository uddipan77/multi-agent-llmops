# Build triggers — why pushes don't auto-build today

## Current state

Pushing to `main` does **not** auto-trigger a Jenkins build. Every deploy needs a manual **Build Now** click in the Jenkins UI.

Two things have to be in place for `git push` → Jenkins build to work, and we have neither right now:

1. **The Jenkins job is configured to listen for changes** (a "Build Triggers" checkbox in the job config).
2. **Jenkins is reachable by whatever's notifying it** — either GitHub pushing a webhook to Jenkins, or Jenkins itself polling git.

Jenkins in this project runs on `localhost:8080` inside a Docker container on the developer laptop. GitHub.com can't reach `localhost:8080` from the public internet, so a webhook configured in GitHub would never deliver. That's why we click Build Now manually for now.

---

## Option A — GitHub webhook + tunnel (fast, "real" CI)

Push to GitHub → GitHub fires HTTP POST → public tunnel forwards it to your laptop → Jenkins → build starts within seconds.

**Steps:**

1. Expose `localhost:8080` to the public internet with a tunnel. Free options:
   - **Cloudflare Tunnel** (recommended — stable URL, no time limits):
     ```bash
     cloudflared tunnel --url http://localhost:8080
     ```
     Gives you `https://<random>.trycloudflare.com`.
   - **ngrok**:
     ```bash
     ngrok http 8080
     ```
     Free tier rotates the URL on every restart.

2. In GitHub: **repo → Settings → Webhooks → Add webhook**:
   - Payload URL: `https://<your-tunnel-url>/github-webhook/` (trailing slash and `github-webhook/` path are required by Jenkins)
   - Content type: `application/json`
   - Secret: optional but recommended
   - Trigger: "Just the push event"
   - Active: ☑

3. In Jenkins: **`multi-agent-pipeline` → Configure → Build Triggers → ☑ "GitHub hook trigger for GITScm polling" → Save**.

**Trade-off:** every time you stop/restart the tunnel, the URL changes (unless you set up a Cloudflare named tunnel or pay for ngrok). For a laptop-hosted Jenkins this is the reality.

---

## Option B — Jenkins polls GitHub (zero infrastructure, ~slow)

No webhook, no tunnel. Jenkins itself wakes up every N minutes and asks GitHub "anything new?". If yes → build.

**Steps:**

In Jenkins: **`multi-agent-pipeline` → Configure → Build Triggers → ☑ "Poll SCM"** → Schedule:

```
H/2 * * * *
```

(Every ~2 minutes, jittered. `H` spreads load if you have many jobs.)

**Trade-offs:**
- Lag of up to 2 minutes between push and build start.
- No inbound traffic to your laptop required.
- Each check is one cheap `git ls-remote` — negligible cost.

Good enough for a learning/demo project.

---

## Recommendation

Start with **Option B (Poll SCM)** — one checkbox, works immediately, no extra services to manage. If you later want the snappiness of "push and the build starts within 2 seconds," graduate to Cloudflare Tunnel + webhook (Option A).

---

## What a real production setup looks like

For comparison, the way professional teams typically run this:

- Jenkins runs on a publicly-reachable host (an EC2 instance in the same VPC as the ECS cluster, an on-prem server with port forwarded, etc.) — **not a laptop**.
- GitHub webhooks point straight at that host; a webhook secret validates the payload signature.
- The pipeline runs on every push to `main` and on every PR.
- Branch-protection rules in GitHub require the Jenkins build (and the SonarQube quality gate) to pass before merging to `main`.

For this project, the equivalent would be putting Jenkins on a small EC2 instance in `eu-north-1`. Same `Jenkinsfile`, same plugins, same credentials — just a different host. That's the natural next step if you want this to feel like a real CI/CD setup rather than a demo.
