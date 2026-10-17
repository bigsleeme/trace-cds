# Self-hosting TraceCDS on your own domain

Everything in this stack is open source:

| Component | Role | License |
| --- | --- | --- |
| TraceCDS | Retrieval, guardrails, web app | Apache-2.0 |
| Gradio | Web interface | Apache-2.0 |
| Ollama | Runs the language model locally | MIT |
| Qwen2.5-7B-Instruct (default model) | Summarizes label passages | Apache-2.0 |
| OLMo 2 7B (alternative) | Fully open model: weights, data, code | Apache-2.0 |
| Caddy | HTTPS and reverse proxy | Apache-2.0 |
| openFDA / DailyMed | Drug labeling data | U.S. government data |

No question is sent to any outside AI service. The model runs on your server.

## 1. Server

Any Linux VPS works. For the default 7B model on CPU only, use at least **4 vCPUs and 8 GB RAM** (16 GB is more comfortable) and **30 GB disk**. Expect LLM summaries to take several seconds to tens of seconds on CPU. The "Quoted from label" mode needs no model and answers almost instantly. A small GPU makes LLM summaries much faster but isn't required. On a server with 4 GB RAM, set `TRACECDS_MODEL=qwen2.5:1.5b-instruct`.

## 2. Domain

At your domain registrar, create an **A record** pointing your domain (for example `tracecds.yourdomain.com`) to the server's public IP address. Wait until it resolves (`ping tracecds.yourdomain.com`).

## 3. Install and start

```bash
# On the server (Ubuntu):
curl -fsSL https://get.docker.com | sh

git clone https://github.com/bigsleeme/trace-cds.git
cd trace-cds
cp .env.example .env
nano .env            # DOMAIN=tracecds.com, www.tracecds.com (optionally TRACECDS_MODEL)

docker compose up -d --build
docker compose logs -f model-pull   # first run downloads the model (~4.7 GB)
```

Open `https://your-domain`. Caddy obtains the HTTPS certificate on first visit. The app downloads FDA labels for the indexed drugs on first start.

## 4. Firewall

Allow only SSH (22), HTTP (80), and HTTPS (443). Ollama is not exposed to the internet; only the app container can reach it.

```bash
sudo ufw allow 22 && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
```

## 5. Updating

```bash
git pull
docker compose up -d --build
```

To refresh labels, delete the cached corpus and restart the app:

```bash
docker compose exec app rm /data/corpus.jsonl && docker compose restart app
```

## Privacy

- Questions are processed on your server and are not stored by TraceCDS. Gradio analytics are disabled, and Caddy access logs are discarded.
- The interface asks users not to enter patient identifiers, and questions containing common identifiers (record numbers, dates of birth, SSNs, emails, phone numbers) are declined before processing.
- Keep the "Research prototype. Not for clinical use." banner. TraceCDS is not a medical device.
