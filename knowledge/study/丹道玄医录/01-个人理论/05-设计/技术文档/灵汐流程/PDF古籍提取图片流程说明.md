# PDF古籍舌诊图片提取流程说明

> 配套脚本：`extract_pdf_tongue_images.py`
> 适用范围：《杨春虎中药舌诊讲记》及其他含舌诊图谱的PDF古籍

---

## 一、完整流程概览

```
获取PDF → 运行提取脚本 → 质量筛选 → 人工标注 → 入库索引
  ①           ②            ③           ④           ⑤
```

---

## 二、第一步：环境准备

```bash
# 安装依赖（只需执行一次）
pip install pypdf pdfplumber pdf2image Pillow pytesseract
```

**确认安装成功：**
```python
python -c "import pypdf; print('pypdf:', pypdf.__version__)"
python -c "import pdf2image; print('pdf2image ready')"
python -c "from PIL import Image; print('Pillow:', Image.__version__)"
```

---

## 三、第二步：提取图片

### 基本用法

```bash
# 最简单的提取
python extract_pdf_tongue_images.py "杨春虎中药舌诊讲记.pdf"

# 指定输出目录
python extract_pdf_tongue_images.py "杨春虎中药舌诊讲记.pdf" -o ../舌诊图片数据库

# 高清提取（适合含细小舌诊细节的PDF）
python extract_pdf_tongue_images.py "杨春虎中药舌诊讲记.pdf" --dpi 300 --fmt png

# 过滤小图（舌诊图片一般不会太小）
python extract_pdf_tongue_images.py "杨春虎中药舌诊讲记.pdf" --min-size 50 --min-width 200
```

### 参数说明

| 参数 | 默认值 | 说明 |
|:-----|:------:|:------|
| `pdf` | （必填） | PDF文件路径 |
| `-o / --output` | `./舌诊图片数据库` | 输出根目录 |
| `--dpi` | 200 | PDF转图片DPI（越高越清晰） |
| `--min-size` | 30KB | 最小图片大小，小于此值标记为质量不足 |
| `--min-width` | 100px | 最小图片宽度 |
| `--fmt` | jpg | 输出格式（jpg/png/tiff） |
| `--source` | "杨春虎中药舌诊讲记" | 来源名称（写入元数据） |

### 输出结构

```
舌诊图片数据库/
├── raw/                              ← 原始提取图片
│   ├── p0001_杨春虎中药舌诊讲记.jpg
│   ├── p0002_杨春虎中药舌诊讲记.jpg
│   └── ...
├── metadata/
│   └── extraction_meta.json          ← 提取元数据（含图片列表、SHA256等）
```

---

## 四、第三步：质量筛选与分类

提取完成后，`extraction_meta.json` 中已标注每张图片的质量检查结果：

```json
{
  "images": [
    {
      "page": 1,
      "filename": "p0001_杨春虎中药舌诊讲记.jpg",
      "width": 1920,
      "height": 1080,
      "size_kb": 245.3,
      "quality_passed": true
    }
  ],
  "skipped": [
    {
      "page": 3,
      "filename": "p0003_杨春虎中药舌诊讲记.jpg",
      "reason": "疑似全白页面"
    }
  ]
}
```

**筛选建议：**
- `quality_passed: true` → 进入下一步标注
- `quality_passed: false` → 人工复核是否可用
- `skipped` 中的全白/全黑 → 直接删除（可能是夹页、空白页）

---

## 五、第四步：人工标注

按《舌诊图片数据库设计规范》的标注字段，为每张图片添加标注。

**推荐标注流程：**

1. 打开图片 → 观察舌象
2. 判断三级分类（舌质→舌色→淡白舌等）
3. 填写颜色、纹理、苔质等描述
4. 结合《杨春虎中药舌诊讲记》原文填写病机分析
5. 关联古籍来源（填写 book_ref）

**快速标注模板：**

```json
{
  "image_id": "T01-20260508-XXX",
  "filename": "p0015_杨春虎中药舌诊讲记.jpg",
  "tongue_category_l1": "",
  "tongue_category_l2": "",
  "tongue_category_l3": "",
  "tongue_category_tags": [],
  "color_desc": "",
  "texture_desc": "",
  "coating_desc": "",
  "shape_desc": "",
  "syndrome_type": "",
  "pathogenesis": "",
  "book_ref": "",
  "source_name": "杨春虎中药舌诊讲记",
  "source_ref": "",
  "quality_score": 0,
  "verified": false
}
```

---

## 六、第五步：入库索引

标注完成后，将标注数据合并到 `tongue_meta.json` 全库索引中：

```bash
# 后续将开发 index_builder.py 自动完成以下操作：
# 1. 合并新标注到全库
# 2. 生成按分类/证型/来源的索引文件
# 3. 建立FAISS特征向量索引（可选）
# 4. 更新统计信息
```

---

## 七、与《杨春虎中药舌诊讲记》学习的配合

```
阅读书本理论 → 提取对应章节的图片 → 观察比对 → 标注 → 入库
     ①                 ②                ③        ④      ⑤
```

**建议学习顺序：**

1. 通读《杨春虎中药舌诊讲记》一遍，了解全貌
2. 对重点章节（如淡白舌、红绛舌等专题）逐章提取图片
3. 每章理论+图片对照学习
4. 将学到的知识标注到数据库中
5. 积累到一定量后，用FAISS检索做"鉴别训练"

---

## 八、常见问题

**Q：提取出的图片太模糊怎么办？**
A：提高 `--dpi` 参数，从200提升到300或400，但文件会变大、提取时间变长。

**Q：有些页没有舌诊图也想删除？**
A：`extraction_meta.json` 的 `skipped` 列表中会标注"疑似全白页面"，浏览 `raw/` 目录后手动删除无用图片即可。

**Q：我想单独提取某几页的图片？**
A：当前版本提取整本PDF。如需按页提取，可以使用：
```python
# 只提取第5-20页
images = convert_from_path("杨春虎中药舌诊讲记.pdf", first_page=5, last_page=20)
```

**Q：提取出来的是彩色图，OCR还需要吗？**
A：`--no-ocr` 可跳过OCR。舌诊图片重点是图像本身，OCR识别图中的文字标注（如"淡白舌"、"黄腻苔"等标签文字）有助于自动分类，但不是必须的。
