#!/bin/bash

# Set error handling
set -euo pipefail

# Default values
NUM_REQUESTS=100
ENDPOINT="http://$LOADBALANCER_IP/submit-job"

# Make parallel requests
for i in $(seq 1 $NUM_REQUESTS); do
    curl -X POST "$ENDPOINT" &
done

wait

echo "Done"

