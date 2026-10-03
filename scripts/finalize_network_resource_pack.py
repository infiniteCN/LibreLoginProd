#!/usr/bin/env python3
"""给已经合并好的全服材质包做最后一轮收尾，专治客户端那些紫黑块和乱飘模型。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any


非法且未被引用的文件 = {
    "assets/civilization/models/item/tools/elvish_spear/default - Copia.json",
    "assets/minecraft/textures/item/X.png",
    "assets/minecraft/textures/item/mixanor by sword.png",
}

非法文件引用线索 = {
    "assets/civilization/models/item/tools/elvish_spear/default - Copia.json": (
        "default - Copia",
    ),
    "assets/minecraft/textures/item/X.png": ("minecraft:item/X", "item/X"),
    "assets/minecraft/textures/item/mixanor by sword.png": ("mixanor by sword",),
}

声音纠错 = {
    "custom/mobs/fallenhero/slashhit3": "custom/mobs/fallenhero/slashhitb3",
    "custom/spell/fallenreaper/attack4reaper1": "custom/spell/fallenhero/attack4reaper1",
}

合法资源路径 = re.compile(r"^[a-z0-9_./-]+$")


def 读_json(数据: bytes, 名称: str) -> Any:
    try:
        return json.loads(数据.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as 异常:
        raise ValueError(f"{名称} 不是正常 JSON：{异常}") from 异常


def 写_json(内容: Any) -> bytes:
    return (
        json.dumps(内容, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"
    ).encode("utf-8")


def 读取压缩包(路径: Path) -> dict[str, bytes]:
    文件: dict[str, bytes] = {}
    with zipfile.ZipFile(路径) as 压缩包:
        坏文件 = 压缩包.testzip()
        if 坏文件:
            raise ValueError(f"输入包本来就是坏的，第一处坏在：{坏文件}")
        for 信息 in 压缩包.infolist():
            if 信息.is_dir():
                continue
            名称 = 信息.filename.replace("\\", "/").lstrip("/")
            if 名称 in 文件 or any(已有.casefold() == 名称.casefold() for 已有 in 文件):
                raise ValueError(f"包里有重复或大小写撞车的路径：{名称}")
            文件[名称] = 压缩包.read(信息)
    return 文件


def 读取客户端头颅定义(客户端: Path) -> tuple[int, dict[str, Any]]:
    with zipfile.ZipFile(客户端) as 压缩包:
        版本 = 读_json(压缩包.read("version.json"), "客户端 version.json")
        头颅 = 读_json(
            压缩包.read("assets/minecraft/items/player_head.json"),
            "客户端 player_head.json",
        )
    格式 = 版本["pack_version"]["resource_major"]
    模型 = 头颅.get("model", {})
    变换 = 模型.get("transformation")
    if not isinstance(格式, int) or 格式 < 75:
        raise ValueError(f"客户端资源格式不对劲：{格式!r}")
    if not isinstance(变换, dict):
        raise ValueError("客户端原版玩家头没有 transformation，别硬套 26.2 修复")
    return 格式, copy.deepcopy(变换)


def 修复头颅模型(
    文件: dict[str, bytes],
    客户端格式: int,
    原版变换: dict[str, Any],
) -> dict[str, Any]:
    # 旧版最后那个自己指自己会把大于 10012 的头绕晕，直接回原版头骨模板。
    旧版路径 = "assets/minecraft/models/item/player_head.json"
    旧版 = 读_json(文件[旧版路径], 旧版路径)
    旧版重置 = 0
    for 覆盖 in 旧版.get("overrides", []):
        if 覆盖.get("predicate", {}).get("custom_model_data") == 10012:
            覆盖["model"] = "minecraft:item/template_skull"
            旧版重置 += 1
    if 旧版重置 != 1:
        raise ValueError(f"旧版玩家头的 10012 重置项数量不对：{旧版重置}")
    文件[旧版路径] = 写_json(旧版)

    来源路径 = (
        "ia_overlay_1_21_11_plus_safe/assets/minecraft/items/player_head.json"
    )
    新版 = 读_json(文件[来源路径], 来源路径)
    已补变换 = 0

    def 递归补变换(节点: Any) -> None:
        nonlocal 已补变换
        if isinstance(节点, dict):
            类型 = str(节点.get("type", "")).split(":")[-1]
            内层 = 节点.get("model")
            if (
                类型 == "special"
                and isinstance(内层, dict)
                and str(内层.get("type", "")).split(":")[-1] == "player_head"
            ):
                节点["transformation"] = copy.deepcopy(原版变换)
                已补变换 += 1
            for 值 in 节点.values():
                递归补变换(值)
        elif isinstance(节点, list):
            for 值 in 节点:
                递归补变换(值)

    递归补变换(新版)
    if 已补变换 != 14:
        raise ValueError(f"26.2 玩家头应当补 14 处变换，实际补了 {已补变换} 处")

    覆盖目录 = "ia_overlay_26_2_plus_safe"
    目标路径 = f"{覆盖目录}/assets/minecraft/items/player_head.json"
    文件[目标路径] = 写_json(新版)

    元数据 = 读_json(文件["pack.mcmeta"], "pack.mcmeta")
    条目 = 元数据.setdefault("overlays", {}).setdefault("entries", [])
    条目[:] = [项目 for 项目 in 条目 if 项目.get("directory") != 覆盖目录]
    条目.append(
        {
            "directory": 覆盖目录,
            "formats": [客户端格式, 9999],
            "min_format": 客户端格式,
            "max_format": 9999,
        }
    )
    文件["pack.mcmeta"] = 写_json(元数据)
    return {
        "legacy_reset_model": "minecraft:item/template_skull",
        "client_format": 客户端格式,
        "overlay": 覆盖目录,
        "transformations_added": 已补变换,
    }


def 修复方块轮廓(文件: dict[str, bytes]) -> str:
    路径 = "assets/minecraft/models/item/block_outline.json"
    模型 = 读_json(文件[路径], 路径)
    模型["parent"] = "minecraft:block/block"
    纹理 = 模型.setdefault("textures", {})
    纹理["particle"] = "minecraft:block/white_concrete"
    文件[路径] = 写_json(模型)
    return 路径


def 拆声音名称(名称: str) -> tuple[str, str]:
    if ":" in 名称:
        return tuple(名称.split(":", 1))  # type: ignore[return-value]
    return "minecraft", 名称


def 声音文件存在(文件: dict[str, bytes], 名称: str) -> bool:
    命名空间, 相对路径 = 拆声音名称(名称)
    return f"assets/{命名空间}/sounds/{相对路径}.ogg" in 文件


def 清理坏声音引用(文件: dict[str, bytes]) -> dict[str, Any]:
    已纠正: list[dict[str, str]] = []
    已移除声音: list[dict[str, str]] = []
    已移除事件: list[str] = []

    声音表路径 = sorted(
        路径
        for 路径 in 文件
        if 路径.startswith("assets/") and 路径.endswith("/sounds.json")
    )
    for 路径 in 声音表路径:
        内容 = 读_json(文件[路径], 路径)
        if not isinstance(内容, dict):
            raise ValueError(f"{路径} 的根不是对象")
        新内容: dict[str, Any] = {}
        for 事件, 配置 in 内容.items():
            if not isinstance(配置, dict) or not isinstance(配置.get("sounds"), list):
                新内容[事件] = 配置
                continue
            原声音 = 配置["sounds"]
            新声音: list[Any] = []
            for 项目 in 原声音:
                if isinstance(项目, str):
                    名称 = 项目
                    类型 = "sound"
                elif isinstance(项目, dict):
                    名称 = 项目.get("name")
                    类型 = 项目.get("type", "sound")
                else:
                    新声音.append(项目)
                    continue
                if not isinstance(名称, str) or 类型 == "event":
                    新声音.append(项目)
                    continue

                新名称 = 声音纠错.get(名称, 名称)
                if 新名称 != 名称:
                    已纠正.append({"event": 事件, "from": 名称, "to": 新名称})
                    if isinstance(项目, str):
                        项目 = 新名称
                    else:
                        项目 = dict(项目)
                        项目["name"] = 新名称
                    名称 = 新名称

                # 原版声音不在资源包里，只有 custom/ 才必须由咱自己带齐。
                _, 相对路径 = 拆声音名称(名称)
                if 相对路径.startswith("custom/") and not 声音文件存在(文件, 名称):
                    已移除声音.append({"event": 事件, "sound": 名称})
                    continue
                新声音.append(项目)

            新配置 = dict(配置)
            新配置["sounds"] = 新声音
            if 原声音 and not 新声音:
                已移除事件.append(f"{路径}:{事件}")
                continue
            新内容[事件] = 新配置
        文件[路径] = 写_json(新内容)

    # 再扫一遍，漏一条就别发布，免得客户端进服继续刷屏。
    残留: list[str] = []
    for 路径 in 声音表路径:
        内容 = 读_json(文件[路径], 路径)
        for 事件, 配置 in 内容.items():
            if not isinstance(配置, dict):
                continue
            for 项目 in 配置.get("sounds", []):
                if isinstance(项目, str):
                    名称 = 项目
                    类型 = "sound"
                elif isinstance(项目, dict):
                    名称 = 项目.get("name")
                    类型 = 项目.get("type", "sound")
                else:
                    continue
                if not isinstance(名称, str) or 类型 == "event":
                    continue
                _, 相对路径 = 拆声音名称(名称)
                if 相对路径.startswith("custom/") and not 声音文件存在(文件, 名称):
                    残留.append(f"{路径}:{事件}->{名称}")
    if 残留:
        raise ValueError("自定义声音还缺文件：\n- " + "\n- ".join(残留))
    return {
        "corrected": 已纠正,
        "removed_missing_sounds": 已移除声音,
        "removed_empty_events": 已移除事件,
    }


def 清理非法路径(文件: dict[str, bytes]) -> list[str]:
    所有文本 = b"\n".join(
        数据
        for 路径, 数据 in 文件.items()
        if 路径.endswith((".json", ".mcmeta", ".properties", ".yml", ".yaml"))
    )
    for 路径 in 非法且未被引用的文件:
        if any(线索.encode("utf-8") in 所有文本 for 线索 in 非法文件引用线索[路径]):
            raise ValueError(f"准备删除的非法文件还有引用，先别乱删：{路径}")
    已删除 = sorted(路径 for 路径 in 非法且未被引用的文件 if 路径 in 文件)
    for 路径 in 已删除:
        del 文件[路径]
    return 已删除


def 校验资源路径(文件: dict[str, bytes]) -> None:
    非法: list[str] = []
    for 路径 in 文件:
        位置 = 路径.find("assets/")
        if 位置 < 0:
            continue
        资源路径 = 路径[位置:]
        if not 合法资源路径.fullmatch(资源路径):
            非法.append(路径)
    if 非法:
        raise ValueError("资源路径里还有客户端不认的字符：\n- " + "\n- ".join(非法))


def 写压缩包(文件: dict[str, bytes], 输出: Path) -> bytes:
    输出.parent.mkdir(parents=True, exist_ok=True)
    临时 = 输出.with_suffix(输出.suffix + ".tmp")
    with zipfile.ZipFile(
        临时, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as 压缩包:
        for 路径 in sorted(文件, key=str.casefold):
            信息 = zipfile.ZipInfo(路径, date_time=(2026, 7, 28, 0, 0, 0))
            信息.compress_type = zipfile.ZIP_DEFLATED
            信息.external_attr = 0o100644 << 16
            压缩包.writestr(信息, 文件[路径], compresslevel=9)
    临时.replace(输出)

    with zipfile.ZipFile(输出) as 压缩包:
        坏文件 = 压缩包.testzip()
        if 坏文件:
            raise ValueError(f"输出包写坏了：{坏文件}")
        名称 = [项目.filename for 项目 in 压缩包.infolist() if not 项目.is_dir()]
        if len(名称) != len({项目.casefold() for 项目 in 名称}):
            raise ValueError("输出包里出现了重复或大小写撞车路径")
        for 路径 in 名称:
            if 路径.endswith(".json") or 路径 == "pack.mcmeta":
                读_json(压缩包.read(路径), 路径)
    return 输出.read_bytes()


def main() -> None:
    参数 = argparse.ArgumentParser()
    参数.add_argument("--input", type=Path, required=True)
    参数.add_argument("--client-jar", type=Path, required=True)
    参数.add_argument("--output", type=Path, required=True)
    参数.add_argument("--report", type=Path)
    配置 = 参数.parse_args()

    文件 = 读取压缩包(配置.input)
    客户端格式, 原版变换 = 读取客户端头颅定义(配置.client_jar)
    报告 = {
        "source": str(配置.input),
        "head_model": 修复头颅模型(文件, 客户端格式, 原版变换),
        "block_outline": 修复方块轮廓(文件),
        "sounds": 清理坏声音引用(文件),
        "invalid_paths_removed": 清理非法路径(文件),
    }
    校验资源路径(文件)
    数据 = 写压缩包(文件, 配置.output)
    报告.update(
        {
            "output": str(配置.output),
            "files": len(文件),
            "size": len(数据),
            "sha1": hashlib.sha1(数据).hexdigest(),
            "sha256": hashlib.sha256(数据).hexdigest(),
        }
    )
    文本 = json.dumps(报告, ensure_ascii=False, indent=2) + "\n"
    if 配置.report:
        配置.report.write_text(文本, encoding="utf-8")
    print(文本, end="")


if __name__ == "__main__":
    main()
