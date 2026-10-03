#!/usr/bin/env python3
"""删掉会把原版声音直接静音的空声音事件。"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


声音文件 = "assets/minecraft/sounds.json"


def 修复(输入: Path, 输出: Path) -> list[str]:
    with zipfile.ZipFile(输入) as 原包:
        坏文件 = 原包.testzip()
        if 坏文件:
            raise ValueError(f"原包已经损坏：{坏文件}")

        名称 = [信息.filename for 信息 in 原包.infolist() if not 信息.is_dir()]
        if len(名称) != len({名称项.casefold() for 名称项 in 名称}):
            raise ValueError("原包里有重复或大小写冲突的路径")

        声音 = json.loads(原包.read(声音文件).decode("utf-8-sig"))
        已删除 = [
            事件
            for 事件, 配置 in 声音.items()
            if isinstance(配置, dict)
            and 配置.get("replace") is True
            and 配置.get("sounds") == []
        ]
        for 事件 in 已删除:
            del 声音[事件]

        临时文件 = 输出.with_suffix(输出.suffix + ".tmp")
        with zipfile.ZipFile(临时文件, "w", allowZip64=True) as 新包:
            for 信息 in 原包.infolist():
                数据 = 原包.read(信息.filename)
                if 信息.filename == 声音文件:
                    数据 = json.dumps(
                        声音, ensure_ascii=False, indent=2, separators=(",", ": ")
                    ).encode("utf-8")
                新包.writestr(信息, 数据)

    临时文件.replace(输出)
    with zipfile.ZipFile(输出) as 新包:
        坏文件 = 新包.testzip()
        if 坏文件:
            raise ValueError(f"修好的包校验失败：{坏文件}")

        剩余声音 = json.loads(新包.read(声音文件).decode("utf-8"))
        残留 = [
            事件
            for 事件, 配置 in 剩余声音.items()
            if isinstance(配置, dict)
            and 配置.get("replace") is True
            and 配置.get("sounds") == []
        ]
        if 残留:
            raise ValueError(f"空声音事件还没删干净：{残留}")

    return 已删除


def main() -> None:
    参数 = argparse.ArgumentParser()
    参数.add_argument("--input", type=Path, required=True)
    参数.add_argument("--output", type=Path, required=True)
    配置 = 参数.parse_args()

    已删除 = 修复(配置.input, 配置.output)
    数据 = 配置.output.read_bytes()
    print(
        json.dumps(
            {
                "output": str(配置.output),
                "removed_silent_events": 已删除,
                "size": len(数据),
                "sha1": hashlib.sha1(数据).hexdigest(),
                "sha256": hashlib.sha256(数据).hexdigest(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
