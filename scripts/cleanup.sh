#!/bin/bash
# Safe disk cleanup — never touches volumes or running containers
echo "Disk before: $(df -h / | tail -1)"
docker builder prune -f
docker system prune -f --volumes=false
docker image prune -af
echo "Disk after:  $(df -h / | tail -1)"
