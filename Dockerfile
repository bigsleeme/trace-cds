FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt pyproject.toml README.md LICENSE ./
COPY src ./src
COPY app.py ./
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir .

ENV GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_ANALYTICS_ENABLED=False \
    TRACECDS_CORPUS=/data/corpus.jsonl
EXPOSE 7860
CMD ["python", "app.py"]
