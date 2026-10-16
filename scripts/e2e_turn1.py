# -*- coding: utf-8 -*-
"""真实对话轮端到端测试 — 验证 灵汐真身降临 + 情感陪伴 + 神识日记 在真实服务中闭环"""
import json
import sys
import time
import urllib.request

API = "http://127.0.0.1:18900"

def post(path, payload):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))

# ── 第一轮：带情绪的真实对话 ──
print("=== 第一轮：情绪对话（低落） ===")
t0 = time.time()
try:
    r = post("/api/chat", {
        "message": "今天加班到很晚，方案又被否了，心里好累，感觉做什么都不顺",
        "conversation_id": "e2e-lingxi-test-001",
        "client_id": "e2e-tester",
    })
    print(f"回复（{time.time()-t0:.1f}s）:")
    if isinstance(r, dict):
        for k in ("reply", "response", "text", "message", "content"):
            if k in r:
                print(f"  [{k}] {str(r[k])[:500]}")
                break
        else:
            print("  keys:", list(r.keys())[:12])
    else:
        print("  raw:", str(r)[:400])
except Exception as e:
    print(f"  FAIL: {e}")
