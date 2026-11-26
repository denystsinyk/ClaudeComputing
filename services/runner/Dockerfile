FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system runner \
    && useradd --system --gid runner runner

COPY runner.py /app/runner.py
USER runner
ENV PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["python", "/app/runner.py"]
