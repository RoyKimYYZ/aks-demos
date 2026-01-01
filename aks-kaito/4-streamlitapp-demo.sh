# streamlit app demo via nginx ingress controller

# Streamlit App
# https://github.com/pauldotyu/kaitochat

workspace_name="workspace-phi-4-mini"
service_name="${workspace_name}.default.svc.cluster.local"
model_name="phi-4-mini-instruct"

kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  labels:
    app: kaitochatdemo
  name: kaitochatdemo
spec:
  replicas: 1
  selector:
    matchLabels:
      app: kaitochatdemo
  template:
    metadata:
      labels:
        app: kaitochatdemo
    spec:
      containers:
      - name: kaitochatdemo
        image: ghcr.io/pauldotyu/kaitochat/kaitochatdemo:latest
        resources: {}
        env:
        - name: MODEL_ENDPOINT
          value: "http://$service_name:80/v1/chat/completions"
        - name: MODEL_NAME
          value: "$model_name"
        ports:
        - containerPort: 8501
---
apiVersion: v1
kind: Service
metadata:
  labels:
    app: kaitochatdemo
  name: kaitochatdemo
spec:
  type: ClusterIP
  ports:
  - port: 80
    protocol: TCP
    targetPort: 8501
  selector:
    app: kaitochatdemo
EOF

# Use the ingress controller public IP for access, e.g. http://<INGRESS_IP>/chat
echo "http://$(kubectl get ingress kaito-ingress -n default -o jsonpath='{.status.loadBalancer.ingress[0].ip}')/chat"


# Use the ingress controller public IP for access, e.g. http://<INGRESS_IP>/chat
echo "http://$(kubectl get ingress kaito-ingress -n default -o json
path='{.status.loadBalancer.ingress[0].ip}')/chat"

# Test Streamlit app endpoint via ingress
INGRESS_IP=$(kubectl get svc ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "INGRESS_IP=$INGRESS_IP"