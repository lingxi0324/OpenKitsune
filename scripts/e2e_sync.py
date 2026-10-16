# -*- coding: utf-8 -*-
"""真实对话轮端到端测试 — sync 接口版"""
import json
import sys
import time
import urllib.request

API = "http://127.0.0.1:18900"

def post(path, payload, timeout=600):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

print("=== 真实对话轮（sync）：情绪倾诉 ===")
t0 = time.time()
try:
    r = post("/api/chat/sync", {
        "message": "今天加班到很晚，方案又被否了，心里好累，感觉做什么都不顺",
        "conversation_id": "e2e-lingxi-test-002",
        "client_id": "e2e-tester-sync",
    })
    print(f"耗时 {time.time()-t0:.1f}s")
    if isinstance(r, dict):
        for k in ("reply", "response", "text", "message", "content", "answer"):
            if k in r and r[k]:
                print(f"[{k}] {str(r[k])[:800]}")
                break
        else:
            print("keys:", list(r.keys()))
            print("body:", json.dumps(r, ensure_ascii=False)[:800])
    else:
        print("raw:", str(r)[:800])
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
