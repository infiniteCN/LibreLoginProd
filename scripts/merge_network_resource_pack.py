#!/usr/bin/env python3
"""合并 infiniteMC 的网络材质包，顺手把 ItemsAdder 那种保护 ZIP 正常化。"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import posixpath
import struct
import zlib
import zipfile
from pathlib import Path
from typing import Any


需要手动合并的路径 = {
    "pack.mcmeta",
    "pack.png",
    "assets/minecraft/sounds.json",
    "assets/minecraft/atlases/blocks.json",
    "assets/minecraft/font/default.json",
    "assets/minecraft/lang/en_us.json",
    "assets/minecraft/textures/char/black.png",
}


def 安全路径(文件名: str) -> str:
    路径 = 文件名.replace("\\", "/")
    规范路径 = posixpath.normpath(路径).lstrip("/")
    if not 规范路径 or 规范路径 == "." or 规范路径.startswith("../"):
        raise ValueError(f"包里混进了不安全路径：{文件名!r}")
    if ":" in 规范路径.split("/", 1)[0]:
        raise ValueError(f"包里混进了盘符路径：{文件名!r}")
    return 规范路径


def 读取普通包(路径: Path) -> dict[str, bytes]:
    文件: dict[str, bytes] = {}
    with zipfile.ZipFile(路径) as 压缩包:
        坏文件 = 压缩包.testzip()
        if 坏文件:
            raise ValueError(f"{路径.name} 解压校验没过，坏在：{坏文件}")
        for 信息 in 压缩包.infolist():
            if 信息.is_dir():
                continue
            文件名 = 安全路径(信息.filename)
            键 = 文件名.casefold()
            if any(已有.casefold() == 键 for 已有 in 文件):
                raise ValueError(f"{路径.name} 有重复或大小写撞车的路径：{文件名}")
            文件[文件名] = 压缩包.read(信息)
    return 文件


def 读取保护包(路径: Path) -> dict[str, bytes]:
    """ItemsAdder 会把本地头写成假数据，只信中央目录，别被它带沟里。"""
    文件: dict[str, bytes] = {}
    with 路径.open("rb") as 原始文件, zipfile.ZipFile(路径) as 压缩包:
        for 信息 in 压缩包.infolist():
            if 信息.is_dir():
                continue
            文件名 = 安全路径(信息.filename)
            键 = 文件名.casefold()
            if any(已有.casefold() == 键 for 已有 in 文件):
                raise ValueError(f"{路径.name} 有重复或大小写撞车的路径：{文件名}")

            原始文件.seek(信息.header_offset)
            头 = 原始文件.read(30)
            if len(头) != 30 or 头[:4] != b"PK\x03\x04":
                raise ValueError(f"{文件名} 的本地 ZIP 头不对劲")
            *_, 文件名长度, 扩展长度 = struct.unpack("<4s5H3I2H", 头)
            原始文件.seek(文件名长度 + 扩展长度, 1)
            压缩数据 = 原始文件.read(信息.compress_size)

            if 信息.compress_type == zipfile.ZIP_STORED:
                数据 = 压缩数据
            elif 信息.compress_type == zipfile.ZIP_DEFLATED:
                数据 = zlib.decompress(压缩数据, -zlib.MAX_WBITS)
            else:
                raise ValueError(f"{文件名} 用了没处理的压缩算法：{信息.compress_type}")

            # 这个包连中央目录的长度和 CRC 都故意写假，只能靠 DEFLATE 自己验流。
            # 顺便卡个上限，免得哪天塞进来一个解压炸弹，把机器直接送走。
            if len(数据) > 100 * 1024 * 1024:
                raise ValueError(f"{文件名} 解出来超过 100 MiB，先别硬吃")
            文件[文件名] = 数据
    return 文件


def 读_json(数据: bytes, 名称: str) -> Any:
    try:
        return json.loads(数据.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as 异常:
        raise ValueError(f"{名称} 不是正常 JSON：{异常}") from 异常


def 写_json(内容: Any) -> bytes:
    return (json.dumps(内容, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def 补命名空间(值: str) -> str:
    if ":" in 值:
        return 值
    return f"minecraft:{值}"


def 规范物品模型节点(节点: Any) -> Any:
    """ItemsAdder 有些字段不写 minecraft:，新客户端偶尔真不给面子。"""
    if isinstance(节点, list):
        return [规范物品模型节点(项) for 项 in 节点]
    if not isinstance(节点, dict):
        return 节点

    结果: dict[str, Any] = {}
    for 键, 值 in 节点.items():
        if 键 in {"type", "property"} and isinstance(值, str):
            结果[键] = 补命名空间(值)
        elif 键 == "model" and isinstance(值, str):
            结果[键] = 补命名空间(值)
        else:
            结果[键] = 规范物品模型节点(值)
    return 结果


def 精简直接模型(节点: dict[str, Any], 文件名: str) -> dict[str, Any]:
    模型 = 节点.get("model")
    if not isinstance(模型, str) or not 模型:
        raise ValueError(f"{文件名} 的 CMD 分支没写模型，客户端看了也得懵")

    结果: dict[str, Any] = {
        "type": "minecraft:model",
        "model": 补命名空间(模型),
    }
    着色 = 节点.get("tints")
    if isinstance(着色, list):
        结果["tints"] = 规范物品模型节点(着色)
    return 结果


def 修复皮革物品模型(文件: dict[str, bytes]) -> list[str]:
    """IA 把原版纹饰选择器硬怼进 model 节点了，紫黑块就是这么来的。"""
    已修复: list[str] = []
    for 文件名, 数据 in list(文件.items()):
        if not 文件名.endswith(".json"):
            continue
        if "/assets/minecraft/items/leather_" not in f"/{文件名}":
            continue
        if not 文件名.startswith("ia_overlay_"):
            continue

        内容 = 读_json(数据, 文件名)
        if not isinstance(内容, dict) or not isinstance(内容.get("model"), dict):
            raise ValueError(f"{文件名} 的物品模型根节点不对，这个不能硬猜")
        分发 = 内容["model"]
        if str(分发.get("type", "")).split(":")[-1] != "range_dispatch":
            continue
        if not isinstance(分发.get("entries"), list):
            raise ValueError(f"{文件名} 的 CMD entries 不是数组，先别乱修")

        原回退 = 分发.get("fallback")
        if not isinstance(原回退, dict):
            raise ValueError(f"{文件名} 没有正常 fallback，普通物品会直接变方块")

        if all(键 in 原回退 for 键 in ("cases", "fallback", "property")):
            # 这三个才是原版盔甲纹饰选择器。IA 额外塞的 model/tints 属于串台，扔掉。
            新回退 = {
                "type": "minecraft:select",
                "cases": 原回退["cases"],
                "fallback": 原回退["fallback"],
                "property": 原回退["property"],
            }
        else:
            新回退 = 精简直接模型(原回退, 文件名)

        新条目: list[dict[str, Any]] = []
        上个阈值: float | None = None
        for 条目 in 分发["entries"]:
            if not isinstance(条目, dict) or not isinstance(条目.get("model"), dict):
                raise ValueError(f"{文件名} 有一条 CMD 分支长得不对")
            阈值 = 条目.get("threshold")
            if not isinstance(阈值, (int, float)):
                raise ValueError(f"{文件名} 有一条 CMD threshold 不是数字")
            if 上个阈值 is not None and 阈值 <= 上个阈值:
                raise ValueError(f"{文件名} 的 CMD threshold 没按升序排，客户端会抽风")
            上个阈值 = float(阈值)
            新条目.append({
                "threshold": 阈值,
                "model": 精简直接模型(条目["model"], 文件名),
            })

        新分发 = {
            键: 值
            for 键, 值 in 分发.items()
            if 键 not in {"type", "property", "fallback", "entries"}
        }
        新分发.update({
            "type": "minecraft:range_dispatch",
            "property": "minecraft:custom_model_data",
            "fallback": 新回退,
            "entries": 新条目,
        })
        内容["model"] = 规范物品模型节点(新分发)
        文件[文件名] = 写_json(内容)
        已修复.append(文件名)
    return sorted(已修复)


def 检查物品模型(文件: dict[str, bytes]) -> None:
    """拦住刚才那种串台 JSON，免得下次合包又把坑带回来。"""
    def 检查节点(节点: Any, 文件名: str) -> None:
        if isinstance(节点, list):
            for 项 in 节点:
                检查节点(项, 文件名)
            return
        if not isinstance(节点, dict):
            return

        类型 = str(节点.get("type", "")).split(":")[-1]
        if 类型 == "model" and any(键 in 节点 for 键 in ("cases", "fallback", "property")):
            raise ValueError(f"{文件名} 还有 model/select 串台，不能发给玩家")
        for 值 in 节点.values():
            检查节点(值, 文件名)

    for 文件名, 数据 in 文件.items():
        if "/items/" not in f"/{文件名}" or not 文件名.endswith(".json"):
            continue
        检查节点(读_json(数据, 文件名), 文件名)


def 隔离新版实体着色器(文件: dict[str, bytes]) -> dict[str, Any]:
    """1.21.11 换了实体着色器接口，IA 旧版硬套上去就会让皮肤和物品隐身。"""
    元数据路径 = "pack.mcmeta"
    元数据 = 读_json(文件[元数据路径], 元数据路径)
    if not isinstance(元数据, dict):
        raise ValueError("pack.mcmeta 根节点不对，覆盖层没法安全拆")

    覆盖层 = 元数据.get("overlays", {}).get("entries")
    if not isinstance(覆盖层, list):
        raise ValueError("pack.mcmeta 没有正常 overlays.entries")

    旧目录 = "ia_overlay_1_21_6_plus"
    安全目录 = "ia_overlay_1_21_11_plus_safe"
    旧覆盖 = next(
        (项 for 项 in 覆盖层 if isinstance(项, dict) and 项.get("directory") == 旧目录),
        None,
    )
    if 旧覆盖 is None:
        return {
            "legacy_overlay": None,
            "safe_overlay": None,
            "unsafe_shaders_excluded": [],
            "safe_files": 0,
        }

    旧覆盖["formats"] = [63, 74]
    旧覆盖["min_format"] = 63
    旧覆盖["max_format"] = 74
    覆盖层[:] = [
        项
        for 项 in 覆盖层
        if not (isinstance(项, dict) and 项.get("directory") == 安全目录)
    ]
    覆盖层.append({
        "directory": 安全目录,
        "formats": [75, 9999],
        "min_format": 75,
        "max_format": 9999,
    })

    排除的相对路径 = {
        "assets/minecraft/shaders/core/entity.vsh",
        "assets/minecraft/shaders/core/entity.fsh",
    }
    旧前缀 = f"{旧目录}/"
    安全前缀 = f"{安全目录}/"
    for 文件名 in [名称 for 名称 in 文件 if 名称.startswith(安全前缀)]:
        del 文件[文件名]

    已排除: list[str] = []
    安全文件数 = 0
    for 文件名, 数据 in list(文件.items()):
        if not 文件名.startswith(旧前缀):
            continue
        相对路径 = 文件名[len(旧前缀):]
        if 相对路径 in 排除的相对路径:
            已排除.append(相对路径)
            continue
        文件[f"{安全前缀}{相对路径}"] = 数据
        安全文件数 += 1

    if set(已排除) != 排除的相对路径:
        少的 = "、".join(sorted(排除的相对路径 - set(已排除)))
        raise ValueError(f"该隔离的旧实体着色器没找全：{少的}")

    文件[元数据路径] = 写_json(元数据)
    return {
        "legacy_overlay": [63, 74],
        "safe_overlay": [75, 9999],
        "unsafe_shaders_excluded": sorted(已排除),
        "safe_files": 安全文件数,
    }


def 移除跨版本盾牌副本(文件: dict[str, bytes]) -> list[str]:
    """这三份只是某一版原版副本，留在跨版本包里反而会把别的版本盾牌搞透明。"""
    路径 = {
        "assets/minecraft/items/shield.json",
        "assets/minecraft/models/item/shield.json",
        "assets/minecraft/models/item/shield_blocking.json",
    }
    已移除: list[str] = []
    for 文件名 in list(文件):
        相对路径 = 文件名.split("/", 1)[1] if 文件名.startswith("ia_overlay_") and "/" in 文件名 else 文件名
        if 相对路径 in 路径:
            del 文件[文件名]
            已移除.append(文件名)
    return sorted(已移除)


def 修复PNG校验和(文件: dict[str, bytes]) -> list[str]:
    """有些 IA 内置图能被宽松解码器读，CRC 却是坏的；客户端换实现就容易变紫黑块。"""
    已修复: list[str] = []
    签名 = b"\x89PNG\r\n\x1a\n"
    for 文件名, 数据 in list(文件.items()):
        if not 文件名.lower().endswith(".png") or not 数据.startswith(签名):
            continue

        位置 = len(签名)
        输出 = bytearray(签名)
        块序号 = 0
        找到结尾 = False
        有变化 = False
        while 位置 < len(数据):
            if 位置 + 12 > len(数据):
                raise ValueError(f"{文件名} 的 PNG 块头被截断了")
            长度 = struct.unpack(">I", 数据[位置:位置 + 4])[0]
            结束 = 位置 + 12 + 长度
            if 结束 > len(数据):
                raise ValueError(f"{文件名} 的 PNG 块数据被截断了")
            类型 = 数据[位置 + 4:位置 + 8]
            内容 = 数据[位置 + 8:位置 + 8 + 长度]
            原校验 = struct.unpack(">I", 数据[位置 + 8 + 长度:结束])[0]
            新校验 = zlib.crc32(类型 + 内容) & 0xFFFFFFFF
            if 原校验 != 新校验:
                有变化 = True

            if 块序号 == 0 and 类型 != b"IHDR":
                raise ValueError(f"{文件名} 第一块不是 IHDR")
            输出.extend(struct.pack(">I", 长度))
            输出.extend(类型)
            输出.extend(内容)
            输出.extend(struct.pack(">I", 新校验))
            位置 = 结束
            块序号 += 1
            if 类型 == b"IEND":
                找到结尾 = True
                break

        if not 找到结尾:
            raise ValueError(f"{文件名} 根本没有 IEND，图片真被截断了")
        if 位置 != len(数据):
            # IEND 后面藏垃圾字节没任何正经用途，宽松解码器能忍，换实现就可能直接拒收。
            有变化 = True
        if 有变化:
            文件[文件名] = bytes(输出)
            已修复.append(文件名)
    return sorted(已修复)


def 规范损坏PNG(文件: dict[str, bytes]) -> list[str]:
    """宽松解码一次再老实写回去，别把 IA 那些截断流继续甩给不同客户端碰运气。"""
    from PIL import Image, ImageFile

    已重写: list[str] = []
    签名 = b"\x89PNG\r\n\x1a\n"
    for 文件名, 数据 in list(文件.items()):
        if not 文件名.lower().endswith(".png") or not 数据.startswith(签名):
            continue

        try:
            with Image.open(io.BytesIO(数据)) as 图片:
                图片.load()
            continue
        except Exception:
            pass

        原设置 = ImageFile.LOAD_TRUNCATED_IMAGES
        try:
            ImageFile.LOAD_TRUNCATED_IMAGES = True
            with Image.open(io.BytesIO(数据)) as 原图:
                原图.load()
                图片 = 原图.copy()
                保存参数: dict[str, Any] = {"format": "PNG", "optimize": True}
                if "transparency" in 原图.info:
                    保存参数["transparency"] = 原图.info["transparency"]
                输出 = io.BytesIO()
                图片.save(输出, **保存参数)
                新数据 = 输出.getvalue()
        except Exception as 异常:
            raise ValueError(f"{文件名} 连宽松解码都救不回来：{异常}") from 异常
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = 原设置

        # 重新编码后还读不全就别发，紫黑块不能靠运气。
        with Image.open(io.BytesIO(新数据)) as 检查图:
            检查图.load()
        文件[文件名] = 新数据
        已重写.append(文件名)
    return sorted(已重写)


def 修复物品图集(文件: dict[str, bytes]) -> list[str]:
    """新客户端不让一件物品横跨两个图集，这里把 IA 盔甲的物品贴图补进来。"""
    需要补进物品图集: set[str] = set()
    for 文件名, 数据 in 文件.items():
        if "/models/item/ia_auto/" not in 文件名 or not 文件名.endswith(".json"):
            continue

        模型 = 读_json(数据, 文件名)
        if not isinstance(模型, dict):
            continue
        纹理 = 模型.get("textures")
        if not isinstance(纹理, dict):
            continue

        纹理值 = [值 for 值 in 纹理.values() if isinstance(值, str) and not 值.startswith("#")]
        有物品纹理 = any(
            (值.split(":", 1)[-1]).startswith("item/")
            for 值 in 纹理值
        )
        if not 有物品纹理:
            continue

        for 值 in 纹理值:
            相对路径 = 值.split(":", 1)[-1]
            if 相对路径.startswith("armor/"):
                需要补进物品图集.add(值)

    if not 需要补进物品图集:
        return []

    图集路径 = "assets/minecraft/atlases/items.json"
    if 图集路径 in 文件:
        图集 = 读_json(文件[图集路径], 图集路径)
        if not isinstance(图集, dict):
            raise ValueError(f"{图集路径} 的根不是对象，这玩意没法接着补")
    else:
        图集 = {}

    原来源 = 图集.get("sources", [])
    if not isinstance(原来源, list):
        raise ValueError(f"{图集路径} 的 sources 不是数组，这配置有点抽象")
    新来源 = [{"type": "single", "resource": 纹理} for 纹理 in sorted(需要补进物品图集)]
    图集["sources"] = 合并数组([原来源, 新来源])
    文件[图集路径] = 写_json(图集)
    return sorted(需要补进物品图集)


def 合并字典(来源: list[tuple[str, dict[str, Any]]], 名称: str) -> dict[str, Any]:
    结果: dict[str, Any] = {}
    for 来源名, 字典 in 来源:
        for 键, 值 in 字典.items():
            if 键 in 结果 and 结果[键] != 值:
                raise ValueError(f"{名称} 的键 {键!r} 在 {来源名} 里撞车了")
            结果[键] = 值
    return 结果


def 合并数组(来源: list[list[Any]]) -> list[Any]:
    结果: list[Any] = []
    已有: set[str] = set()
    for 数组 in 来源:
        for 项 in 数组:
            指纹 = json.dumps(项, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if 指纹 not in 已有:
                结果.append(项)
                已有.add(指纹)
    return 结果


def 提供器字符(提供器: dict[str, Any]) -> set[str]:
    if 提供器.get("type") == "space":
        return set(提供器.get("advances", {}))
    return {字符 for 行 in 提供器.get("chars", []) for 字符 in 行}


def 合并字体(uhc数据: bytes, ia数据: bytes) -> tuple[bytes, dict[int, int]]:
    uhc = 读_json(uhc数据, "UHC 字体")
    ia = 读_json(ia数据, "ItemsAdder 字体")
    if not isinstance(uhc, dict) or not isinstance(ia, dict):
        raise ValueError("字体 JSON 的根不是对象，这就有点离谱了")

    # UHC 的 E008-E019 已经拿来画血条和图标了，IA 的冷却条整个搬家最省心。
    重映射 = {0xE006 + 序号: 0xE100 + 序号 for 序号 in range(21)}
    重映射[0xE01B] = 0xE115

    uhc提供器 = list(uhc.get("providers", []))
    ia提供器 = list(ia.get("providers", []))
    uhc字符 = set().union(*(提供器字符(项) for 项 in uhc提供器)) if uhc提供器 else set()
    结果提供器 = list(uhc提供器)

    for 原提供器 in ia提供器:
        提供器 = json.loads(json.dumps(原提供器, ensure_ascii=False))
        if 提供器.get("type") == "space":
            新间距: dict[str, Any] = {}
            for 字符, 宽度 in 提供器.get("advances", {}).items():
                新字符 = "".join(chr(重映射.get(ord(项), ord(项))) for 项 in 字符)
                if set(新字符) & uhc字符:
                    continue
                新间距[新字符] = 宽度
            if 新间距:
                提供器["advances"] = 新间距
                结果提供器.append(提供器)
            continue

        提供器["chars"] = [
            "".join(chr(重映射.get(ord(字符), ord(字符))) for 字符 in 行)
            for 行 in 提供器.get("chars", [])
        ]
        冲突 = 提供器字符(提供器) & uhc字符
        if 冲突:
            # 两边都做了负间距字形，UHC 那套更完整，重复塞进去反而会随机抢字形。
            if all(0xF800 <= ord(字符) <= 0xF8FF for 字符 in 冲突):
                continue
            编码 = "、".join(f"U+{ord(字符):04X}" for 字符 in sorted(冲突))
            raise ValueError(f"字体重映射后还撞了：{编码}")
        结果提供器.append(提供器)

    结果 = {键: 值 for 键, 值 in uhc.items() if 键 != "providers"}
    for 键, 值 in ia.items():
        if 键 == "providers":
            continue
        if 键 in 结果 and 结果[键] != 值:
            raise ValueError(f"字体根字段 {键!r} 撞车了，不能瞎覆盖")
        结果[键] = 值
    结果["providers"] = 结果提供器
    return 写_json(结果), 重映射


def 合并元数据(uhc数据: bytes, ia数据: bytes, 可用路径: set[str]) -> bytes:
    uhc = 读_json(uhc数据, "UHC pack.mcmeta")
    ia = 读_json(ia数据, "ItemsAdder pack.mcmeta")
    uhc覆盖 = uhc.get("overlays", {}).get("entries", [])
    ia覆盖 = ia.get("overlays", {}).get("entries", [])
    覆盖层 = [
        项
        for 项 in 合并数组([uhc覆盖, ia覆盖])
        if any(路径.startswith(f"{项['directory']}/") for 路径 in 可用路径)
    ]
    结果 = {
        "pack": {
            "pack_format": 75,
            "supported_formats": [32, 9999],
            "min_format": 32,
            "max_format": 9999,
            "description": "infiniteMC 全服材质包｜声音、界面和模型都在这儿",
        },
        "supported_formats": [32, 9999],
        "overlays": {"entries": 覆盖层},
    }
    for 键, 值 in ia.items():
        if 键 not in {"pack", "supported_formats", "overlays"}:
            结果[键] = 值
    return 写_json(结果)


def 写入并检查包(文件: dict[str, bytes], 输出路径: Path) -> bytes:
    输出路径.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(输出路径, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as 压缩包:
        for 文件名 in sorted(文件, key=str.casefold):
            信息 = zipfile.ZipInfo(文件名, date_time=(2026, 7, 26, 0, 0, 0))
            信息.compress_type = zipfile.ZIP_DEFLATED
            信息.external_attr = 0o100644 << 16
            压缩包.writestr(信息, 文件[文件名], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    with zipfile.ZipFile(输出路径) as 压缩包:
        坏文件 = 压缩包.testzip()
        if 坏文件:
            raise ValueError(f"最终包写坏了，坏在：{坏文件}")
        名称 = [项.filename for 项 in 压缩包.infolist() if not 项.is_dir()]
        if len(名称) != len({项.casefold() for 项 in 名称}):
            raise ValueError("最终包有重复或大小写撞车的路径")
        if "pack.mcmeta" not in 名称:
            raise ValueError("最终包根目录居然没有 pack.mcmeta")
        for 文件名 in 名称:
            安全路径(文件名)
            if 文件名.lower().endswith(".json") or 文件名 == "pack.mcmeta":
                读_json(压缩包.read(文件名), 文件名)

    return 输出路径.read_bytes()


def 合并包(gmusic路径: Path, uhc路径: Path, ia路径: Path, 输出路径: Path) -> dict[str, Any]:
    gmusic = 读取普通包(gmusic路径)
    uhc = 读取普通包(uhc路径)
    ia = 读取保护包(ia路径)

    结果 = dict(uhc)
    实际冲突: set[str] = set()
    for 来源名, 来源文件 in (("GMusic", gmusic), ("ItemsAdder", ia)):
        for 路径, 数据 in 来源文件.items():
            if 路径 not in 结果:
                结果[路径] = 数据
            elif 结果[路径] == 数据:
                continue
            elif 路径 in 需要手动合并的路径:
                实际冲突.add(路径)
            else:
                raise ValueError(f"{来源名} 的 {路径} 和 UHC 包撞了，还没写合并规则")

    声音来源 = []
    for 来源名, 文件 in (("UHC", uhc), ("ItemsAdder", ia), ("GMusic", gmusic)):
        数据 = 文件.get("assets/minecraft/sounds.json")
        if 数据 is not None:
            内容 = 读_json(数据, f"{来源名} sounds.json")
            if not isinstance(内容, dict):
                raise ValueError(f"{来源名} sounds.json 的根不是对象")
            声音来源.append((来源名, 内容))
    结果["assets/minecraft/sounds.json"] = 写_json(合并字典(声音来源, "sounds.json"))

    语言来源 = []
    for 来源名, 文件 in (("UHC", uhc), ("ItemsAdder", ia), ("GMusic", gmusic)):
        数据 = 文件.get("assets/minecraft/lang/en_us.json")
        if 数据 is not None:
            内容 = 读_json(数据, f"{来源名} en_us.json")
            if not isinstance(内容, dict):
                raise ValueError(f"{来源名} en_us.json 的根不是对象")
            语言来源.append((来源名, 内容))
    结果["assets/minecraft/lang/en_us.json"] = 写_json(合并字典(语言来源, "en_us.json"))

    uhc图集 = 读_json(uhc["assets/minecraft/atlases/blocks.json"], "UHC blocks 图集")
    ia图集 = 读_json(ia["assets/minecraft/atlases/blocks.json"], "ItemsAdder blocks 图集")
    图集结果 = dict(uhc图集)
    for 键, 值 in ia图集.items():
        if 键 == "sources":
            continue
        if 键 in 图集结果 and 图集结果[键] != 值:
            raise ValueError(f"blocks 图集的 {键!r} 撞车了")
        图集结果[键] = 值
    图集结果["sources"] = 合并数组([uhc图集.get("sources", []), ia图集.get("sources", [])])
    结果["assets/minecraft/atlases/blocks.json"] = 写_json(图集结果)

    字体, 重映射 = 合并字体(
        uhc["assets/minecraft/font/default.json"],
        ia["assets/minecraft/font/default.json"],
    )
    结果["assets/minecraft/font/default.json"] = 字体
    结果["pack.mcmeta"] = 合并元数据(
        uhc["pack.mcmeta"],
        ia["pack.mcmeta"],
        set(结果),
    )

    # pack.png 和 black.png 留 UHC 版本。后者只是同一个半透明黑点，编码方式不同而已。
    结果["pack.png"] = uhc["pack.png"]
    结果["assets/minecraft/textures/char/black.png"] = uhc[
        "assets/minecraft/textures/char/black.png"
    ]

    for 文件名, 数据 in list(结果.items()):
        if not 文件名.lower().endswith(".png") or 数据.startswith(b"\x89PNG\r\n\x1a\n"):
            continue
        if not 数据.startswith(b"\xff\xd8\xff"):
            raise ValueError(f"{文件名} 后缀写着 PNG，里面却不是图片，先别糊弄客户端")
        # 原 UHC 包有一张 JPEG 硬改成 .png，客户端不一定给面子，这里老实转回来。
        from PIL import Image

        with Image.open(io.BytesIO(数据)) as 图片:
            输出 = io.BytesIO()
            图片.save(输出, format="PNG", optimize=True)
            结果[文件名] = 输出.getvalue()

    移除的盾牌副本 = 移除跨版本盾牌副本(结果)
    修复的PNG = 修复PNG校验和(结果)
    重写的PNG = 规范损坏PNG(结果)
    修复的皮革模型 = 修复皮革物品模型(结果)
    着色器隔离 = 隔离新版实体着色器(结果)
    补进物品图集 = 修复物品图集(结果)
    检查物品模型(结果)
    数据 = 写入并检查包(结果, 输出路径)
    return {
        "gmusic_files": len(gmusic),
        "uhc_files": len(uhc),
        "itemsadder_files": len(ia),
        "merged_files": len(结果),
        "conflicts_handled": sorted(实际冲突),
        "cross_version_shield_copies_removed": 移除的盾牌副本,
        "png_crc_repaired": 修复的PNG,
        "png_streams_normalized": 重写的PNG,
        "leather_item_models_repaired": 修复的皮革模型,
        "shader_compatibility": 着色器隔离,
        "item_atlas_sprites_added": 补进物品图集,
        "font_remap": {
            f"U+{旧:04X}": f"U+{新:04X}" for 旧, 新 in sorted(重映射.items())
        },
        "size": len(数据),
        "sha1": hashlib.sha1(数据).hexdigest(),
        "sha256": hashlib.sha256(数据).hexdigest(),
    }


def 修复现有包(输入路径: Path, 输出路径: Path) -> dict[str, Any]:
    文件 = 读取普通包(输入路径)
    移除的盾牌副本 = 移除跨版本盾牌副本(文件)
    修复的PNG = 修复PNG校验和(文件)
    重写的PNG = 规范损坏PNG(文件)
    修复的皮革模型 = 修复皮革物品模型(文件)
    着色器隔离 = 隔离新版实体着色器(文件)
    补进物品图集 = 修复物品图集(文件)
    检查物品模型(文件)
    数据 = 写入并检查包(文件, 输出路径)
    return {
        "source": str(输入路径),
        "files": len(文件),
        "cross_version_shield_copies_removed": 移除的盾牌副本,
        "png_crc_repaired": 修复的PNG,
        "png_streams_normalized": 重写的PNG,
        "leather_item_models_repaired": 修复的皮革模型,
        "shader_compatibility": 着色器隔离,
        "item_atlas_sprites_added": 补进物品图集,
        "size": len(数据),
        "sha1": hashlib.sha1(数据).hexdigest(),
        "sha256": hashlib.sha256(数据).hexdigest(),
    }


def main() -> None:
    参数 = argparse.ArgumentParser(description="合并 infiniteMC 全服材质包")
    参数.add_argument("--gmusic", type=Path)
    参数.add_argument("--uhc", type=Path)
    参数.add_argument("--itemsadder", type=Path)
    参数.add_argument("--repair-existing", type=Path)
    参数.add_argument("--output", type=Path, required=True)
    参数.add_argument("--report", type=Path)
    配置 = 参数.parse_args()

    if 配置.repair_existing:
        if any((配置.gmusic, 配置.uhc, 配置.itemsadder)):
            参数.error("--repair-existing 不能跟三份源包一起塞，选一种就行")
        报告 = 修复现有包(配置.repair_existing, 配置.output)
    else:
        if not all((配置.gmusic, 配置.uhc, 配置.itemsadder)):
            参数.error("正常合并得同时给 --gmusic、--uhc 和 --itemsadder")
        报告 = 合并包(配置.gmusic, 配置.uhc, 配置.itemsadder, 配置.output)
    文本 = json.dumps(报告, ensure_ascii=False, indent=2) + "\n"
    if 配置.report:
        配置.report.parent.mkdir(parents=True, exist_ok=True)
        配置.report.write_text(文本, encoding="utf-8")
    print(文本, end="")


if __name__ == "__main__":
    main()
