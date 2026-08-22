FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY odoo.py config.py tools.py server.py ./

ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

EXPOSE 8000

CMD ["python", "/app/server.py"]
