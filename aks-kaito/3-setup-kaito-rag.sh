# https://kaito-project.github.io/kaito/docs/rag/

# Install RAG engine helm chart
helm repo add kaito https://kaito-project.github.io/kaito/charts/kaito
helm repo update
helm upgrade --install kaito-ragengine kaito/ragengine \
  --namespace kaito-ragengine \
  --create-namespace

# Verify installation
helm list -n kaito-ragengine

# Check pods status
kubectl get pods -n kaito-ragengine
kubectl describe deploy ragengine -n kaito-ragengine

kubectl get svc -n default -o wide && echo "---" && kubectl get svc -A | grep -i "phi\|workspace"
# The service name is workspace-phi-4-mini, so the in-cluster DNS is http://workspace-phi-4-mini.default.svc.cluster.local/v1/chat/completions

# Get the AKS cluster FQDN
az aks show -g aks-solution -n rkaksdev --query fqdn -o tsv
# Go to bge-small-ragengine.yaml and update the workspaceBaseUrl with the FQDN above
# Update url: "http://workspace-phi-4-mini.default.svc.cluster.local/v1/chat/completions"
# example: https://github.com/kaito-project/kaito/blob/main/examples/RAG/kaito_ragengine_phi_3.yaml

# Deploy BGE Small RAGEngine that uses the BGE Small model for RAG
kubectl apply -f bge-small-ragengine.yaml


# Verify deployment of the RAGEngine
kubectl get pods -n kaito-ragengine -o wide

# Check 
kubectl describe deploy ragengine-example -n default

# cleanup options:
# kubectl delete -f bge-small-ragengine.yaml
# helm uninstall kaito-ragengine -n kaito-ragengine

# https://kaito-project.github.io/kaito/docs/rag#persistent-storage-optional
# Create a PVC that can be used for vector DB persistence.
# NOTE: In the currently installed KAITO RAGEngine CRD (0.7.x), `.spec.storage.*` fields are not accepted
# (strict decoding). This manifest therefore creates ONLY the PVC.

kubectl apply -f pvc-ragengine-vector-db.yaml

# option: kubectl delete -f pvc-ragengine-vector-db.yaml

# verify PVC creation persistentvolumeclaim/pvc-ragengine-vector-db 
kubectl get pvc -n default
kubectl describe deploy kaito-ragengine -n kaito-ragengine

# Verify ragengine.kaito.sh/ragengine-with-storage
kubectl get ragengine -n default -o yaml | grep -A 5 "storage:" 


# Delete Ragengine


# Check ingress rules only
kubectl get ingress kaito-ingress -n default -o jsonpath='{.spec.rules}' | jq .

# Test endpoints via ingress
INGRESS_IP="${INGRESS_IP:-$(kubectl get svc ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}')}"
if [ -z "$INGRESS_IP" ]; then
  echo "ERROR: INGRESS_IP is empty. Is ingress-nginx installed and has an external IP?" >&2
  kubectl get svc -n ingress-nginx -o wide >&2 || true
  exit 1
fi
export INGRESS_IP
echo "INGRESS_IP=$INGRESS_IP"

# Choose which ingress path to use:
# - rag: routes to ragengine-with-storage with persistent volume DB
# - rag-nostorage: routes to ragengine-example with no persistent volume DB
RAG_PATH="${RAG_PATH:-rag-nostorage}"
export RAG_PATH
echo "RAG_PATH=$RAG_PATH"

# List indexes
curl -sS "http://$INGRESS_IP/$RAG_PATH/indexes" | jq


# Create index (through ingress)
curl -sS -X POST "http://$INGRESS_IP/$RAG_PATH/index" \
  -H "Content-Type: application/json" \
  -d '{
    "index_name": "rag_index",
    "documents": [
      {
        "text": "",
        "metadata": {
          "author": "Roy Kim"
        }
      },
      {
        "text": "Retrieval Augmented Generation (RAG) is an architecture that augments the capabilities of a Large Language Model (LLM) like ChatGPT by adding an information retrieval system that provides grounding data.",
        "metadata": {
          "author": "kaito"
        }
      }
    ]
  }' | jq


# index code documents with split_type code

RESPONSE=$(curl -sS -X POST "http://$INGRESS_IP/$RAG_PATH/index" \
  -H "Content-Type: application/json" \
  -d '{
    "index_name": "code_index",
    "documents": [
      {
        "text": "def calculate_sum(a, b):\n    \"\"\"Add two numbers together.\"\"\"\n    return a + b\n\ndef calculate_product(a, b):\n    \"\"\"Multiply two numbers.\"\"\"\n    return a * b\n\nclass Calculator:\n    def __init__(self):\n        self.history = []\n\n    def add(self, a, b):\n        result = a + b\n        self.history.append(result)\n        return result",
        "metadata": {
          "split_type": "code",
          "language": "python",
          "author": "demo",
          "source": "calculator.py"
        }
      },
      {
        "text": "function greet(name) {\n  return `Hello, ${name}!`;\n}\n\nconst sum = (a, b) => a + b;\n\nclass Person {\n  constructor(name) {\n    this.name = name;\n  }\n\n  sayHello() {\n    return greet(this.name);\n  }\n}",
        "metadata": {
          "split_type": "code",
          "language": "javascript",
          "author": "demo",
          "source": "utils.js"
        }
      }
    ]
  }')

# Print formatted response
echo "$RESPONSE" | jq

# Extract first doc_id (Python document)
DOC_ID_0=$(echo "$RESPONSE" | jq -r '.[0].doc_id // .doc_ids[0] // empty')
echo "Python doc_id: $DOC_ID_0"

