#!/usr/bin/env python3
"""skill_integrator.py — 运行时配置切换 (v2.0)"""
import os, sys, json
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from corrected_scoring import compute_corrected_score, PLATES
from diagnose import load_test_suite
DATA_DIR = os.path.join(_SCRIPT_DIR, "..", "data")
PROFILES_PATH = os.path.join(DATA_DIR, "skill_profiles.json")
TEST_PATH = os.path.join(DATA_DIR, "test_suite.json")

def _score(plate, year, month):
    r = compute_corrected_score(plate, year, month)
    return r[0] if isinstance(r, tuple) else r

class SkillConfig:
    def __init__(self):
        with open(PROFILES_PATH) as f:
            self._data = json.load(f)
        self._active = self._data["default_profile"]
    @property
    def active_profile(self): return self._active
    def list_profiles(self):
        return {k: v["description"] for k, v in self._data["profiles"].items()}
    def switch(self, name):
        if name in self._data["profiles"]:
            self._active = name
            return f"Switched to {name}"
        return f"Not found: {name}"
    def get_params(self):
        return self._data["profiles"][self._active]

def validate(profile_name):
    cfg = SkillConfig()
    cfg.switch(profile_name)
    p = cfg.get_params()
    test = load_test_suite(TEST_PATH)
    cor, tot = 0, 0
    for ys, yd in test.items():
        year = int(ys)
        for md in yd["months"]:
            m = md["m"]
            for pn in PLATES:
                actual = md[pn]
                score = _score(pn, year, m)
                if abs(score) > p["up_th"]:
                    pd = 1 if score > p["up_th"] else -1
                    ad = 1 if actual > 0 else (-1 if actual < 0 else 0)
                    if pd != 0 and ad != 0:
                        tot += 1
                        if pd == ad: cor += 1
    return cor, tot, cor/tot*100 if tot else 0

if __name__ == "__main__":
    cfg = SkillConfig()
    print("Profiles:", json.dumps(cfg.list_profiles(), ensure_ascii=False))
    for name in cfg.list_profiles():
        c, t, r = validate(name)
        print(f"  {name}: {c}/{t} = {r:.1f}%")
