#!/usr/bin/env python3
"""upload/*.json 元数据校验器。

用途: 在两个入口挡住不规范的用户提交, 防止坏字段流入 repo.json 导致
应用端(WIZBOX 等)无法识别:
  1. issue-upload 流程: 开 PR 前校验 (硬错误不过关, 安全地不产生 PR)
  2. publish.yml: gen_manifest 入库前再校验一次 (防线)

硬错误(exit 1): JSON 无法解析 / name、title 仅英文数字._- 且缺失即拦 /
  author、description 缺失 / category、subcategory 仅英文白名单 /
  subcategory_cn 须中文 / 字段类型错误(version 允许纯数字) /
  quark 托管缺 custom_dir+uninstall_dir / github_url 非法。
软警告(仅提示): version 缺失(github_url 托管可省) / subcategory 不配对 /
  未知字段 / 无安装来源 / 空选填字段。

与 gen_manifest.py 的 README 字段约定保持一致。
"""

import argparse
import json
import os
import re
import sys

# 见 README 的 <category> 表
CATEGORIES = {
    "game", "emu", "tool", "advanced", "theme", "legacy", "mod",
    "patches", "nro", "ovl", "pkgs", "sysmod", "sys", "misc",
}

# gen_manifest 认识的字段 + 生态里合法的扩展字段(其余视为未知/警告)
KNOWN = {
    "name", "title", "author", "category", "version", "description",
    "subcategory", "subcategory_cn", "quark_url", "github_url",
    "custom_dir", "uninstall_dir", "check_init", "github_asset", "github",
    "require_reboot", "disable_uninstall",
}

# name: 只允许英文/数字/._- (不限制长度)
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# 必填字段(缺失即硬错误); version 单独处理(见下, github_url 托管包除外)
REQUIRED = ("title", "author", "description")
# 选填字符串字段(类型错为硬错误, 空值仅警告)
OPTIONAL_STR = (
    "subcategory", "subcategory_cn",
    "quark_url", "github_url", "custom_dir", "uninstall_dir",
)
RAW_EXTS = (".zip", ".nro", ".ovl", ".bin")


def validate(name_key, data, path, errors, warns):
    """对单个条目做检查, 追加到 errors/warns."""
    if not isinstance(data, dict):
        errors.append(f"{path}: json 顶层必须是对象(当前 {type(data).__name__})")
        return

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{path}: 缺少 name(必填, 仅使用英文/数字/._-, 与文件名一致)")
    elif not NAME_RE.match(name):
        errors.append(f"{path}: name '{name}' 非法——只能使用英文/数字/._-(不能中文或其他语言)")
    elif name_key and name != name_key:
        warns.append(f"{path}: json 内 name='{name}' 与文件名 '{name_key}' 不一致, 将以文件名为准")

    cat = data.get("category")
    if not isinstance(cat, str) or not cat.strip():
        errors.append(f"{path}: 缺少 category(必填, 只能使用英文分类, 见 README 分类表)")
    elif cat not in CATEGORIES:
        errors.append(f"{path}: category '{cat}' 不在白名单(只能使用英文分类名, 不能中文): {sorted(CATEGORIES)}")

    # 必填: title / author / description (缺失即硬错误)
    for k in REQUIRED:
        v = data.get(k)
        if not isinstance(v, str) or not v.strip():
            errors.append(f"{path}: 缺少必填字段 {k}")

    # title: 只允许英文/数字/._- 等, 不能中文(README 硬错误; 不限长度)
    ttl = data.get("title")
    if isinstance(ttl, str) and ttl.strip() and not ttl.isascii():
        errors.append(f"{path}: title 只能使用英文/数字/._-(不能中文或其他语言)")

    # version: 必填, 但 github_url 托管包除外(版本以 release tag 为准, 见 README)
    ver = data.get("version")
    if isinstance(ver, bool) or (ver is not None and not isinstance(ver, (str, int, float))):
        errors.append(f"{path}: version 必须是字符串或数字(当前是 {type(ver).__name__})")
    elif not (isinstance(ver, str) and ver.strip()) \
            and not isinstance(ver, (int, float)) \
            and not data.get("github_url"):
        errors.append(f"{path}: 缺少必填字段 version(github_url 托管包除外, 版本以 release 为准)")

    # 选填字符串字段: 类型错为硬错误, 空值仅警告
    for k in OPTIONAL_STR:
        v = data.get(k)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, str):
            errors.append(f"{path}: 字段 {k} 必须是字符串(当前是 {type(v).__name__})")
            continue
        if not v.strip():
            warns.append(f"{path}: 字段 {k} 为空(入库时会被省略)")

    # subcategory: 出现时只能英文(与 category/name 一致)
    sub = data.get("subcategory")
    if isinstance(sub, str) and sub.strip() and not sub.isascii():
        errors.append(f"{path}: subcategory 只能使用英文(不能中文或其他语言)")

    # subcategory_cn: 出现时必须写中文标题(README: 不能写非中文标题)
    scn = data.get("subcategory_cn")
    if isinstance(scn, str) and scn.strip() and not re.search(r"[\u4e00-\u9fff]", scn):
        errors.append(f"{path}: subcategory_cn 须写中文标题(当前无中文字符)")

    # github_url 必须是 http(s) 或 "true"(按 README); quark_url 存分享码而非 URL,
    #   只要求非空且不含空白(如 fw1810.json 的 "0dfed7641e20")
    gh = data.get("github_url")
    if isinstance(gh, str) and gh.strip() and not gh.startswith(("http://", "https://")) \
            and gh != "true":
        errors.append(f"{path}: github_url 必须是 http(s):// 链接(或 github_url: true)")
    qk = data.get("quark_url")
    if isinstance(qk, str) and qk.strip() and (" " in qk or "\t" in qk):
        errors.append(f"{path}: quark_url 含空白, 请填分享码或完整链接")

    if data.get("quark_url") and not (data.get("custom_dir") and data.get("uninstall_dir")):
        errors.append(f"{path}: quark_url 托管时必须同时提供 custom_dir 和 uninstall_dir")

    if bool(data.get("subcategory")) != bool(data.get("subcategory_cn")):
        warns.append(f"{path}: subcategory 与 subcategory_cn 应成对填写")

    unknown = [k for k in data if k not in KNOWN]
    if unknown:
        warns.append(f"{path}: 未知字段 {unknown}(不会影响识别, 但请核对拼写)")


