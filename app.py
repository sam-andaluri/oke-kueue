from fastapi import FastAPI
from kubernetes import client, config
from cachetools import cached, TTLCache
import urllib.request
import ssl
from typing import Optional
import re
import logging
import sys
import os

TOKEN_TTL = 3600
METRIC_TTL = 60
SERVICE_URL = "https://kueue-controller-manager-metrics-service.kueue-system.svc.cluster.local:8443/metrics"
METRIC_PATTERN = r'kueue_pending_workloads\{cluster_queue="cluster-queue",status="active"\}'

app = FastAPI()

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,  
    format='%(levelname)s: %(message)s'
)

logger = logging.getLogger(__name__)

# Load in-cluster config if running in Kubernetes
if os.getenv("IN_CLUSTER", "true").lower() == "true":
    config.load_incluster_config()
else:
    config.load_kube_config()

batch_v1 = client.BatchV1Api()

# Get service account token, keep it in cache for 60 seconds to reduce file reads
@cached(cache=TTLCache(maxsize=1, ttl=TOKEN_TTL))  
def read_service_token(token_path="/var/run/secrets/kubernetes.io/serviceaccount/token"):
    try:
        with open(token_path, "r") as token_file:
            token = token_file.read().strip()
        return token
    except FileNotFoundError:
        print(f"Token file not found at {token_path}.")
        return None
    except Exception as e:
        print(f"An error occurred while reading the token file: {e}")
        return None

# Get pending workloads from Kueue, keep it in cache for 60 seconds to reduce API calls
@cached(cache=TTLCache(maxsize=1, ttl=METRIC_TTL))
def get_prometheus_metric(metric_name: str="kueue_pending_workloads", url: str = SERVICE_URL) -> Optional[float]:
    try:
        # Skip SSL verification for internal services
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        # Create request with auth header
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {read_service_token()}"}
        )
        
        # Make request with timeout
        response = urllib.request.urlopen(request, context=context, timeout=5)
        metrics_data = response.read().decode('utf-8')
        # Find specific metric in response
        for line in metrics_data.split('\n'):
            if re.search(METRIC_PATTERN, line):
                # Extract value after space
                return float(line.split(' ')[1])
                
        return None
        
    except Exception as e:
        print(f"Error fetching metric {metric_name}: {e}")
        return None

# Create a deployment with a sleep job (representing a workload that needs to be scaled on a queue metric)
def create_deployment(deployment_name: str="dummy-sleep-job", replicas: int=1):
    apps_v1 = client.AppsV1Api()
    deployment = client.V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=client.V1ObjectMeta(name=deployment_name),
        spec=client.V1DeploymentSpec(
            replicas=replicas,
            selector=client.V1LabelSelector(
                match_labels={"app": deployment_name}
            ),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": deployment_name}),
                spec=client.V1PodSpec(
                    containers=[
                        client.V1Container(
                            name="dummy",
                            image="gcr.io/k8s-staging-perf-tests/sleep:v0.1.0",
                            args=["30s"],
                            ports=[client.V1ContainerPort(container_port=80)]
                        )
                    ]
                )
            )
        )
    )
    apps_v1.create_namespaced_deployment(namespace="default", body=deployment)

# Scale the dummy deployment
def scale_deployment(deployment_name: str="dummy-sleep-job", replicas: int=2):
    apps_v1 = client.AppsV1Api()
    deployment = apps_v1.read_namespaced_deployment(name=deployment_name, namespace="default")
    deployment.spec.replicas = replicas
    apps_v1.patch_namespaced_deployment(name=deployment_name, namespace="default", body=deployment)

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI and Gunicorn!"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

# Submit a job to the local queue
# Added FastAPI endpoint to submit a job to the local queue for testing purposes
@app.post("/submit-job")
def submit_job(queue_name: str = "local-queue", job_prefix: str = "job-"):    
    logger.info("Received metric data: %d", get_prometheus_metric())
    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(generate_name=job_prefix),
        spec=client.V1JobSpec(
            parallelism=1,
            completions=1,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(
                    labels={"kueue.x-k8s.io/queue-name": queue_name}
                ),
                spec=client.V1PodSpec(
                    containers=[
                        client.V1Container(
                            name="dummy-job",
                            image="python:3.11-slim",
                            command=["python", "-c", "print('Hello from Python and Kueue!')"]
                        )
                    ],
                    restart_policy="Never"
                )
            )
        )
    )

    response = batch_v1.create_namespaced_job(namespace="default", body=job)
    return {"status": "submitted", "queue": queue_name, "job": response.metadata.name}

