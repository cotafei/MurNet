"""
MURNET DOCKER CONFIGURATION v5.0
Docker и Docker Compose конфигурация для VDS
"""

DOCKERFILE = """
# Murnet Node Docker Image
FROM python:3.11-slim

# Установка зависимостей
RUN apt-get update && apt-get install -y \\
    gcc \\
    libffi-dev \\
    libssl-dev \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копирование requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY . .

# Создание директории для данных
RUN mkdir -p /data

# Открываем порты
EXPOSE 8888/udp
EXPOSE 8080/tcp
EXPOSE 9090/tcp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\
    CMD python -c "import requests; requests.get('http://localhost:8080/health')" || exit 1

# Запуск
ENTRYPOINT ["python", "-m", "murnet"]
CMD ["--config", "/data/murnet.yaml", "--data-dir", "/data"]
"""

DOCKER_COMPOSE = """
version: '3.8'

services:
  murnet:
    build: .
    container_name: murnet-node
    restart: unless-stopped
    
    ports:
      - "8888:8888/udp"    # P2P порт
      - "8080:8080/tcp"    # API
      - "9090:9090/tcp"    # Prometheus metrics
    
    volumes:
      - ./data:/data
      - ./config:/config:ro
    
    environment:
      - MURNET_PROFILE=vds
      - MURNET_LOG_LEVEL=INFO
      - MURNET_API_HOST=0.0.0.0
    
    # Resource limits для VDS
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 128M
    
    # Логирование
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "5"
    
    networks:
      - murnet

  # Опционально: Prometheus для мониторинга
  prometheus:
    image: prom/prometheus:latest
    container_name: murnet-prometheus
    restart: unless-stopped
    ports:
      - "9091:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    networks:
      - murnet
    profiles:
      - monitoring

  # Опционально: Grafana для визуализации
  grafana:
    image: grafana/grafana:latest
    container_name: murnet-grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
      - ./monitoring/grafana/datasources:/etc/grafana/provisioning/datasources:ro
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    networks:
      - murnet
    profiles:
      - monitoring

volumes:
  prometheus-data:
  grafana-data:

networks:
  murnet:
    driver: bridge
"""

PROMETHEUS_CONFIG = """
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'murnet'
    static_configs:
      - targets: ['murnet:9090']
    metrics_path: /metrics
"""

class DockerGenerator:
    """Генератор Docker конфигураций"""
    
    @staticmethod
    def generate_dockerfile(path: str = "Dockerfile"):
        """Генерация Dockerfile"""
        with open(path, 'w') as f:
            f.write(DOCKERFILE.strip())
        print(f"✓ Generated {path}")
    
    @staticmethod
    def generate_compose(path: str = "docker-compose.yml"):
        """Генерация docker-compose.yml"""
        with open(path, 'w') as f:
            f.write(DOCKER_COMPOSE.strip())
        print(f"✓ Generated {path}")
    
    @staticmethod
    def generate_prometheus_config(path: str = "monitoring/prometheus.yml"):
        """Генерация конфига Prometheus"""
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        with open(path, 'w') as f:
            f.write(PROMETHEUS_CONFIG.strip())
        print(f"✓ Generated {path}")
    
    @staticmethod
    def generate_all(output_dir: str = "."):
        """Генерация всех конфигов"""
        DockerGenerator.generate_dockerfile(f"{output_dir}/Dockerfile")
        DockerGenerator.generate_compose(f"{output_dir}/docker-compose.yml")
        DockerGenerator.generate_prometheus_config(f"{output_dir}/monitoring/prometheus.yml")
        
        print(f"\n📦 Docker configuration generated in {output_dir}/")
        print("Commands:")
        print("  docker-compose up -d          # Start node")
        print("  docker-compose --profile monitoring up -d  # With monitoring")
        print("  docker-compose logs -f        # View logs")


# Docker entrypoint script
ENTRYPOINT_SCRIPT = """#!/bin/bash
# Murnet Docker Entrypoint

set -e

# Создание директорий
mkdir -p /data/dht /data/messages /data/identity

# Генерация конфига если не существует
if [ ! -f /data/murnet.yaml ]; then
    echo "Generating default configuration..."
    cat > /data/murnet.yaml << EOF
network:
  bind_host: 0.0.0.0
  port: 8888
  bootstrap_nodes: ${BOOTSTRAP_NODES:-[]}

storage:
  data_dir: /data
  max_size_mb: 1000

api:
  enabled: true
  host: 0.0.0.0
  port: 8080

vds:
  monitoring_enabled: true
  prometheus_port: 9090
  log_rotation: true
EOF
fi

# Запуск
exec python -m murnet "$@"
"""

if __name__ == "__main__":
    DockerGenerator.generate_all()