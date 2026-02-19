FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    procps net-tools iproute2 dnsutils curl wget \
    lsof sysstat htop iotop \
    docker.io docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["opsai-tui"]
