### Pre-requisites 
1. Install podman `brew install podman` ( MacOS )
2. Install kubectl `curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/darwin/arm64/kubectl;chmod +x kubectl;sudo mv kubectl /usr/local/bin/`
3. Create a container registry in OCI Console. Get regional OCIR endpoint e.g. phx.ocir.io
4. Create an auth token in OCI Console.
5. Login to phx.ocir.io using `podman login phx.ocir.io`. User name is <tenancy>/<OCI-user-name> e..g hpc_limited_availability/sam
6. Create an OKE cluster and download kubeconfig
7. Install krew for plugin management `https://krew.sigs.k8s.io/docs/user-guide/setup/install/`

### Install kueue and dependencies
1. Install kueue `kubectl apply --server-side -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.10.0/manifests.yaml`
2. Wait till install finishes `kubectl wait deploy/kueue-controller-manager -n kueue-system --for=condition=available --timeout=5m`
3. Install prometheus operator `kubectl create -f https://github.com/prometheus-operator/prometheus-operator/releases/download/v0.79.2/bundle.yaml`
4. Install kueue/prometheus `kubectl apply --server-side -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.10.0/prometheus.yaml`
5. Install kueue priority plugin `kubectl apply --server-side -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.10.0/visibility-apf.yaml`

### Build and push the application image
1. [uv](https://docs.astral.sh/uv/getting-started/installation/) is the package manager used for this project.
2. When adding new or removing dependencies use the following commands as an example
   ```
   uv add prometheus_client
   uv remove prometheus-api-client
   uv pip compile pyproject.toml -o requirements.txt
   ```
3. Build app image `podman build -t phx.ocir.io/hpc_limited_availability/test:backend-kueue .`
4. Push app image to OCIR `podman push phx.ocir.io/hpc_limited_availability/test:backend-kueue`
5. `Makefile` helps organizing commands for building images, deploying. `make clean` to delete local images and generated manifests. `make` to rebuild image, push image to OCIR and deploy.
6. There may be times when you just need to run `make` to incrementally add features. You can scale deployment to 0 and scale it up to more replicas to force deployment to pull the new image. 
   ```
   kubectl scale deployment.apps/backend-kueue --replicas=0
   kubectl scale deployment.apps/backend-kueue --replicas=1
   ```

### Create Kueue objects
*NOTE* This is an example, production deployment requires more planning and design
1. Create a default flavor `kubectl apply -f default-flavor.yaml`
2. Create a cluster queue `kubectl apply -f cluster-queue.yaml`
3. Create a local queue `kubectl apply -f local-queue.yaml`

### Deploy App
1. Modify the `k8s-backend.template` to specify the image repo and image tag.
2. Generate secret and manifest all example objects.
    ```
    DOCKER_CONF_JSON_BASE64=`cat ~/.docker/config.json | base64`
    sed -e "s/DOCKER_CONF_JSON_BASE64/$DOCKER_CONF_JSON_BASE64/g" k8s-backend.template > k8s-backend.yaml
    ```
 3. Deploy app `kubectl apply -f k8s-backend.yaml`
 4. Find the Load Balancer ip address `kubectl get svc`    
    Output looks like below and 141.148.171.46 is the public ip of the load balancer. In your case this would be different.
    ```
    kubectl get svc
    NAME                    TYPE           CLUSTER-IP      EXTERNAL-IP      PORT(S)             AGE
    backend-kueue-service   LoadBalancer   10.96.245.223   141.148.171.46   80:32484/TCP        19m
    kubernetes              ClusterIP      10.96.0.1       <none>           443/TCP,12250/TCP   8d
    prometheus-operator     ClusterIP      None            <none>           8080/TCP            27h
    ```
 5. Test app by running curl commands

    ```
    LOADBALANCER_IP=`kubectl get service backend-kueue-service -o jsonpath='{.status.loadBalancer.ingress[0].ip}'`
	  curl -s http://${LOADBALANCER_IP}/health | jq -r '.status=="ok"'
    ```

    ```
    curl http://${LOADBALANCER_IP}/
    {"message":"Hello from FastAPI and Gunicorn!"}

    curl http://${LOADBALANCER_IP}/health
    {"status":"ok"}    
    ```
  6. Submit a kueue job via FastAPI

    ```
    curl -X POST http://${LOADBALANCER_IP}/submit-job
    {"status":"submitted","queue":"local-queue","job":"job-c5k6l"}    
    ```
  7. Submit a kueue job using manifest `kubectl apply -f sample-job.yaml`

  8. Check the status of the job
    ```
    kubectl get jobs
    NAME          STATUS     COMPLETIONS   DURATION   AGE
    job1          Complete   1/1           7s         10s
    ```

### Access Kueue Metrics
1. Create a service account which gives access to `/metrics` url `kubectl apply -f metrics-viewer-rbac.yaml`
2. Create a token from the service account 
```
export TOKEN=`kubectl create token metrics-viewer -n kueue-system`
```
3. Port forward the metrics service
```
kubectl port-forward -n kueue-system svc/kueue-controller-manager-metrics-service 8443:8443
```
4. Open another terminal tab/window and run
```
curl -k https://localhost:8443/metrics -H "Authorization: Bearer $TOKEN"
```
5. See `app.py` file and `get_prometheus_metric` method for an example that accesses the metrics programmatically. This file also includes a method `create_deployment` for creating a deployment and `scale_deployment` for writing custom scaling algorithm.

### Horizontal Pod Autoscaler (HPA) integration
![diagram](images/HPACustomMetrics.png)
1. Use the above diagram understand the flow and identify the changes. The :x: mark in the diagram indicates components we need to configure. The :heavy_check_mark: in the diagram indicates configuration that was included in the install steps.
2. Clone prometheus-operator https://github.com/prometheus-operator/kube-prometheus.git and make change to this file  https://github.com/prometheus-operator/kube-prometheus/blob/5f0e7a6eee2fc91509a35fb2cce7989cd1bf7c9c/manifests/prometheus-prometheus.yaml#L48
3. Clone prometheus-adapter repo `git clone https://github.com/kubernetes-sigs/prometheus-adapter.git` and make change to this file https://github.com/kubernetes-sigs/prometheus-adapter/blob/c2ae4cdaf160363151f746e253789af89f8b6c49/deploy/manifests/config-map.yaml#L3 using an example from https://github.com/kubernetes-sigs/prometheus-adapter/blob/c2ae4cdaf160363151f746e253789af89f8b6c49/docs/sample-config.yaml#L70

### Cluster Autoscaler

### Vertical Pod Autoscaler (VPA) integration

### Multidimensional Pod Autoscaler (MdPA) integration

### References
1. Prometheus Operator https://github.com/prometheus-operator/prometheus-operator
2. Kueue job example https://kueue.sigs.k8s.io/docs/tasks/run/python_jobs/
3. Install krew plugin manager https://krew.sigs.k8s.io/docs/user-guide/setup/install/
4. kueuectl https://kueue.sigs.k8s.io/docs/reference/kubectl-kueue/installation/
5. Prometheus Adapter configuration walkthru https://github.com/kubernetes-sigs/prometheus-adapter/blob/master/docs/config-walkthrough.md
6. Prometheus Adapter configuration reference https://github.com/kubernetes-sigs/prometheus-adapter/blob/master/docs/config.md
7. External metrics https://github.com/kubernetes-sigs/prometheus-adapter/blob/master/docs/externalmetrics.md
8. Kueue metrics https://kueue.sigs.k8s.io/docs/reference/metrics/#optional-metrics
