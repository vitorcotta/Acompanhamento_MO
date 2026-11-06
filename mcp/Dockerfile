FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py reveal.py ./

ENV MO_API_BASE=http://app:8000
ENV MO_MCP_SALT_FILE=/salt/salt

# O container fica parado (idle); o Claude Desktop entra via "docker exec -i"
# e roda "python server.py" por sessão, igual ao padrão usado em garmin-ia.
CMD ["tail", "-f", "/dev/null"]
