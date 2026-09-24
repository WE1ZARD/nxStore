#!/usr/bin/env bash

set -euo pipefail

REPO="${REPO:?}"
ISSUE="${ISSUE:?}"
COMMENT="${COMMENT:-}"

# 1. 取 issue
BODY="$(gh api "repos/$REPO/issues/$ISSUE" --jq .body)"

# 2. 抓附件 URL: 恰好 1 个 .zip + 恰好 1 个 .json (外部直链也可)
mapfile -t ZIP_URLS < <(grep -oE 'https://[^[:space:]")>]*\.zip' <<<"$BODY" || true)
mapfile -t JSON_URLS < <(grep -oE 'https://[^[:space:]")>]*\.json' <<<"$BODY" || true)
[[ ${#ZIP_URLS[@]} -eq 0 ]]  && { echo "错误: 没有 .zip 附件(把 {name}.zip 拖进 issue)"; exit 1; }
[[ ${#ZIP_URLS[@]} -gt 1 ]]  && { echo "错误: 找到 ${#ZIP_URLS[@]} 个 zip, 每次只提交 1 个包"; exit 1; }
[[ ${#JSON_URLS[@]} -eq 0 ]] && { echo "错误: 缺少 {name}.json 附件(元数据以 json 为准, 请一并上传)"; exit 1; }
[[ ${#JSON_URLS[@]} -gt 1 ]] && { echo "错误: 找到 ${#JSON_URLS[@]} 个 json, 只能附带 1 个元数据文件"; exit 1; }
ZIP_URL="${ZIP_URLS[0]}"; JSON_URL="${JSON_URLS[0]}"
echo "zip : $ZIP_URL"
echo "json: $JSON_URL"

# 3. 包名: /publish <name> 优先, 否则取 zip 文件名
NAME="$(sed -n 's|^/publish[[:space:]]\+\([^[:space:]]*\).*|\1|p' <<<"$COMMENT" | head -n1)"
[[ -z "$NAME" ]] && NAME="$(basename "$ZIP_URL" .zip)"
[[ "$NAME" =~ ^[A-Za-z0-9._-]{1,64}$ ]] && [[ -n "$NAME" ]] || { echo "错误: 非法包名 '$NAME'"; exit 1; }
echo "包名: $NAME"

# 4. json 内 name 一致性(不一致以文件名为准, 同 gen_manifest)
JSON_NAME="$(curl -fsSL --retry 3 "$JSON_URL" | python3 -c "import sys,json;print(json.load(sys.stdin).get('name',''))" 2>/dev/null || true)"
if [[ -n "$JSON_NAME" && "$JSON_NAME" != "$NAME" ]]; then
  echo "警告: json 内 name='$JSON_NAME' 与包名 '$NAME' 不一致, 将按 '$NAME' 入库"
fi

# 5. 同名冲突保护
if [[ -f "upload/$NAME.zip" || -f "zips/$NAME.zip" || -d "packages/$NAME" ]]; then
  echo "错误: 已存在同包 $NAME (upload/ 或 zips/ 或 packages/), 更新请走同名 PR"
  exit 1
fi

# 6. 下载两个附件到 upload/(公开附件无需鉴权; 失败时带 token 重试)
mkdir -p upload
dl() { # dl <url> <dest>
  local url="$1" dest="$2"
  if ! curl -fL --retry 3 -o "$dest" "$url"; then
    echo "无鉴权下载失败, 尝试带 token ..."
    curl -fL --retry 3 -H "Authorization: token $GH_TOKEN" -o "$dest" "$url"
  fi
}
dl "$ZIP_URL"  "upload/$NAME.zip"
dl "$JSON_URL" "upload/$NAME.json"
echo "已写入 upload/$NAME.zip + upload/$NAME.json"

# 7. 元数据校验(硬错误 → 回复 issue 并中止, 不产生 PR; 防止坏 json 进 repo.json)
echo "--- 元数据校验 ---"
if ! VOUT="$(python3 tools/validate_package.py --dir "$PWD" --file "upload/$NAME.json" 2>&1)"; then
  echo "$VOUT"
  MSG="❌ 元数据校验未通过, 请修正 {name}.json 后让维护者重新 /publish。

\`\`\`
$VOUT
\`\`\`"
  gh issue comment "$ISSUE" --body "$MSG"
  exit 1
fi
echo "$VOUT"
echo "校验通过 ✅"

# 8. 干跑一次生成 (校验 zip 完整性 + 预览产物), 失败不阻断开 PR
echo "--- gen_manifest --dry-run ---"
python3 tools/gen_manifest.py --dir "$PWD" --dry-run 2>&1 | tail -40 || true

# 9. 提交到分支 + 开 PR
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
BRANCH="upload/issue-$ISSUE"
git checkout -b "$BRANCH"
git add "upload/$NAME.zip" "upload/$NAME.json"
git commit -m "Add $NAME from issue #$ISSUE"
git push -u origin "$BRANCH"

PR_URL="$(gh pr create --base main --head "$BRANCH" \
  --title "Add $NAME (issue #$ISSUE)" \
  --body "From issue #$ISSUE. 合并后 publish workflow 会自动处理 upload/ 并更新商店。")"
echo "PR: $PR_URL"
gh issue comment "$ISSUE" --body "已生成待审核 PR: $PR_URL"