# Extract second doc_id (JavaScript document)
DOC_ID_1=$(echo "$RESPONSE" | jq -r '.[1].doc_id // .doc_ids[1] // empty')
echo "JavaScript doc_id: $DOC_ID_1"

# Extract all doc_ids as array
ALL_DOC_IDS=$(echo "$RESPONSE" | jq -r '.[].doc_id // .doc_ids[] // empty')
echo "All doc_ids:"
echo "$ALL_DOC_IDS"

# examples for listing documents:
curl -X GET "http://$INGRESS_IP/$RAG_PATH/indexes/rag_index/documents?limit=5&offset=0&max_text_length=500" | jq

curl -X GET "http://$INGRESS_IP/$RAG_PATH/indexes/code_index/documents?limit=5&offset=0&max_text_length=500" | jq

# with pagination (next 5 documents)
curl -X GET "http://$INGRESS_IP/$RAG_PATH/indexes/rag_index/documents?limit=5&offset=5&max_text_length=500" | jq

# List all documents with full text
curl -X GET "http://$INGRESS_IP/$RAG_PATH/indexes/rag_index/documents?limit=100&max_text_length=5000" | jq

# list available indexes
curl -X GET "http://$INGRESS_IP/$RAG_PATH/indexes" | jq

# Update Document by ID
curl -X POST "http://$INGRESS_IP/$RAG_PATH/indexes/code_index/documents" \
  -H "Content-Type: application/json" \
  -d '{
        "documents": [
            {
                "doc_id": "'$DOC_ID_0'",
                "text": "Retrieval Augmented Generation (RAG) is an architecture that augments the capabilities of a Large Language Model (LLM) like ChatGPT by adding an information retrieval system that provides grounding data. Adding an information retrieval system gives you control over grounding data used by an LLM when it formulates a response.",
                "hash_value": "text_hash_value",
                "metadata": {
                  "author": "kaito",
                    "updated": "true"
                }
            }
        ]  
    }' | jq


model=phi-4-mini-instruct

curl -sS -X POST "http://$INGRESS_IP/$RAG_PATH/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "index_name": "code_index",
    "model": "phi-4-mini-instruct",
    "messages": [
      {"role": "system", "content": "You are a knowledgeable assistant."},
      {"role": "user", "content": "What is Retrieval Augmented Generation (RAG)?"}
    ],
    "temperature": 0.7,
    "max_tokens": 2048,
    "context_token_ratio": 0.5
  }' | jq
  

curl -X POST http://$INGRESS_IP/$RAG_PATH/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
        "index_name": "rag_index",
        "model": "phi-4-mini-instruct",
        "messages": [
          {"role": "system", "content": "You are a knowledgeable Tax assistant."},
          {"role": "user", "content": "what are tax credits available for families in Canada?"}
        ],
        "temperature": 0.7,
        "max_tokens": 2048,
        "context_token_ratio": 0.5
      }' | jq


curl -X POST http://$INGRESS_IP/phi4/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
        "index_name": "rag_index",
        "model": "phi-4-mini-instruct",
        "messages": [
          {"role": "system", "content": "You are a knowledgeable assistant."},
          {"role": "user", "content": "What is RAG?"}
        ],
        "temperature": 0.7,
        "max_tokens": 2048,
        "context_token_ratio": 0.5
      }' | jq




# Demo Scenario: Index and Query Land of Fantasia laws
# Assumes you already have INGRESS_IP + RAG_PATH set (e.g., RAG_PATH=rag-nostorage)
DOC_FILE="document-ingestion/fantasia-citizen-laws.md"

curl -sS -X POST "http://$INGRESS_IP/$RAG_PATH/index" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg index_name "rag_index" \
    --rawfile text "$DOC_FILE" \
    --arg title "Fantasia Citizen Code (FCC)" \
    --arg jurisdiction "Island of Fantasia (fictional)" \
    --arg version "FCC-1.0" \
    --arg effective_date "2041-04-01" \
    --arg last_updated "2041-09-15" \
    --arg intended_use "Demo document for vector database ingestion + RAG question answering" \
    --argjson tags '["fantasia","fictional-law","citizen-code","vector-db-demo","rag"]' \
    '{
      index_name: $index_name,
      documents: [
        {
          text: $text,
          metadata: {
            title: $title,
            jurisdiction: $jurisdiction,
            version: $version,
            effective_date: $effective_date,
            last_updated: $last_updated,
            intended_use: $intended_use,
            tags: $tags,
            source: "fantasia-citizen-laws.md"
          }
        }
      ]
    }')" | jq


curl -sS -X POST "http://$INGRESS_IP/$RAG_PATH/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "index_name": "rag_index",
    "model": "phi-4-mini-instruct",     
    "messages": [
      {"role": "system", "content": "You are a legal assistant knowledgeable about the laws of the Island of Fantasia."},
      {"role": "user", "content": "What are the key responsibilities of citizens under the Fantasia Citizen Code?"}
    ],
    "temperature": 0.3,
    "max_tokens": 2048,
    "context_token_ratio": 0.6
  }' | jq -r '.choices[0].message.content'
# Expected: The response should summarize key responsibilities as outlined in the FCC document.


curl -sS -X POST "http://$INGRESS_IP/$RAG_PATH/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "index_name": "rag_index",
    "model": "phi-4-mini-instruct",     
    "messages": [
      {"role": "system", "content": "You are a legal assistant knowledgeable about the laws of the Island of Fantasia."},
      {"role": "user", "content": "What is law 1.02 Civic Ledger registration?"}
    ],
    "temperature": 0.9,
    "max_tokens": 2048,
    "context_token_ratio": 0.6
  }' | jq -r '.choices[0].message.content'

