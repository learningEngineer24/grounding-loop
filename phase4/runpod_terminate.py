"""Terminate a RunPod pod and/or list current pods.

Usage:
  POD_ID=<id> python3 runpod_terminate.py        # terminate one pod
  python3 runpod_terminate.py --list             # list my pods
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import add_surrogate_to_request, read_json_response

API = "https://api.runpod.io/graphql"


def call(query):
    body = json.dumps({"query": query}).encode()
    req = urllib.request.Request(API, data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    add_surrogate_to_request(req, "custom.runpod", allowed_hosts=["api.runpod.io"])
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return read_json_response(resp)
    except urllib.error.HTTPError as e:
        print("HTTP", e.code)
        print(e.read().decode(errors="replace"))
        sys.exit(1)


LIST_Q = """
query {
  myself {
    pods {
      id
      name
      desiredStatus
      costPerHr
      runtime { uptimeInSeconds }
    }
  }
}
"""

if "--list" in sys.argv:
    print(json.dumps(call(LIST_Q), indent=1))
    sys.exit(0)

pod = os.environ.get("POD_ID")
if not pod:
    print("POD_ID not set")
    sys.exit(1)

mut = f"""
mutation {{
  podTerminate(input: {{ podId: "{pod}" }})
}}
"""
print(json.dumps(call(mut), indent=1))
print(json.dumps(call(LIST_Q), indent=1))
