FROM python:3.12-slim

WORKDIR /app
COPY server.py fixtures.json ./

EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=2s --start-period=2s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=1).read()" || exit 1

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8080"]
