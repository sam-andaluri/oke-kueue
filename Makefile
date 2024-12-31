all: build deploy

.PHONY: all

clean:
	kubectl delete -f k8s-backend.yaml
	podman system prune --all --force && podman rmi --all --force
	rm k8s-backend.yaml

build:
	export DOCKER_CONF_JSON_BASE64=`cat ~/.docker/config.json | base64`
	podman build -t phx.ocir.io/hpc_limited_availability/test:backend-kueue .
	podman push phx.ocir.io/hpc_limited_availability/test:backend-kueue
	sed -e "s/DOCKER_CONF_JSON_BASE64/${DOCKER_CONF_JSON_BASE64}/g" k8s-backend.template > k8s-backend.yaml	

deploy:
	kubectl apply -f k8s-backend.yaml
	kubectl apply -f metrics-viewer-rbac.yaml

