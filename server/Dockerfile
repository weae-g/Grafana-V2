FROM public.ecr.aws/docker/library/python:3.13-slim
RUN apt-get update && \
    apt-get upgrade -y && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY receiver.py ping_monitor.py ./
CMD ["python", "receiver.py"]
