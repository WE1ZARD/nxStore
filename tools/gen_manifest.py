#!/usr/bin/env python3
"""
用法:
  python3 gen_manifest.py [--dir DIR] [--config-dirs config] [--dry-run]
"""

import argparse
import fnmatch
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
import zipfile

try:
    from PIL import Image
except ImportError:
    Image = None  # 缺 Pillow 时图标原样移动并警告

# repo.json 条目字段 (除 name 由文件名决定)
ENTRY_FIELDS = ("category", "subcategory", "subcategory_cn", "title", "description",
                "author", "version", "quark_url", "github_url", "custom_dir",
                "uninstall_dir", "check_init", "require_reboot", "disable_uninstall")

# 这些字段为空时不写入 repo.json
OPTIONAL_FIELDS = ("subcategory", "subcategory_cn", "quark_url", "github_url",
                   "custom_dir", "uninstall_dir")

# 非 zip 原始文件自动打包: 小写扩展名 -> zip 内安装路径 ({name} 为包名占位符)
# 打包出的 zips/{name}.zip 走与手打 zip 完全相同的 manifest 管线
RAW_ENTRY_MAP = {
    ".nro": "switch/{name}/{name}.nro",
    ".ovl": "switch/.overlays/{name}.ovl",
    ".bin": "bootloader/payloads/{name}.bin",  # 单文件 payload (如 modchip-toolbox)
}


def is_empty(v) -> bool:
    """None / 空串 / 纯空白视为空值."""
    return v is None or not str(v).strip()


