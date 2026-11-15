"""Wait for a RunPod Ollama pod, then streaming-pull the Glimmer GGUF.

Usage: POD_ID=<id> python3 runpod_wait_pull.py
Durable copy (workspace, not /tmp). Polls the proxy /api/tags until Ollama
answers, then pulls with stream:true (stream:false dies on a Cloudflare
524 timeout for a 17GB model). Exits 0 when the model is listed in /api/tags.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

POD = os.environ["POD_ID"]
MODEL = "hf.co/meta-models/Muse-Glimmer-30B-GGUF:Muse-Glimmer-30B-KQuant-17GB-Q4_K_M"
BASE = f"https://{POD}-11434.proxy.runpod.net"

print(f"waiting for Ollama on {BASE} ...", flush=True)
for i in range(90):
    try:
        with urllib.request.urlopen(BASE + "/api/tags", timeout=15) as resp:
            print("Ollama up after", (i + 1) * 10, "s", flush=True)
            break
    except Exception:
        time.sleep(10)
else:
    print("Ollama did not come up in 15 min")
    sys.exit(1)

print("pulling", MODEL, "(streaming, ~7 min) ...", flush=True)
proc = subprocess.run(
    ["curl", "-sN", "--max-time", "1800", "-X", "POST", BASE + "/api/pull",
     "-H", "Content-Type: application/json",
     "-d", json.dumps({"name": MODEL, "stream": True})],
    capture_output=True, text=True)
print("pull exit:", proc.returncode, flush=True)
tail = proc.stdout.strip().splitlines()[-2:]
print("\n".join(tail), flush=True)

with urllib.request.urlopen(BASE + "/api/tags", timeout=30) as resp:
    tags = json.load(resp)
names = [m["name"] for m in tags.get("models", [])]
print("models on pod:", names, flush=True)
sys.exit(0 if MODEL in names else 1)
