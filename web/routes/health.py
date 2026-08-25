"""Advanced health dashboard — comprehensive system status."""

import time
from datetime import datetime

import psutil
from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__, url_prefix="/api/health")

_start_time = time.time()


@health_bp.route("", methods=["GET"])
def health_check():
    """Basic health check."""
    return jsonify(
        {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "uptime_seconds": int(time.time() - _start_time),
        }
    )


@health_bp.route("/full", methods=["GET"])
def full_health():
    """Comprehensive system health dashboard."""
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    cpu = psutil.cpu_percent(interval=0.5)
    net = psutil.net_io_counters()

    # Docker status
    docker_status = "unknown"
    try:
        import subprocess

        result = subprocess.run(
            ["docker", "ps", "--filter", "name=grinch", "--format", "{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        docker_status = "running" if "Up" in result.stdout else "down"
    except:
        pass

    return jsonify(
        {
            "status": "healthy" if docker_status == "running" else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "uptime_seconds": int(time.time() - _start_time),
            "system": {
                "cpu_percent": cpu,
                "memory": {
                    "total_gb": round(mem.total / 1024**3, 2),
                    "used_gb": round(mem.used / 1024**3, 2),
                    "percent": mem.percent,
                },
                "disk": {
                    "total_gb": round(disk.total / 1024**3, 2),
                    "free_gb": round(disk.free / 1024**3, 2),
                    "percent": disk.percent,
                },
                "network": {
                    "sent_mb": round(net.bytes_sent / 1024**2, 2),
                    "recv_mb": round(net.bytes_recv / 1024**2, 2),
                },
            },
            "docker": docker_status,
            "version": "3.1.0",
        }
    )


@health_bp.route("/metrics", methods=["GET"])
def metrics():
    """Prometheus-style metrics."""
    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.5)

    metrics_text = f"""# AI-Trading Metrics
grinch_uptime_seconds {int(time.time() - _start_time)}
grinch_cpu_percent {cpu}
grinch_memory_used_bytes {mem.used}
grinch_memory_total_bytes {mem.total}
grinch_memory_percent {mem.percent}
"""
    return metrics_text, 200, {"Content-Type": "text/plain"}