def read_if_exists(path: str):
    """读取文件文本; 不存在或不可读返回 None."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def has_install_payload(root: str, name: str) -> bool:
    """upload/ 或 zips/ 下是否存在 name 的安装包 (zip / nro / ovl)."""
    for sub in ("upload", "zips"):
        d = os.path.join(root, sub)
        for ext in (".zip",) + tuple(RAW_ENTRY_MAP):
            if os.path.isfile(os.path.join(d, name + ext)):
                return True
    return False


def externally_hosted(data) -> bool:
    """条目是否外部托管 (quark_url / github_url / github): 是则只做记录, 无需本地安装包."""
    return (not is_empty(data.get("quark_url"))
            or not is_empty(data.get("github_url"))
            or data.get("github") is True)


GITHUB_API = "https://api.github.com"
GITHUB_UA = "wizbox-nxstore-gen-manifest/1.0"
GITHUB_TOKEN_ENV_NAMES = ("GH_TOKEN",)
GITHUB_AUTH_HOSTS = {"api.github.com", "github.com", "www.github.com"}


def github_auth_token():
    """读取 GitHub release 访问令牌, 不在日志中输出令牌内容."""
    for env_name in GITHUB_TOKEN_ENV_NAMES:
        token = os.environ.get(env_name, "").strip()
        if token:
            return token
    return None


def github_request(url: str, accept=None):
    """构造 GitHub 请求, 仅向 HTTPS GitHub 主机附加认证头."""
    parsed = urllib.parse.urlsplit(url)
    headers = {"User-Agent": GITHUB_UA}
    token = github_auth_token()
    if (token and parsed.scheme == "https"
            and parsed.hostname and parsed.hostname.lower() in GITHUB_AUTH_HOSTS):
        headers["Authorization"] = "Bearer " + token
    if accept:
        headers["Accept"] = accept
    return urllib.request.Request(url, headers=headers)


def github_auth_hint() -> str:
    """认证缺失时返回不泄露凭据的配置提示."""
    if github_auth_token():
        return ""
    return "；私有仓库请配置 GH_TOKEN"


def github_repo_of(data):
    """解析 github_url (兼容 github 字段别名) 为 (kind, target, pin):
    ('direct', 资产直链, tag) / ('repo', owner/repo, 钉定tag或None) / None.

    推荐统一填 release 地址 (https://github.com/{owner}/{repo}/releases[/latest|/tag/{tag}]
    或资产直链), 资产按包名 {name} 匹配; github_url 为 true 时按 {author}/{name} 推导,
    仅当包名与仓库名相同时可用 (如 SaltyNX)."""
    v = data.get("github_url")
    if is_empty(v) and data.get("github") is True:
        v = True  # 别名: github: true == github_url: true
    if isinstance(v, str) and v.strip():
        s = v.strip()
        if s.lower().startswith("http"):
            if "/releases/download/" in s:
                m = re.search(r"/releases/download/([^/]+)/", s)
                return ("direct", s, m.group(1) if m else None)
            s = s.split("?", 1)[0].rstrip("/")
            for pre in ("https://github.com/", "http://github.com/"):
                if s.startswith(pre):
                    parts = s[len(pre):].split("/")
                    if len(parts) >= 2 and parts[0] and parts[1]:
                        pin = None
                        if (len(parts) >= 4 and parts[2] == "releases"
                                and parts[3] == "tag" and len(parts) >= 5):
                            pin = parts[4]
                        return ("repo", "%s/%s" % (parts[0], parts[1]), pin)
            return None
        parts = s.split("/")
        if len(parts) == 2 and parts[0] and parts[1]:
            return ("repo", "%s/%s" % (parts[0], parts[1]), None)
        return None
    if v is True:
        author = data.get("author", "")
        name = data.get("name", "")
        if not is_empty(author) and not is_empty(name):
            return ("repo", "%s/%s" % (str(author).strip(), str(name).strip()), None)
    return None


def github_pick_asset(assets, name, pattern=None):
    """在 release 资产里挑最匹配的一个 (返回 asset dict 或 None).

    优先级: github_asset 显式模式 (fnmatch) > 精确 {name}{ext} >
    {下划线名}{ext} > 前缀 {name}-/{name}_ > 前缀 {name} > 该扩展名任意资产.
    这样即使 release 里有多个 zip (分平台/源码包等), 也能稳定选中包名的那个."""
    if pattern:
        cand = [a for a in assets
                if fnmatch.fnmatchcase(a.get("name", "").lower(), pattern.lower())]
        if cand:
            return cand[0]
    for ext in (".bin", ".nro", ".ovl", ".zip"):
        low = name.lower()
        exact = [a for a in assets if a.get("name", "").lower() == low + ext]
        if not exact:
            exact = [a for a in assets
                     if a.get("name", "").lower() == name.replace("-", "_").lower() + ext]
        if exact:
            return exact[0]
        pref = [a for a in assets
                if a.get("name", "").lower().endswith(ext)
                and (a.get("name", "").lower().startswith(low + "-")
                     or a.get("name", "").lower().startswith(low + "_"))]
        if not pref:
            pref = [a for a in assets
                    if a.get("name", "").lower().endswith(ext)
                    and a.get("name", "").lower().startswith(low)]
        if pref:
            return pref[0]
        fallback = [a for a in assets if a.get("name", "").lower().endswith(ext)]
        if fallback:
            return fallback[0]
    return None


def _files_equal(a: str, b: str) -> bool:
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            while True:
                ca, cb = fa.read(65536), fb.read(65536)
                if ca != cb:
                    return False
                if not ca:
                    return True
    except OSError:
        return False


def _zip_entry_equal(zip_path: str, entry: str, file_path: str) -> bool:
    """zips/{name}.zip 内已有条目且内容与待写入文件一致 (幂等判断)."""
    try:
        with zipfile.ZipFile(zip_path) as zf, open(file_path, "rb") as fp:
            return zf.read(entry) == fp.read()
    except (OSError, zipfile.BadZipFile, KeyError):
        return False


def github_version_of(tag):
    """release tag -> 版本号: 去掉常见前缀 (v/V/ver./release-), 空则返回 None."""
    s = re.sub(r"^(?:v|V|ver\.?|release[-_])", "", str(tag or "").strip())
    return s or None


def compare_versions(a, b):
    """数值段感知的版本比较 (与 WIZBOX CompareVersions 一致): 返回 -1/0/1."""
    i = j = 0
    while i < len(a) or j < len(b):
        adot = a.find('.', i)
        bdot = b.find('.', j)
        sa = a[i:] if adot == -1 else a[i:adot]
        sb = b[j:] if bdot == -1 else b[j:bdot]
        na, nb = sa.isdigit(), sb.isdigit()
        if na and nb:
            cmp_ = (int(sa) > int(sb)) - (int(sa) < int(sb))
        else:
            cmp_ = (sa > sb) - (sa < sb)
        if cmp_:
            return cmp_
        if adot == -1 and bdot == -1:
            return 0
        if adot == -1:
            return -1
        if bdot == -1:
            return 1
        i = adot + 1
        j = bdot + 1
    return 0


def github_latest_assets(repo, pin=None):
    """查询 release 的 (tag, 资产列表 [(name, url), ...]).

    pin 钉定指定 tag; 否则取最新发布 — 注意: GitHub 的 /releases/latest 端点
    排除预发布版, 这里改用完整 release 列表取最新一条 (含预发布, 不含草稿).
    优先 GitHub API; 遇限流/失败时回落 HTML (不消耗 API 配额). 完全失败返回 None."""
    if pin:
        api_url = "%s/repos/%s/releases/tags/%s" % (GITHUB_API, repo, urllib.parse.quote(pin))
    else:
        api_url = "%s/repos/%s/releases?per_page=1" % (GITHUB_API, repo)
    try:
        req = github_request(api_url, "application/vnd.github+json")
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
        if pin:
            rel = data
        else:
            if not isinstance(data, list) or not data:
                print("github %s: 仓库没有 release" % repo, file=sys.stderr)
                return None
            rel = data[0]
        return (rel.get("tag_name", ""),
                [(a["name"], a["browser_download_url"], a.get("id"))
                 for a in rel.get("assets", [])])
    except Exception:
        pass
    try:
        if pin:
            tag = pin
            page = "https://github.com/%s/releases/tag/%s" % (repo, urllib.parse.quote(pin))
        else:
            # releases 页按最新排序, 含预发布; 取第一条 release 的 tag
            page = "https://github.com/%s/releases" % repo
        req = github_request(page)
        with urllib.request.urlopen(req, timeout=60) as r:
            html = r.read().decode("utf-8", "replace")
        if not pin:
            m = re.search(r'href="/%s/releases/tag/([^"]+)"' % re.escape(repo), html)
            if not m:
                print("github %s: releases 页未找到任何 release" % repo, file=sys.stderr)
                return None
            tag = m.group(1)
        req = github_request(
            "https://github.com/%s/releases/expanded_assets/%s"
            % (repo, urllib.parse.quote(tag)))
        with urllib.request.urlopen(req, timeout=60) as r:
            html = r.read().decode("utf-8", "replace")
        pat = re.compile(r'href="/[^"/]+/[^"/]+/releases/download/%s/([^"]+)"'
                         % re.escape(tag))
        out = []
        for m in pat.finditer(html):
            raw = m.group(1)
            out.append((raw, "https://github.com/%s/releases/download/%s/%s"
                        % (repo, urllib.parse.quote(tag), urllib.parse.quote(raw)), None))
        return (tag, out)
    except Exception as e:
        print("github %s: release 查询失败 (API 限流或网络): %s%s" %
              (repo, e, github_auth_hint()), file=sys.stderr)
        return None


def fetch_github_package(root: str, name: str, data, dry_run: bool):
    """github_url 托管包自动拉取最新 release 资产.

    .zip 资产 -> zips/{name}.zip; .bin/.nro/.ovl 资产 -> upload/{name}{ext},
    由首遍 RAW_ENTRY_MAP 打包管线统一处理.
    返回 (status, version): status 为 'ok' / 'up-to-date' / 'failed';
    version 为 release tag 归一化的版本号 (推导失败时为 None)."""
    resolved = github_repo_of(data)
    if resolved is None:
        print("github %s: 无法解析 github_url (需 true 按 author/name 推导, 或 owner/repo / 仓库页 / 资产直链)"
              % name, file=sys.stderr)
        return ("failed", None)

    kind, target, pin = resolved
    version = None
    asset_id = None
    if kind == "direct":
        asset_name = target.rsplit("/", 1)[-1]
        version = github_version_of(pin)
    else:
        latest = github_latest_assets(target, pin)
        if latest is None:
            if not isinstance(data.get("github_url"), str):
                print("github %s: 提示 — 包名与仓库名(%s)不同时 author/name 推导会失败; "
                      "请把 github_url 填成 release 地址" % (name, target), file=sys.stderr)
            return ("failed", None)
        tag, assets = latest
        version = github_version_of(tag)
        asset = github_pick_asset(
            [{"name": n, "browser_download_url": u, "id": a_id} for n, u, a_id in assets],
            name, data.get("github_asset"))
        if asset is None:
            print("github %s: release 无匹配资产 (.bin/.nro/.ovl/.zip)" % name,
                  file=sys.stderr)
            return ("failed", None)
        asset_name = asset["name"]
        asset_id = asset.get("id")
        repo_name = target
        target = asset["browser_download_url"]

    ext = os.path.splitext(asset_name)[1].lower()
    if ext not in RAW_ENTRY_MAP and ext != ".zip":
        print("github %s: 资产扩展名 %s 不受支持 (仅 %s / .zip)"
              % (name, ext, "/".join(RAW_ENTRY_MAP)), file=sys.stderr)
        return ("failed", None)

    zips_dir = os.path.join(root, "zips")
    upload_dir = os.path.join(root, "upload")
    if dry_run:
        print("github %s: 将拉取 %s (dry-run)" % (name, target))
        return ("ok", version)

    # 相同 release 跳过下载: packages/{name}/info.json 记录的上次发布 tag 与当前
    # release tag 一致且本地 zip 已存在 → 直接视为已是最新, 不重复拉取资产
    if version:
        prev_tag = ""
        try:
            prev = read_if_exists(os.path.join(root, "packages", name, "info.json"))
            if prev:
                prev_tag = str(json.loads(prev).get("version", "") or "")
        except Exception:
            prev_tag = ""
        if prev_tag == version and os.path.isfile(os.path.join(zips_dir, name + ".zip")):
            return ("up-to-date", version)

    tmp = os.path.join(upload_dir, ".github-%s.download" % name)
    try:
        download_url = target
        accept = None
        if asset_id and github_auth_token():
            # 私有仓库: github.com 的 /releases/download 端点不接受 fine-grained token,
            # 改走 API 资产端点 (需要 Contents 读取权限)
            download_url = "%s/repos/%s/releases/assets/%s" % (GITHUB_API, repo_name, asset_id)
            accept = "application/octet-stream"
        req = github_request(download_url, accept)
        with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
    except Exception as e:
        print("github %s: 下载失败 (%s)%s" % (name, e, github_auth_hint()),
              file=sys.stderr)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return ("failed", None)

    if ext == ".zip":
        dst = os.path.join(zips_dir, name + ".zip")
        if os.path.isfile(dst) and _files_equal(tmp, dst):
            os.remove(tmp)
            return ("up-to-date", version)
        os.makedirs(zips_dir, exist_ok=True)
        os.replace(tmp, dst)
        print("github %s: %s -> zips/%s.zip" % (name, asset_name, name))
        return ("ok", version)

    entry = safe_rel(RAW_ENTRY_MAP[ext].format(name=name))
    src = os.path.join(upload_dir, name + ext)
    zip_path = os.path.join(zips_dir, name + ".zip")
    if os.path.isfile(zip_path) and _zip_entry_equal(zip_path, entry, tmp):
        os.remove(tmp)
        return ("up-to-date", version)
    if os.path.isfile(zip_path):
        os.remove(zip_path)  # 内容有变: 移除旧 zip, 让首遍按新文件重新打包
    os.replace(tmp, src)
    print("github %s: %s -> upload/%s%s" % (name, asset_name, name, ext))
    return ("ok", version)


def check_repo_payloads(root: str, repo) -> None:
    """巡检 repo.json 已有条目: 无安装来源、quark 托管缺 custom_dir/uninstall_dir、
    或 github 托管缺拉取产物的给出警告 (不删除, 仅提示)."""
    for e in repo.get("packages", []):
        name = e.get("name")
        if not name or has_install_payload(root, name):
            continue
        if externally_hosted(e):
            if not is_empty(e.get("quark_url")):
                if is_empty(e.get("custom_dir")) or is_empty(e.get("uninstall_dir")):
                    print("警告: repo.json 条目 %s 为 quark 外部托管但缺少 custom_dir/uninstall_dir"
                          % name, file=sys.stderr)
            elif not is_empty(e.get("github_url")):
                print("警告: repo.json 条目 %s 的 github 拉取产物缺失 (运行工具时会自动拉取)"
                      % name, file=sys.stderr)
            continue
        print("警告: repo.json 条目 %s 缺少安装包 (需 zips/%s.zip/nro/ovl, "
              "或 quark_url 并填写 custom_dir/uninstall_dir, 或 github_url 自动拉取)"
              % (name, name), file=sys.stderr)


def safe_rel(raw: str):
    """归一化为合法相对路径; 非法返回 None."""
    p = raw.replace("\\", "/")
    while p.startswith("/"):
        p = p[1:]
    if not p:
        return None
    if ":" in p or "//" in p:
        return None
    if p == ".." or p.startswith("../") or "/../" in p or p.endswith("/.."):
        return None
    return p


def classify(rel: str, g_dirs) -> str:
    return "G" if rel.split("/", 1)[0] in g_dirs else "U"


ICON_MAX_SIDE = 128  # 图标最长边上限 (px)


def shrink_icon(src: str, dst: str) -> bool:
    """将 src 图片最长边缩至 128px 内并保存为 jpg; 已达标返回 False (调用方原样移动)."""
    with Image.open(src) as im:
        im.load()  # 提前解码, 损坏文件在此抛 OSError
        if max(im.size) <= ICON_MAX_SIDE:
            return False
        im.thumbnail((ICON_MAX_SIDE, ICON_MAX_SIDE), Image.LANCZOS)
        im.convert("RGB").save(dst, "JPEG", quality=90)
        return True


def build_single_file_zip(zip_path: str, entry_rel: str, src: str) -> None:
    """把单个原始文件打包成单条目 zip (供 manifest 管线统一处理).

    调用方负责写 .tmp 再 os.replace, 与其余产出一致.
    """
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(src, entry_rel)


def reconcile_removed_packages(root: str, entries, active_names, dry_run: bool) -> bool:
    """删除不再有 upload/{name}.json 的派生产物和索引条目."""
    repo_changed = False
    packages_dir = os.path.join(root, "packages")
    if os.path.isdir(packages_dir):
        for name in sorted(os.listdir(packages_dir)):
            package_path = os.path.join(packages_dir, name)
            if name in active_names or not os.path.isdir(package_path):
                continue
            print("remove package %s" % os.path.relpath(package_path, root))
            if not dry_run:
                if os.path.islink(package_path):
                    os.unlink(package_path)
                else:
                    shutil.rmtree(package_path)

    zips_dir = os.path.join(root, "zips")
    if os.path.isdir(zips_dir):
        for zip_name in sorted(os.listdir(zips_dir)):
            if not zip_name.lower().endswith(".zip"):
                continue
            name = zip_name[:-4]
            zip_path = os.path.join(zips_dir, zip_name)
            if name in active_names or not os.path.isfile(zip_path):
                continue
            print("remove zip %s" % os.path.relpath(zip_path, root))
            if not dry_run:
                os.remove(zip_path)

    kept_entries = []
    for entry in entries:
        name = entry.get("name") if isinstance(entry, dict) else None
        if name and name not in active_names:
            print("repo.json: 移除已删除条目 %s" % name)
            repo_changed = True
            continue
        kept_entries.append(entry)
    if repo_changed:
        entries[:] = kept_entries
    return repo_changed


def process_manifest(root: str, g_dirs, dry_run: bool, active_names=None) -> None:
    zips_dir = os.path.join(root, "zips")
    if not os.path.isdir(zips_dir):
        return

    for zip_name in sorted(os.listdir(zips_dir)):
        if not zip_name.lower().endswith(".zip"):
            continue
        zip_path = os.path.join(zips_dir, zip_name)
        pkg_name = zip_name[:-4]
        if active_names is not None and pkg_name not in active_names:
            continue

        try:
            zf = zipfile.ZipFile(zip_path)
        except zipfile.BadZipFile:
            print("跳过(损坏): %s" % zip_name, file=sys.stderr)
            continue

        lines, skipped = [], []
        for info in zf.infolist():
            if info.is_dir() or info.filename.endswith("/"):
                continue
            rel = safe_rel(info.filename)
            if rel is None:
                skipped.append(info.filename)
                continue
            lines.append("%s: %s" % (classify(rel, g_dirs), rel))
        zf.close()

        if not lines:
            print("跳过(无文件): %s" % zip_name, file=sys.stderr)
            continue

        lines.sort()
        content = "\n".join(lines) + "\n"
        u_count = sum(1 for l in lines if l.startswith("U: "))

        out_path = os.path.join(root, "packages", pkg_name, "manifest.install")
        if read_if_exists(out_path) == content:
            continue  # 无变化, 不打印不重写
        print("manifest %s: %d 文件 (U:%d G:%d)" % (zip_name, len(lines), u_count, len(lines) - u_count))
        if skipped:
            print("  跳过不安全路径: %s" % ", ".join(skipped), file=sys.stderr)
        if dry_run:
            print("  [dry-run] -> %s" % out_path)
        else:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            tmp = out_path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            os.replace(tmp, out_path)


def load_repo_json(path: str):
    """读取 repo.json; 缺失或损坏时重建空结构."""
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("packages"), list):
                return data
            print("警告: %s 结构异常, 重建" % path, file=sys.stderr)
        except json.JSONDecodeError:
            print("警告: %s 无法解析, 重建" % path, file=sys.stderr)
    return {"packages": []}


def process_upload(root: str, dry_run: bool):
    """处理 upload/ 原始输入: zip -> zips/, jpg -> icon, json -> info.json + repo.json."""
    upload_dir = os.path.join(root, "upload")
    if not os.path.isdir(upload_dir):
        return None

    repo_json_path = os.path.join(root, "repo.json")
    repo = load_repo_json(repo_json_path)
    entries = repo["packages"]
    repo_changed = False

    # 清理历史遗留的空值可选字段 (写入侧已跳过, 此处迁移旧数据)
    for e in entries:
        for k in OPTIONAL_FIELDS:
            if k in e and is_empty(e[k]):
                del e[k]
                repo_changed = True

    zips_dir = os.path.join(root, "zips")

    # ── 第零遍: github_url/github 托管包自动拉取 (true 按 author/name 推导仓库;
    #    已有产物且内容未变则跳过; 版本号以 release tag 为准, 不回写 upload json) ──
    github_failed = set()
    github_versions = {}
    for fname in sorted(f for f in os.listdir(upload_dir) if f):
        if not fname.lower().endswith(".json"):
            continue
        name, _ = os.path.splitext(fname)
        try:
            with open(os.path.join(upload_dir, fname), encoding="utf-8") as f:
                gdata = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(gdata, dict):
            continue
        if is_empty(gdata.get("github_url")) and gdata.get("github") is not True:
            continue
        if any(os.path.isfile(os.path.join(upload_dir, name + e))
               for e in (".zip",) + tuple(RAW_ENTRY_MAP)):
            print("github %s: 已存在本地 upload 安装包, 以本地为准" % name)
            continue
        status, version = fetch_github_package(root, name, gdata, dry_run)
        if status == "failed":
            github_failed.add(name)
        else:
            # 归一化 github_url (true -> 仓库 URL; 钉定 tag 的 URL 原样保留)
            # 版本号不写回 upload json: github 包版本以 release tag 为准,
            # 由第二遍直接写入 packages/{name}/info.json, repo.json 不记录
            res = github_repo_of(gdata)
            norm = None
            if res and res[0] == "repo":
                if (isinstance(gdata.get("github_url"), str)
                        and "/releases/tag/" in str(gdata["github_url"])):
                    norm = str(gdata["github_url"]).split("?", 1)[0].rstrip("/")
                else:
                    norm = "https://github.com/" + res[1]
            elif res and res[0] == "direct":
                norm = res[1]
            changes = []
            if norm and gdata.get("github_url") != norm:
                gdata["github_url"] = norm
                changes.append("github_url -> %s" % norm)
            if version:
                github_versions[name] = version
                cur = str(gdata.get("version", "")).strip()
                if cur and compare_versions(version, cur) < 0:
                    print("github %s: release 版本 %s 低于 json 记录 %s, info.json 以 release 为准"
                          % (name, version, cur), file=sys.stderr)
            else:
                print("github %s: 未能从 release tag 推导版本号, packages 的 info.json "
                      "将无版本记录" % name, file=sys.stderr)
            if changes:
                if dry_run:
                    print("github %s: [dry-run] %s" % (name, "; ".join(changes)))
                else:
                    with open(os.path.join(upload_dir, fname), "w",
                              encoding="utf-8", newline="\n") as f:
                        json.dump(gdata, f, ensure_ascii=False, indent=4)
                    print("github %s: %s" % (name, "; ".join(changes)))

    # 拉取可能新放入 upload/{name}.bin 等文件, 重新扫描, 让后续各遍可见
    files = sorted(f for f in os.listdir(upload_dir) if f)
    active_names = {
        os.path.splitext(fname)[0]
        for fname in files
        if fname.lower().endswith(".json")
        and os.path.isfile(os.path.join(upload_dir, fname))
    }

    # ── 封面: upload/categories/<id>.jpg -> categories/<id>.jpg (缩放 128px) ──
    cover_src_dir = os.path.join(upload_dir, "categories")
    if os.path.isdir(cover_src_dir):
        cover_dst_dir = os.path.join(root, "categories")
        for fname in sorted(f for f in os.listdir(cover_src_dir) if f):
            name, ext = os.path.splitext(fname)
            if ext.lower() != ".jpg":
                print("忽略(封面仅支持 jpg): %s" % fname, file=sys.stderr)
                continue
            src = os.path.join(cover_src_dir, fname)
            dst = os.path.join(cover_dst_dir, name + ".jpg")
            print("cover %s -> %s" % (fname, os.path.relpath(dst, root)))
            if dry_run:
                print("  [dry-run] 移动")
                continue
            os.makedirs(cover_dst_dir, exist_ok=True)
            try:
                shrunk = shrink_icon(src, dst)
            except OSError:
                print("  警告: 图片解析失败, 原样移动: %s" % fname, file=sys.stderr)
                os.replace(src, dst)
            else:
                if shrunk:
                    print("  缩放至最长边 %dpx" % ICON_MAX_SIDE)
                    os.remove(src)
                else:
                    os.replace(src, dst)

    # ── 第一遍: 移动原始 zip / 打包原始 nro、ovl / 安装清单 / 图标 (先于 json, 使对应检查准确) ──
    for fname in files:
        name, ext = os.path.splitext(fname)
        src = os.path.join(upload_dir, fname)

        if ext.lower() == ".zip":
            dst = os.path.join(zips_dir, name + ".zip")
            print("zip %s -> %s" % (fname, os.path.relpath(dst, root)))
            if dry_run:
                print("  [dry-run] 移动")
            else:
                os.makedirs(zips_dir, exist_ok=True)
                os.replace(src, dst)
            continue

        if ext.lower() == ".install":
            # 外部托管包 (quark_url/github_url) 可选的手写安装清单,
            # 供其他客户端 (如 sphaira) 使用; 发布门槛见下方 json 检查
            dst = os.path.join(root, "packages", name, "manifest.install")
            print("install %s -> %s" % (fname, os.path.relpath(dst, root)))
            if dry_run:
                print("  [dry-run] 移动")
            else:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.replace(src, dst)
            continue

        raw_entry = RAW_ENTRY_MAP.get(ext.lower())
        if raw_entry is not None:
            entry_rel = safe_rel(raw_entry.format(name=name))
            if entry_rel is None:
                print("跳过(非法安装路径): %s" % fname, file=sys.stderr)
                continue
            dst = os.path.join(zips_dir, name + ".zip")
            if os.path.isfile(dst) or os.path.isfile(os.path.join(upload_dir, name + ".zip")):
                print("跳过(已有 %s.zip, 以 zip 为准): %s" % (name, fname), file=sys.stderr)
                continue
            print("raw %s -> %s  (%s)" % (fname, os.path.relpath(dst, root), entry_rel))
            if dry_run:
                print("  [dry-run] 打包为 zip 并移除原文件")
            else:
                os.makedirs(zips_dir, exist_ok=True)
                tmp = dst + ".tmp"
                build_single_file_zip(tmp, entry_rel, src)
                os.replace(tmp, dst)
                os.remove(src)
            continue

        if ext.lower() == ".jpg":
            icon_path = os.path.join(root, "packages", name, "icon.jpg")
            print("icon %s -> %s" % (fname, os.path.relpath(icon_path, root)))

            if Image is None:
                print("  警告: 未安装 Pillow, 跳过缩放, 原样移动", file=sys.stderr)
                if dry_run:
                    print("  [dry-run] 移动")
                else:
                    os.makedirs(os.path.dirname(icon_path), exist_ok=True)
                    os.replace(src, icon_path)
                continue

            if dry_run:
                try:
                    with Image.open(src) as im:
                        im.load()
                        too_big = max(im.size) > ICON_MAX_SIDE
                except OSError:
                    too_big = None
                if too_big is None:
                    print("  [dry-run] 原样移动 (图片解析失败)")
                elif too_big:
                    print("  [dry-run] 缩放至最长边 %dpx 后移动" % ICON_MAX_SIDE)
                else:
                    print("  [dry-run] 原样移动 (已 <= %dpx)" % ICON_MAX_SIDE)
                continue

            os.makedirs(os.path.dirname(icon_path), exist_ok=True)
            try:
                shrunk = shrink_icon(src, icon_path)
            except OSError:
                print("  警告: 图片解析失败, 原样移动: %s" % fname, file=sys.stderr)
                os.replace(src, icon_path)
            else:
                if shrunk:
                    print("  缩放至最长边 %dpx" % ICON_MAX_SIDE)
                    os.remove(src)
                else:
                    os.replace(src, icon_path)
            continue

        if ext.lower() == ".json":
            continue  # 第二遍统一处理元数据

        print("忽略(不支持的类型): %s" % fname, file=sys.stderr)
    if reconcile_removed_packages(root, entries, active_names, dry_run):
        repo_changed = True

    # ── 第二遍: 元数据 json -> info.json + repo.json (同时统一缩进) ──
    for fname in files:
        name, ext = os.path.splitext(fname)
        if ext.lower() != ".json":
            continue
        src = os.path.join(upload_dir, fname)

        with open(src, encoding="utf-8") as f:
            raw = f.read()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            # 坏 JSON(如多余逗号): 只跳过该条目, 绝不拖垮整批发布
            print("跳过(JSON 无法解析, 未写入 repo.json/packages): %s (%s)" % (fname, e),
                  file=sys.stderr)
            continue
        if not isinstance(data, dict):
            print("跳过(非对象 JSON): %s" % fname, file=sys.stderr)
            continue

        # github 拉取失败: 整条跳过, 不写 info.json/repo.json (避免覆盖已有记录)
        if name in github_failed:
            print("跳过(github 拉取失败, 未写入 repo.json/packages): %s" % fname,
                  file=sys.stderr)
            continue

        # ── 安装包检查: 本地 zip/nro/ovl/bin 直接发布; quark 托管须填写
        #    custom_dir 和 uninstall_dir (整包解压目标/卸载目录) ──
        if not has_install_payload(root, name):
            if externally_hosted(data):
                if not is_empty(data.get("quark_url")):
                    if is_empty(data.get("custom_dir")) or is_empty(data.get("uninstall_dir")):
                        print("跳过(quark 外部托管须填写 custom_dir 和 uninstall_dir): %s" % fname,
                              file=sys.stderr)
                        continue
            else:
                print("跳过(无安装包, 未写入 repo.json/packages): %s" % fname,
                      file=sys.stderr)
                continue

        # ── 归一化: 剔除空值 (只留非空), name 与文件名核对 ──
        # github 托管包: version 以 release tag 为准, 从 upload json 移除 (不记录)
        gh_version = github_versions.get(name)
        is_gh = (gh_version is not None or not is_empty(data.get("github_url"))
                 or data.get("github") is True)
        changed = False
        for k in list(data.keys()):
            if is_empty(data[k]):
                del data[k]
                changed = True
        if is_gh and "version" in data:
            print("github %s: 移除 upload json 中的 version (版本以 release 为准)" % name)
            del data["version"]
            changed = True
        if "name" not in data or is_empty(data["name"]):
            data["name"] = name  # 空/缺失时按文件名补全
            changed = True
        elif data["name"].lower() != name.lower():
            print("  警告: %s 的 name \"%s\" 与文件名 \"%s\" 不一致, 以文件名为准"
                  % (fname, data["name"], name), file=sys.stderr)

        # 统一格式: 4 空格缩进, 顺带去掉 tab/行尾空白 (数据未变也重写)
        canonical = json.dumps(data, ensure_ascii=False, indent=4)
        if changed or raw != canonical:
            reasons = []
            if changed:
                reasons.append("剔除空值/补全 name")
            if raw != canonical:
                reasons.append("统一缩进")
            if dry_run:
                print("  [dry-run] 重写 %s (%s)" % (fname, "/".join(reasons)))
            else:
                tmp = src + ".tmp"
                with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                    f.write(canonical)
                os.replace(tmp, src)

        # github 托管包: 版本直接取 release tag, 写入 packages/{name}/info.json
        version = str(gh_version if gh_version is not None else data.get("version", ""))
        info_path = os.path.join(root, "packages", name, "info.json")
        info_content = json.dumps({"version": version}, ensure_ascii=False)
        if read_if_exists(info_path) != info_content:
            print("info %s: version=%s" % (fname, version or "(空)"))
            if dry_run:
                print("  [dry-run] -> %s" % os.path.relpath(info_path, root))
            else:
                os.makedirs(os.path.dirname(info_path), exist_ok=True)
                tmp = info_path + ".tmp"
                with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                    f.write(info_content)
                os.replace(tmp, info_path)

        # ── repo.json: 全新追加 / 已存在只更新实际变化的字段 ──
        # github 包的 version 取 release tag (gh_version), 不回写 upload json
        def entry_value(k):
            if k == "version":
                v = gh_version if gh_version is not None else data.get("version")
                return None if isinstance(v, bool) or v is None else str(v)
            return data.get(k)

        existing = next((e for e in entries if e.get("name") == name), None)
        if existing is None:
            entry = {"name": name}
            for k in ENTRY_FIELDS:
                v = entry_value(k)
                if v is None:
                    continue
                if k not in OPTIONAL_FIELDS or not is_empty(v):
                    entry[k] = v
            entries.append(entry)
            repo_changed = True
            print("repo.json: 追加新条目 %s" % name)
        else:
            changed_keys = []
            for k in ENTRY_FIELDS:
                v = entry_value(k)
                if v is None:
                    continue
                if (k not in OPTIONAL_FIELDS or not is_empty(v)) and existing.get(k) != v:
                    existing[k] = v
                    changed_keys.append(k)
            if changed_keys:
                repo_changed = True
                print("repo.json: 更新条目 %s (%s)" % (name, ", ".join(changed_keys)))

    if repo_changed and not dry_run:
        tmp = repo_json_path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(repo, f, ensure_ascii=False, indent=4)
        os.replace(tmp, repo_json_path)
        print("repo.json 已更新")
    return active_names


def main() -> int:
    parser = argparse.ArgumentParser(description="repo 源批量发布: manifest + upload 同步")
    parser.add_argument("--dir", default=os.path.dirname(os.path.abspath(__file__)),
                        help="repo 根目录 (含 zips/ packages/ upload/ repo.json), 默认本脚本所在目录")
    parser.add_argument("--config-dirs", default="config",
                        help="映射为 G 命令的顶层目录, 逗号分隔; 默认 config")
    parser.add_argument("--dry-run", action="store_true", help="只打印, 不写文件/不移动")
    args = parser.parse_args()

    root = os.path.abspath(args.dir)
    g_dirs = set(d.strip() for d in args.config_dirs.split(",") if d.strip())

    active_names = process_upload(root, args.dry_run)
    process_manifest(root, g_dirs, args.dry_run, active_names)
    check_repo_payloads(root, load_repo_json(os.path.join(root, "repo.json")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
