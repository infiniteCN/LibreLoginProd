#!/usr/bin/env python3
"""按真实客户端版本审计全服材质包，专门拦紫黑块、透明模型和跨版本着色器。"""

from __future__ import annotations

import argparse
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image


物品模型路径 = re.compile(r"^assets/([^/]+)/items/.+\.json$")
普通模型路径 = re.compile(r"^assets/([^/]+)/models/(.+)\.json$")


def 读_json(数据: bytes, 名称: str) -> Any:
    try:
        return json.loads(数据.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as 异常:
        raise ValueError(f"{名称} 不是正常 JSON：{异常}") from 异常


def 大版本(值: Any) -> int:
    if isinstance(值, int):
        return 值
    if isinstance(值, list) and 值 and isinstance(值[0], int):
        return 值[0]
    raise ValueError(f"资源包格式写得看不懂：{值!r}")


def 标识符(值: str) -> tuple[str, str]:
    if ":" in 值:
        命名空间, 路径 = 值.split(":", 1)
    else:
        命名空间, 路径 = "minecraft", 值
    return 命名空间, 路径


class 资源源:
    def __init__(self, 路径: Path):
        self.路径 = 路径
        self.压缩包: zipfile.ZipFile | None = None
        if 路径.is_file():
            self.压缩包 = zipfile.ZipFile(路径)
            self.名称 = set(self.压缩包.namelist())
        elif 路径.is_dir():
            self.名称 = {
                文件.relative_to(路径).as_posix()
                for 文件 in 路径.rglob("*")
                if 文件.is_file()
            }
        else:
            raise FileNotFoundError(f"客户端资源源不存在：{路径}")

    def 有(self, 路径: str) -> bool:
        return 路径 in self.名称

    def 读(self, 路径: str) -> bytes:
        if self.压缩包 is not None:
            return self.压缩包.read(路径)
        return (self.路径 / Path(*路径.split("/"))).read_bytes()

    def 关闭(self) -> None:
        if self.压缩包 is not None:
            self.压缩包.close()


@dataclass(frozen=True)
class 目标:
    名称: str
    格式: int
    资源: 资源源


def 解析目标(文本: str) -> 目标:
    try:
        名称, 格式文本, 路径文本 = 文本.split("=", 2)
        return 目标(名称, int(格式文本), 资源源(Path(路径文本)))
    except ValueError as 异常:
        raise ValueError("--target 要写成 名称=资源格式=客户端JAR或资源目录") from 异常


def 覆盖层范围(条目: dict[str, Any]) -> tuple[int, int]:
    if "min_format" in 条目 or "max_format" in 条目:
        if "min_format" not in 条目 or "max_format" not in 条目:
            raise ValueError(f"覆盖层 {条目.get('directory')} 少写了一半 min/max_format")
        return 大版本(条目["min_format"]), 大版本(条目["max_format"])
    格式 = 条目.get("formats")
    if isinstance(格式, list) and len(格式) == 2:
        return int(格式[0]), int(格式[1])
    if isinstance(格式, int):
        return 格式, 格式
    raise ValueError(f"覆盖层 {条目.get('directory')} 没写正常版本范围")


def 检查覆盖层元数据(覆盖层: list[dict[str, Any]]) -> None:
    最低格式 = min(
        min(覆盖层范围(条目)[0], int(条目.get("formats", [999999])[0]) if isinstance(条目.get("formats"), list) else 999999)
        for 条目 in 覆盖层
    )
    跨旧版 = 最低格式 <= 64
    目录: set[str] = set()
    for 条目 in 覆盖层:
        名称 = 条目.get("directory")
        if not isinstance(名称, str) or not re.fullmatch(r"[-_a-zA-Z0-9.]+", 名称):
            raise ValueError(f"覆盖层目录名不合法：{名称!r}")
        if 名称 in 目录:
            raise ValueError(f"覆盖层目录重复了：{名称}")
        目录.add(名称)

        最小, 最大 = 覆盖层范围(条目)
        if 最小 > 最大:
            raise ValueError(f"覆盖层 {名称} 的最小格式比最大格式还大")
        旧格式 = 条目.get("formats")
        if 跨旧版 and 旧格式 is None:
            raise ValueError(f"覆盖层 {名称} 少了 formats，跨 64 以前版本时客户端会拒绝整组覆盖层")
        if isinstance(旧格式, list) and len(旧格式) == 2:
            if int(旧格式[0]) != 最小:
                raise ValueError(f"覆盖层 {名称} 的 formats/min_format 起点对不上")
            if int(旧格式[1]) not in {最大, 64}:
                raise ValueError(f"覆盖层 {名称} 的 formats/max_format 终点对不上")


def 生成有效资源(
    所有文件: dict[str, bytes],
    覆盖层: list[dict[str, Any]],
    格式: int,
) -> tuple[dict[str, bytes], list[str]]:
    覆盖目录 = {条目["directory"] for 条目 in 覆盖层}
    有效 = {
        路径: 数据
        for 路径, 数据 in 所有文件.items()
        if 路径.split("/", 1)[0] not in 覆盖目录
    }
    已应用: list[str] = []
    for 条目 in 覆盖层:
        最小, 最大 = 覆盖层范围(条目)
        if not 最小 <= 格式 <= 最大:
            continue
        目录 = 条目["directory"]
        前缀 = f"{目录}/"
        已应用.append(目录)
        for 路径, 数据 in 所有文件.items():
            if 路径.startswith(前缀):
                有效[路径[len(前缀):]] = 数据
    return 有效, 已应用


def 找节点(节点: Any):
    if isinstance(节点, dict):
        yield 节点
        for 值 in 节点.values():
            yield from 找节点(值)
    elif isinstance(节点, list):
        for 值 in 节点:
            yield from 找节点(值)


def 从包或原版读取(有效: dict[str, bytes], 原版: 资源源, 路径: str) -> bytes | None:
    if 路径 in 有效:
        return 有效[路径]
    if 原版.有(路径):
        return 原版.读(路径)
    return None


def 检查目标(
    目标项: 目标,
    所有文件: dict[str, bytes],
    覆盖层: list[dict[str, Any]],
    透明图片: set[str],
) -> dict[str, Any]:
    有效, 已应用 = 生成有效资源(所有文件, 覆盖层, 目标项.格式)
    错误: list[str] = []
    模型队列: list[str] = []
    已见模型: set[str] = set()
    用到的贴图: set[str] = set()

    for 路径, 数据 in 有效.items():
        if not 物品模型路径.match(路径):
            continue
        内容 = 读_json(数据, 路径)
        for 节点 in 找节点(内容):
            类型 = str(节点.get("type", "")).split(":")[-1]
            if 类型 == "model" and any(键 in 节点 for 键 in ("cases", "fallback", "property")):
                错误.append(f"{路径} 还有 model/select 串台")
            模型 = 节点.get("model")
            if 类型 == "model" and isinstance(模型, str):
                模型队列.append(模型)

    while 模型队列:
        模型编号 = 模型队列.pop()
        if 模型编号 in 已见模型:
            continue
        已见模型.add(模型编号)
        命名空间, 模型名 = 标识符(模型编号)
        if 模型名.startswith("builtin/"):
            continue
        路径 = f"assets/{命名空间}/models/{模型名}.json"
        数据 = 从包或原版读取(有效, 目标项.资源, 路径)
        if 数据 is None:
            错误.append(f"找不到模型 {模型编号}（{路径}）")
            continue
        内容 = 读_json(数据, 路径)
        if not isinstance(内容, dict):
            错误.append(f"{路径} 的根不是对象")
            continue
        父模型 = 内容.get("parent")
        if isinstance(父模型, str) and not 父模型.startswith("builtin/"):
            模型队列.append(父模型)
        贴图 = 内容.get("textures")
        if isinstance(贴图, dict):
            for 值 in 贴图.values():
                if not isinstance(值, str) or 值.startswith("#"):
                    continue
                纹理命名空间, 纹理名 = 标识符(值)
                # 盔甲纹饰是 atlas 的 paletted_permutations 现场生成，不会有同名实体 PNG。
                if 纹理命名空间 == "minecraft" and 纹理名.startswith("trims/items/"):
                    continue
                纹理路径 = f"assets/{纹理命名空间}/textures/{纹理名}.png"
                用到的贴图.add(纹理路径)
                if 从包或原版读取(有效, 目标项.资源, 纹理路径) is None:
                    错误.append(f"{路径} 引用了不存在的贴图 {值}")

    for 纹理路径 in sorted(用到的贴图 & 透明图片):
        错误.append(f"物品模型引用了全透明贴图：{纹理路径}")

    盾牌文件 = [
        "assets/minecraft/items/shield.json",
        "assets/minecraft/models/item/shield.json",
        "assets/minecraft/models/item/shield_blocking.json",
    ]
    盾牌一致: list[str] = []
    for 路径 in 盾牌文件:
        if not 目标项.资源.有(路径):
            continue
        包内 = 有效.get(路径)
        if 包内 is None:
            盾牌一致.append(f"{路径}:使用原版")
        elif 包内 == 目标项.资源.读(路径):
            盾牌一致.append(f"{路径}:逐字节一致")
        else:
            错误.append(f"{路径} 覆盖了 {目标项.名称} 原版盾牌资源")

    实体着色器 = [
        "assets/minecraft/shaders/core/entity.vsh",
        "assets/minecraft/shaders/core/entity.fsh",
    ]
    着色器状态: list[str] = []
    for 路径 in 实体着色器:
        包内 = 有效.get(路径)
        原版 = 目标项.资源.读(路径) if 目标项.资源.有(路径) else None
        if 包内 is None:
            着色器状态.append(f"{路径}:使用原版")
            continue
        if 原版 is None:
            着色器状态.append(f"{路径}:该版本没有同名原版资源")
            continue
        包版本 = 包内.decode("utf-8-sig", "replace").splitlines()[0].strip()
        原版版本 = 原版.decode("utf-8-sig", "replace").splitlines()[0].strip()
        if 目标项.格式 >= 75 and 包内 != 原版:
            错误.append(f"{路径} 在格式 {目标项.格式} 还覆盖原版，透明材质风险没清干净")
        elif 包版本 != 原版版本:
            错误.append(f"{路径} 的 GLSL 版本是 {包版本}，原版却是 {原版版本}")
        else:
            着色器状态.append(f"{路径}:{包版本}")

    if 目标项.格式 >= 75 and "ia_overlay_1_21_6_plus" in 已应用:
        错误.append("1.21.10 及以前的实体着色器覆盖层被错误套到了新客户端")
    if 目标项.格式 >= 75 and "ia_overlay_1_21_11_plus_safe" not in 已应用:
        错误.append("新客户端没吃到安全覆盖层")

    if 错误:
        raise ValueError(f"{目标项.名称} 审计没过：\n- " + "\n- ".join(sorted(set(错误))))
    return {
        "name": 目标项.名称,
        "format": 目标项.格式,
        "overlays": 已应用,
        "item_models_resolved": len(已见模型),
        "item_textures_resolved": len(用到的贴图),
        "shield": 盾牌一致,
        "entity_shaders": 着色器状态,
    }


def main() -> None:
    参数 = argparse.ArgumentParser(description="审计 infiniteMC 全服材质包")
    参数.add_argument("--pack", type=Path, required=True)
    参数.add_argument("--target", action="append", default=[], help="名称=资源格式=客户端JAR或资源目录")
    参数.add_argument("--report", type=Path)
    配置 = 参数.parse_args()
    if not 配置.target:
        参数.error("至少给一个 --target")

    目标列表 = [解析目标(文本) for 文本 in 配置.target]
    try:
        with zipfile.ZipFile(配置.pack) as 压缩包:
            坏文件 = 压缩包.testzip()
            if 坏文件:
                raise ValueError(f"ZIP 校验坏在：{坏文件}")
            名称 = [项.filename for 项 in 压缩包.infolist() if not 项.is_dir()]
            if len(名称) != len({项.casefold() for 项 in 名称}):
                raise ValueError("ZIP 里有重复或大小写撞车路径")
            所有文件 = {名称项: 压缩包.read(名称项) for 名称项 in 名称}

        元数据 = 读_json(所有文件["pack.mcmeta"], "pack.mcmeta")
        覆盖层 = 元数据.get("overlays", {}).get("entries", [])
        if not isinstance(覆盖层, list):
            raise ValueError("pack.mcmeta 的 overlays.entries 不是数组")
        检查覆盖层元数据(覆盖层)

        透明图片: set[str] = set()
        图片数量 = 0
        for 路径, 数据 in 所有文件.items():
            if not 路径.lower().endswith(".png"):
                continue
            图片数量 += 1
            try:
                with Image.open(io.BytesIO(数据)) as 图片:
                    图片.verify()
                with Image.open(io.BytesIO(数据)) as 图片:
                    宽, 高 = 图片.size
                    if 宽 <= 0 or 高 <= 0:
                        raise ValueError("尺寸是零")
                    if "A" in 图片.getbands() and 图片.convert("RGBA").getchannel("A").getextrema() == (0, 0):
                        透明图片.add(路径)
            except Exception as 异常:
                raise ValueError(f"{路径} 不是客户端能读的 PNG：{异常}") from 异常

        结果 = {
            "pack": str(配置.pack),
            "files": len(所有文件),
            "png_files_verified": 图片数量,
            "fully_transparent_png_files": sorted(透明图片),
            "targets": [
                检查目标(目标项, 所有文件, 覆盖层, 透明图片)
                for 目标项 in 目标列表
            ],
        }
        文本 = json.dumps(结果, ensure_ascii=False, indent=2) + "\n"
        if 配置.report:
            配置.report.parent.mkdir(parents=True, exist_ok=True)
            配置.report.write_text(文本, encoding="utf-8")
        print(文本, end="")
    finally:
        for 目标项 in 目标列表:
            目标项.资源.关闭()


if __name__ == "__main__":
    main()
