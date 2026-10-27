"""汇总各 Windows spike 任务的 JSON 结果，供推送回分支后本地查看。"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

OUT_DIR = Path("desktop/spike/out")


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 汇总脚本需要保留坏文件信息
        return {"status": "invalid", "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    needs = json.loads(os.environ.get("NEEDS", "{}"))
    checks: dict[str, dict] = {}
    for path in sorted(OUT_DIR.glob("*.json")):
        if path.name == "summary.json":
            continue
        checks[path.stem] = load_json(path)

    summary = {
        "run_id": os.environ.get("RUN_ID"),
        "run_url": os.environ.get("RUN_URL"),
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "jobs": {name: info.get("result") for name, info in needs.items()},
        "checks": checks,
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Windows 可行性 Spike 结果",
        "",
        f"- run: {summary['run_url']}",
        f"- 生成时间: {summary['generated_at']}",
        "",
        "| 任务 | 作业结果 | 检查状态 | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for name, job_result in summary["jobs"].items():
        check = checks.get(name, {})
        status = check.get("status", "无结果")
        detail = check.get("error") or check.get("summary") or ""
        detail = str(detail).replace("|", "\\|").replace("\n", " ")[:180]
        lines.append(f"| {name} | {job_result} | {status} | {detail} |")
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
