# Docker Setup Guide for Autonomous Coding Agent

This guide explains how to run the monitoring stack (Prometheus, Grafana) using Docker.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop) installed
- Docker running (start Docker Desktop)

## Quick Start

### Option 1: Run with Docker Compose (Recommended)

```bash
# Start all services (backend + Prometheus + Grafana)
docker-compose up -d
```

This will start:
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3001 (admin/admin)
- **Backend API**: http://localhost:8000

### Option 2: Run Individual Containers

#### Prometheus

```bash
# Run Prometheus container
docker run -d \
  --name prometheus \
  -p 9090:9090 \
  -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus:latest
```

#### Grafana

```bash
# Run Grafana container
docker run -d \
  --name grafana \
  -p 3001:3000 \
  -e GF_SECURITY_ADMIN_PASSWORD=admin \
  -v grafana-data:/var/lib/grafana \
  grafana/grafana:latest
```

## Configuration Files

### prometheus.yml

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'autonomous-agent'
    static_configs:
      - targets: ['host.docker.internal:8000']
    metrics_path: '/metrics'
```

### Docker Compose File

```yaml
version: '3.8'

services:
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
    networks:
      - agent-network

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    ports:
      - "3001:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_SERVER_ROOT_URL=http://localhost:3001
    volumes:
      - grafana-data:/var/lib/grafana
    depends_on:
      - prometheus
    networks:
      - agent-network

networks:
  agent-network:
    driver: bridge

volumes:
  grafana-data:
```

## Accessing Services

| Service | URL | Credentials |
|---------|-----|-------------|
| Prometheus | http://localhost:9090 | N/A |
| Grafana | http://localhost:3030 | admin / admin |
| Backend API | http://localhost:8000 | N/A |
| API Docs | http://localhost:8000/docs | N/A |

## Grafana Dashboard Setup

1. Open Grafana at http://localhost:3030
2. Login with `admin` / `admin`
3. Add Prometheus as data source:
   - Go to Configuration > Data Sources
   - Add Prometheus
   - URL: `http://prometheus:9090`
4. Import the dashboard:
   - Go to Dashboards > Import
   - Upload `grafana_dashboard.json` file
   - Or use the JSON file in this project

### Import Dashboard

Import a pre-built dashboard by going to Dashboards > Import:
1. Upload `grafana_dashboard.json` from this project
2. Select Prometheus as data source

The dashboard includes:
- Workflow Rate (per second)
- P95 Duration
- Success Rate %
- Tool Call Rate
- Error Rate
- Total Workflows
- Total Tool Calls
- Total Errors
- Total Iterations

## Verify Metrics are Being Scraped

1. Open Prometheus at http://localhost:9090
2. Go to Status > Targets
3. Verify `autonomous-agent` target is UP
4. Try querying metrics in the Console tab

## Common Issues

### Prometheus Can't Reach Backend

If you see target as DOWN:
- Ensure backend is running: `python backend/run.py`
- Check firewall settings
- Try `host.docker.internal` instead of `localhost` on Windows

### Grafana Login Issues

Reset Grafana admin password:
```bash
docker run --rm -it grafana/grafana grafana-cli admin reset-admin-password newpassword
```

### Clean Up

```bash
# Stop all containers
docker-compose down

# Remove volumes (data will be lost)
docker-compose down -v

# Remove all containers
docker rm -f prometheus grafana
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PROMETHEUS_PORT` | Prometheus port | 9090 |
| `GRAFANA_PORT` | Grafana port | 3001 |
| `BACKEND_PORT` | Backend API port | 8000 |

## Production Considerations

For production deployment:
1. Use persistent volumes for Prometheus and Grafana data
2. Enable authentication on all services
3. Use reverse proxy (nginx) for SSL termination
4. Set up alerting rules in Prometheus
5. Configure Grafana alerts for notifications
