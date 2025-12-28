# streamlit app demo via nginx ingress controller
#   

# Use the ingress controller public IP for access, e.g. http://<INGRESS_IP>/chat
echo "http://$(kubectl get ingress kaito-ingress -n default -o json
path='{.status.loadBalancer.ingress[0].ip}')/chat"

# Test Streamlit app endpoint via ingress
INGRESS_IP=$(kubectl get svc ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "INGRESS_IP=$INGRESS_IP"