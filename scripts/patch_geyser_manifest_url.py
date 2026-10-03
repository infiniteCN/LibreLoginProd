#!/usr/bin/env python3
"""把 Geyser 写死的旧 Mojang 清单地址换成现在能正常握手的地址。"""

from __future__ import annotations

import argparse
import hashlib
import struct
import zipfile
from pathlib import Path


TARGET_ENTRY = "org/geysermc/geyser/util/AssetUtils.class"
OLD_URL = b"https://launchermeta.mojang.com/mc/game/version_manifest.json"
NEW_URL = b"https://piston-meta.mojang.com/mc/game/version_manifest.json"


def patch_class(data: bytes) -> bytes:
    # 这是 class 常量池里的 UTF-8 项，前两个字节就是长度。只改这一个，别乱扫字符串。
    old_record = struct.pack(">H", len(OLD_URL)) + OLD_URL
    new_record = struct.pack(">H", len(NEW_URL)) + NEW_URL
    count = data.count(old_record)
    if count != 1:
        raise RuntimeError(f"目标地址应该刚好出现 1 次，实际是 {count} 次，先别硬改。")
    return data.replace(old_record, new_record, 1)


def patch_jar(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source, "r") as input_jar:
        names = input_jar.namelist()
        if TARGET_ENTRY not in names:
            raise RuntimeError(f"JAR 里找不到 {TARGET_ENTRY}，这包不对劲。")

        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w") as output_jar:
            for info in input_jar.infolist():
                payload = input_jar.read(info.filename)
                if info.filename == TARGET_ENTRY:
                    payload = patch_class(payload)
                output_jar.writestr(info, payload)

    # 写完再自己读一遍，免得生成个表面像 ZIP、实际一碰就炸的玩意。
    with zipfile.ZipFile(destination, "r") as result:
        bad_entry = result.testzip()
        patched = result.read(TARGET_ENTRY)
    if bad_entry is not None:
        raise RuntimeError(f"改完的 JAR 校验没过，坏在 {bad_entry}。")
    if OLD_URL in patched or NEW_URL not in patched:
        raise RuntimeError("地址没换干净，先别拿去开服。")


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="修一下 Geyser 还在用旧 Mojang 域名这件破事。")
    parser.add_argument("source", type=Path, help="官方 Geyser JAR")
    parser.add_argument("destination", type=Path, help="改好后放哪")
    args = parser.parse_args()

    patch_jar(args.source.resolve(), args.destination.resolve())
    print(f"改好了：{args.destination.resolve()}")
    print(f"SHA-256：{digest(args.destination.resolve())}")


if __name__ == "__main__":
    main()
