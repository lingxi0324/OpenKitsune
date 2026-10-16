"""
解析「药性多维分析法·六维象形辨药论.md」中的240味药，
生成结构化 JSON 知识库文件，供 yaoxing_duowei.py 引擎加载。
"""
import re
import json

MD_PATH = r"I:\ai\openakita-main\我的文件夹\丹道玄医录\07-个人理论\04-交叉发明\药性多维分析法·六维象形辨药论.md"
JSON_PATH = r"I:\ai\openakita-main\skills\药性多维分析\knowledge_240.json"

with open(MD_PATH, "r", encoding="utf-8") as f:
    text = f.read()

# 匹配每味药条目：### N. 药名
block_pattern = re.compile(
    r'### (\d+)\.\s*(.+?)\n'
    r'1\.\s*\*{2}味维\*{2}\s*[：:]\s*(.*?)\n'
    r'2\.\s*\*{2}色维\*{2}\s*[：:]\s*(.*?)\n'
    r'3\.\s*\*{2}形维\*{2}\s*[：:]\s*(.*?)\n'
    r'4\.\s*\*{2}境维\*{2}\s*[：:]\s*(.*?)\n'
    r'5\.\s*\*{2}质维\*{2}\s*[：:]\s*(.*?)\n'
    r'6\.\s*\*{2}生维\*{2}\s*[：:]\s*(.*?)\n'
    r'\*{2}六维合参\*{2}\s*[：:]\s*(.*?)(?=\n### |\n# |\Z)',
    re.DOTALL
)

matches = block_pattern.findall(text)
print(f"解析到 {len(matches)} 味药")

herbs = []
for m in matches:
    num, name, taste, color, shape, habitat, substance, growth, summary = m
    name = name.strip()
    summary = summary.strip()
    
    # 提取各维的五行关键词
    taste_keywords = []
    if "辛" in taste: taste_keywords.append("辛")
    if "甘" in taste: taste_keywords.append("甘")
    if "酸" in taste: taste_keywords.append("酸")
    if "苦" in taste: taste_keywords.append("苦")
    if "咸" in taste: taste_keywords.append("咸")
    if "淡" in taste: taste_keywords.append("淡")
    
    color_keywords = []
    if "青" in color or "绿" in color: color_keywords.append("青")
    if "赤" in color or "红" in color: color_keywords.append("赤")
    if "黄" in color: color_keywords.append("黄")
    if "白" in color: color_keywords.append("白")
    if "黑" in color or "紫" in color: color_keywords.append("黑")
    
    shape_keywords = []
    if "中空" in shape: shape_keywords.append("中空")
    if "方茎" in shape or "方" in shape: shape_keywords.append("方茎")
    if "藤" in shape or "蔓" in shape: shape_keywords.append("藤蔓")
    if "毛" in shape: shape_keywords.append("多毛")
    if "刺" in shape: shape_keywords.append("有刺")
    if "叶缺" in shape or "缺" in shape: shape_keywords.append("叶缺")
    if "竹节" in shape or "节" in shape: shape_keywords.append("竹节")
    if "根" in shape: shape_keywords.append("根")
    if "花" in shape: shape_keywords.append("花")
    if "果" in shape or "实" in shape or "籽" in shape: shape_keywords.append("果籽")
    
    herb = {
        "id": int(num),
        "name": name,
        "taste": taste,
        "color": color,
        "shape": shape,
        "habitat": habitat,
        "substance": substance,
        "growth": growth,
        "summary": summary,
        "taste_keywords": taste_keywords,
        "color_keywords": color_keywords,
        "shape_keywords": shape_keywords
    }
    herbs.append(herb)

output = {
    "version": "1.0",
    "total": len(herbs),
    "herbs": herbs
}

with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"已写入 {JSON_PATH}")
print(f"共 {len(herbs)} 味药")

# 统计覆盖情况
sections = re.findall(r'## 第[一二三四五六]部分[：:](.*?)(?=\n|$)', text)
print(f"\n分类覆盖：{len(sections)} 个部分")
for s in sections:
    print(f"  - {s.strip()}")
