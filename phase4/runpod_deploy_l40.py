"""Deploy one NVIDIA L40 (Community) pod running ollama/ollama for Glimmer 30B.

Durable copy of the deploy step (lives in the repo workspace, not /tmp —
/tmp was wiped mid-session Nov 15, 2026, losing the original script).

Usage: python3 runpod_deploy_l40.py
Prints the new pod id (or the GraphQL error) and exits.
"""
import json
import sys
import urllib.request

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import add_surrogate_to_request, read_json_response

import os
GPU = os.environ.get("GPU", "NVIDIA L40")
CLOUD = os.environ.get("CLOUD", "COMMUNITY")
MUTATION = """
mutation {
  podFindAndDeployOnDemand(input: {
    cloudType: COMMUNITY
    gpuCount: 1
    gpuTypeId: "NVIDIA L40"
    imageName: "ollama/ollama"
    name: "glimmer-30b"
    volumeInGb: 50
    containerDiskInGb: 50
    ports: "11434/http"
    env: [{key: "OLLAMA_HOST", value: "0.0.0.0:11434"}]
  }) {
    id
    desiredStatus
    machineId
    costPerHr
  }
}
""".replace("COMMUNITY", CLOUD).replace("NVIDIA L40", GPU)

import urllib.error

body = json.dumps({"query": MUTATION}).encode()
req = urllib.request.Request(
    "https://api.runpod.io/graphql", data=body,
    headers={"Content-Type": "application/json"}, method="POST")
add_surrogate_to_request(req, "custom.runpod", allowed_hosts=["api.runpod.io"])
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = read_json_response(resp)
except urllib.error.HTTPError as e:
    print("HTTP", e.code)
    print(e.read().decode(errors="replace"))
    sys.exit(1)
print(json.dumps(data, indent=1))
pod = (data.get("data") or {}).get("podFindAndDeployOnDemand")
if pod:
    print("POD_ID=" + pod["id"])
if (data.get("errors")):
    sys.exit(1)
