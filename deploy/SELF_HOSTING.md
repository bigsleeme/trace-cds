# Self-hosting TraceCDS on your own domain

Everything in this stack is open source:

| Component | Role | License |
| --- | --- | --- |
| TraceCDS | Retrieval, guardrails, web app, homepage | Apache-2.0 |
| Gradio | Chat interface | Apache-2.0 |
| Ollama | Runs the language model locally | MIT |
| SearXNG | Self-hosted web search (queries Google, Bing, DuckDuckGo, PubMed) | AGPL-3.0 |
| BioMistral-7B-DARE (default model) | Summarizes label passages | Apache-2.0 |
| BAAI/bge-m3 (dense retrieval) | Hybrid retrieval alongside BM25 | MIT |
| BAAI/bge-reranker-v2-m3 | Reranks retrieved passages before generation | Apache-2.0 |
| OLMo 2 7B / Mistral 7B (alternative models) | Fully open general-purpose alternatives | Apache-2.0 |
| Caddy | HTTPS and reverse proxy | Apache-2.0 |
| openFDA / DailyMed | Drug labeling data | U.S. government data |

Retrieval, source trust-checking, and the guardrails run on your server; web searches go out through your own SearXNG. Answer generation talks to whatever OpenAI-compatible endpoint you set in `TRACECDS_LLM_URL` / `TRACECDS_MODEL` / `TRACECDS_LLM_API_KEY`: point it at a hosted API (e.g. DeepInfra) for speed, in which case questions are sent there to generate the answer, or at a self-hosted server (Ollama, vLLM, llama.cpp) to keep generation on your own infrastructure. The "Quoted from label" mode uses no model and never leaves your server.

## 1. Server

With the default hybrid retrieval + reranking pipeline (`pip install -e ".[dense]"`, used automatically by the Docker image) and the default 7B model, all resident at once on CPU, budget **~10 GB RAM**: Ollama + the model (~6 GB), the embedder and reranker (~3 GB), SearXNG and Caddy (~1.5 GB). Recommended: **Hetzner Cloud CPX41 (4 vCPU, 16 GB RAM) in an EU region (Falkenstein or Helsinki) — about $29/month**; the same spec in Hetzner's US region costs several times more, and 16 GB leaves comfortable headroom over the ~10 GB estimate. **30 GB disk** is enough.

To cut cost further, drop to a smaller box (e.g. Hetzner CPX31, 8 GB RAM, ~$16/month in an EU region) by either skipping the dense/rerank extras (plain `pip install .`, BM25-only retrieval) or using a lighter quantization, e.g. `TRACECDS_MODEL=hf.co/mradermacher/BioMistral-Instructv0.2-7B-DARE-GGUF:Q3_K_S`. Expect LLM summaries to take several seconds to tens of seconds on CPU either way. The "Quoted from label" mode needs no model and answers almost instantly. A small GPU makes LLM summaries much faster but isn't required.

## 2. Domain

This deploys two sites on one server: the static marketing homepage, and the chat app on its own subdomain. At your domain registrar, create **two A records** pointing at the server's public IP address: your root domain (e.g. `tracecds.com`) and the chat subdomain (e.g. `chat.tracecds.com`). Wait until both resolve (`ping tracecds.com`, `ping chat.tracecds.com`).

## 3. Install and start

```bash
# On the server (Ubuntu):
curl -fsSL https://get.docker.com | sh

git clone https://github.com/bigsleeme/trace-cds.git
cd trace-cds
cp .env.example .env
openssl rand -hex 32 # copy the output into SEARXNG_SECRET in .env
nano .env            # DOMAIN=tracecds.com, www.tracecds.com / CHAT_DOMAIN=chat.tracecds.com / SEARXNG_SECRET=...

docker compose up -d --build
docker compose logs -f model-pull   # first run downloads the model (~4.4 GB)
```

Open `https://your-domain` for the homepage and `https://chat.your-domain` for the chat app. Caddy obtains an HTTPS certificate for each on first visit. The app downloads FDA labels for the indexed drugs on first start.

## 4. Firewall

Allow only SSH (22), HTTP (80), and HTTPS (443). Ollama and SearXNG are not exposed to the internet; only the app container can reach them.

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

## Web search notes

Search engines sometimes rate-limit servers. If web answers stop appearing, check `docker compose logs searxng`. SearXNG combines several engines, so it keeps working if one engine blocks it. You can change engines in `deploy/searxng/settings.yml`.
