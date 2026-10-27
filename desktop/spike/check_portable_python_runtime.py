"""便携 Python 运行时探针：导入并实际使用 numpy / pandas / matplotlib / openpyxl / pillow。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

OUT = Path(os.environ.get("SPIKE_OUT", "desktop/spike/out/portable-python-runtime.json"))
result: dict = {"check": "portable-python-runtime", "status": "fail", "details": {}}

try:
    import matplotlib
    import numpy
    import openpyxl
    import pandas
    from PIL import Image

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    result["details"].update(
        {
            "python": sys.version,
            "executable": sys.executable,
            "numpy": numpy.__version__,
            "pandas": pandas.__version__,
            "matplotlib": matplotlib.__version__,
            "openpyxl": openpyxl.__version__,
            "pillow": Image.__version__,
        }
    )

    work = Path(tempfile.mkdtemp(prefix="kiwi-portable-"))

    fig, ax = plt.subplots(figsize=(3, 2))
    ax.plot([1, 2, 3], [3, 2, 1])
    ax.set_title("便携 Python 绘图")
    png = work / "plot.png"
    fig.savefig(png, dpi=100)
    plt.close(fig)
    if not png.exists() or png.stat().st_size < 1000:
        raise AssertionError("matplotlib 输出的 PNG 异常")

    xlsx = work / "probe.xlsx"
    frame = pandas.DataFrame({"名称": ["苹果", "香蕉"], "数量": [3, 5]})
    frame.to_excel(xlsx, index=False)
    loaded = pandas.read_excel(xlsx)
    if list(loaded["名称"]) != ["苹果", "香蕉"]:
        raise AssertionError(f"pandas / openpyxl 读回不一致：{loaded.to_dict()}")

    image = Image.open(png).convert("RGB")
    if image.size[0] < 100:
        raise AssertionError("pillow 读取 PNG 失败")

    result["details"]["png_bytes"] = png.stat().st_size
    result["details"]["xlsx_bytes"] = xlsx.stat().st_size
    result["details"]["pandas_roundtrip"] = loaded.to_dict(orient="records")
    result["status"] = "pass"
    result["summary"] = "numpy / pandas / matplotlib / openpyxl / pillow 均可用"
except Exception:  # noqa: BLE001 - 结果文件需要保留完整堆栈
    result["error"] = traceback.format_exc()
finally:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))

sys.exit(0 if result["status"] == "pass" else 1)
