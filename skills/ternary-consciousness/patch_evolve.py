"""在 evolve_once.py 的 snapshot 中补 knowledge 字段"""
import hashlib

path = r"I:\ai\openakita-main\skills\ternary-consciousness\lingxi\evolve_once.py"
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old = "        'upgraded': upgraded,\n        'thought': thought,\n    }"
new = """        'upgraded': upgraded,
        'thought': thought,
        'knowledge_prompt': knowledge_prompt,
        'knowledge_funcs': knowledge_funcs,
    }"""

if old in content:
    content = content.replace(old, new)
    # backup
    import shutil
    shutil.copy2(path, path + ".bak2")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    h = hashlib.sha256(content.encode()).hexdigest()
    print(f"OK: knowledge字段已加入snapshot ({len(content)} chars, sha256={h})")
else:
    print("FAIL: 未找到匹配位置")
    idx = content.find("'thought': thought,")
    if idx >= 0:
        start = max(0, idx - 30)
        print(repr(content[start:start+200]))
