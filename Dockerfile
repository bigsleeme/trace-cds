FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt pyproject.toml README.md LICENSE ./
COPY src ./src
COPY app.py ./
COPY chat ./chat
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir -e ".[dense]"

ENV TRACECDS_HOST=0.0.0.0 \
    TRACECDS_CORPUS=/data/corpus.jsonl
EXPOSE 7860
CMD ["python", "app.py"]