def main() -> int:
    ap = argparse.ArgumentParser(description="校验 upload/*.json 元数据格式")
    ap.add_argument("--dir", default=".", help="仓库根目录(含 upload/ zips/), 默认当前目录")
    ap.add_argument("--file", default=None, help="只校验单个 json 路径(绝对或相对 --dir)")
    ap.add_argument("--strict", action="store_true", help="把警告也计为失败")
    args = ap.parse_args()

    root = os.path.abspath(args.dir)
    errors, warns = [], []

    if args.file:
        files = [args.file if os.path.isabs(args.file)
                 else os.path.join(root, args.file)]
    else:
        up = os.path.join(root, "upload")
        files = [os.path.join(up, f) for f in sorted(os.listdir(up))
                 if f.lower().endswith(".json")] if os.path.isdir(up) else []

    if not files:
        print("没有需要校验的 upload/*.json")
        return 0

    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as e:
            errors.append(f"{os.path.relpath(f, root)}: JSON 无法解析({e})")
            continue
        except OSError as e:
            errors.append(f"{os.path.relpath(f, root)}: 读取失败({e})")
            continue
        name_key = os.path.splitext(os.path.basename(f))[0]
        validate(name_key, data, os.path.relpath(f, root), errors, warns)
        # 安装来源缺失只降级为警告: gen_manifest 会安全跳过这类条目,
        # 不会写入 repo.json、不影响应用端; 但提交者应该看到提示
        has_local = any(
            os.path.isfile(os.path.join(root, sub, name_key + ext))
            for sub in ("upload", "zips")
            for ext in RAW_EXTS)
        if not has_local and not (data.get("quark_url") or data.get("github_url")):
            warns.append(f"{os.path.relpath(f, root)}: 无安装来源(需 {name_key}.zip/nro/ovl 文件, "
                         f"或 quark_url / github_url 外部托管), 该项不会进入 repo.json")

    for w in warns:
        print("WARN:", w)
    for e in errors:
        print("ERROR:", e)
    print(f"文件 {len(files)} 个, {len(errors)} errors, {len(warns)} warnings")
    return 1 if (errors or (args.strict and warns)) else 0


if __name__ == "__main__":
    sys.exit(main())
