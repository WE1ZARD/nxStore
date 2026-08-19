# 参与建设

## 参与方式

- 建议使用 PR
- 不会 PR 的朋友：直接在 issue 里传文件，审核后自动入库。

### 提交流程

1. 点击 **New issue** 提交以下内容到附件
   - `{name}.zip` 非加密压缩包, zip格式
   - `{name}.json` [基本信息](#基本信息)
   - `{name}.jpg` 封面[图标](#图标要求) (可选)
2. 等待维护者审核；通过后维护者回复 `/publish` → 系统自动抓取附件 → 自动开 PR
3. PR 复核合并 → 自动跑 `gen_manifest` 入库 (内层 zip → `zips/`，json → `repo.json`)→ 自动更新网站商店

> **附件上限约 25MB**；超出请用夸克网盘, "quark_url": "分享id",
> `/publish` 只有维护者可触发；校验不通过时**不会产生 PR**，issue 会收到带错误位置 (行:列)的回复。


### 入库规则

提交会经过 `tools/validate_package.py` 两道校验 (**开 PR 前** + **入库前**)：

**🚫 硬错误 — 会被拦截，必须修正**
- JSON 无法解析 (含**多余逗号**如 `{"a":1,}` 等，报错会带 行:列 定位)
- `name` 缺失 / 非法 (**只能使用英文/数字/`._-`**，且与文件名一致；不能中文或其他语言)
- `title` 缺失 / 非法 (**只能使用英文/数字/`._-`**，不能中文或其他语言)
- `author`缺失, 来源作者必填, 尤其是闭源应用
- `description` 中文描述
- `category` 缺失 / 不在分类表 (**分类只能使用英文**，见上文分类表；不能中文)
- `subcategory` (**子分类只能使用英文** 不能中文)
- `subcategory_cn` 写非中文的标题
- `quark_url` 托管但缺 `custom_dir` / `uninstall_dir`
- `github_url` 不是 `http(s)://` 链接或 `true`
- `direct_url` 不是完整链接

**😐 仅警告 — 不拦截，但建议补齐**
- `subcategory` 与 `subcategory_cn` 不成对


## 图标要求

- 命名: {name}.jpg
- 尺寸: 128px 或 256px
- 非必需项


## 基本信息

```json
{
	"category": "分类",
	"subcategory": "子分类", 
	"subcategory_cn": "子分类名",
	"name": "文件名",
	"title": "英文标题",
	"description": "中文简单描述",
	"author": "作者",
	"version": "版本号",
	"quark_url": "夸克分享链接id",
	"github_url": "开源下载页",
	"direct_url": "完整直链下载链接",
	"custom_dir": "自定义安装路径",
	"uninstall_dir": "自定义卸载路径"
}
```

- 命名: 
	- {name}.json.template -> {name}.json
	- 比如 `wiz.json, wiz.zip, wiz.jpg`
- `custom_dir`, `uninstall_dir`: 
	- quark 外部托管 (quark_url) 时必填, 否则跳过不发布
- `github_url`: 
	- 填写 release 地址 (`https://github.com/{owner}/{repo}/releases`, 比如: `https://github.com/WE1ZARD/Magic-Suite/releases`) 
- 填 `true` 仅当包名与仓库名相同时自动获取
- `version`: 
	- github_url 托管包**不需要填写**
	- quark 分享id, 必须填写


```
| 分类 | 英文名 | 中文名 |
|------|--------|--------|
| emu | Emulators | 模拟器 |
| game | Games | 游戏 |
| nro | Homebrew | 相册工具 |
| ovl | Overlays | 特斯拉插件 |
| patches | Patches | 增强补丁 |
| pkgs | Packages | 特斯拉插件包 |
| sys | System | 系统相关 |
| sysmod | SysMod | 系统模块 |
```
