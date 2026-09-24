#!/usr/bin/env bash
# run_tools.sh — 运行 tools/ 目录下的 Python 工具
#
# 用法:
#   bash run_tools.sh                 # 交互模式: 选择工具, 默认参数直接运行
#   bash run_tools.sh <tool> [参数]   # 直接模式: 运行 tools/<tool>.py, 需要特别参数时用这个
#   bash run_tools.sh list            # 列出可用工具
#   bash run_tools.sh -h              # 帮助
#
# 说明:
#   - <tool> 带不带 .py 后缀均可 (gen_manifest / tools/gen_manifest.py 都能识别)
#   - 参数里没有 --dir 时自动注入仓库根目录: tools 下脚本的 --dir 默认指向
#     自身目录, 会找不到 upload/ 等数据; 显式传了 --dir 则尊重用户的值

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="$SCRIPT_DIR/tools"

usage() {
    cat <<'EOF'
用法:
  bash run_tools.sh                 # 交互模式: 选择工具, 默认参数直接运行
  bash run_tools.sh <tool> [参数]   # 直接模式: 需要特别参数时末尾追加, 如 gen_manifest --dry-run
  bash run_tools.sh list            # 列出可用工具
EOF
}

list_tools() {
    local f
    for f in "$TOOLS_DIR"/*.py; do
        [[ -f "$f" ]] && printf '  %s\n' "$(basename "$f" .py)"
    done
}

# 解析工具名: 接受 gen_manifest / gen_manifest.py / tools/gen_manifest.py
resolve_tool() {
    local name="$1"
    name="$(basename "${name%.py}")"
    if [[ -f "$TOOLS_DIR/$name.py" ]]; then
        printf '%s' "$name"
        return 0
    fi
    return 1
}

run_direct() {
    local tool="$1"; shift
    local py="$TOOLS_DIR/$tool.py"
    local -a pyargs=()
    local a has_dir=0
    for a in "$@"; do
        if [[ "$a" == "--dir" || "$a" == "--dir="* ]]; then
            has_dir=1
        fi
        pyargs+=("$a")
    done
    if (( has_dir == 0 )); then
        pyargs=("--dir" "$SCRIPT_DIR" "${pyargs[@]}")
    fi

    printf '$ python3 %s' "$py"
    printf ' %q' "${pyargs[@]}"
    printf '\n'
    python3 "$py" "${pyargs[@]}"
    local rc=$?
    printf '退出码: %d\n' "$rc"
    return "$rc"
}

interactive() {
    local -a tools=()
    local f choice tool
    for f in "$TOOLS_DIR"/*.py; do
        [[ -f "$f" ]] && tools+=("$(basename "$f" .py)")
    done
    if (( ${#tools[@]} == 0 )); then
        printf '错误: %s 下没有 .py 脚本\n' "$TOOLS_DIR" >&2
        return 1
    fi

    while true; do
        printf '\n可用工具:\n'
        local i
        for i in "${!tools[@]}"; do
            printf '  %2d) %s\n' $((i + 1)) "${tools[i]}"
        done
        printf '  q) 退出\n'
        read -rp "选择 (1-${#tools[@]}) 或 q: " choice
        case "$choice" in
            q|Q|quit|exit) printf '退出\n'; return 0 ;;
        esac
        if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#tools[@]} )); then
            tool="${tools[choice - 1]}"
            printf '\n--- 运行 %s ---\n' "$tool"
            run_direct "$tool"
            return $?
        else
            printf '无效选择: %s\n' "$choice" >&2
        fi
    done
}

main() {
    if [[ ! -d "$TOOLS_DIR" ]]; then
        printf '错误: 未找到 tools 目录 (%s)\n' "$TOOLS_DIR" >&2
        return 1
    fi

    if (( $# == 0 )); then
        interactive
        return $?
    fi

    case "$1" in
        list|-l|--list) printf '可用工具:\n'; list_tools; return 0 ;;
        -h|--help|help) usage; return 0 ;;
    esac

    local tool
    if ! tool="$(resolve_tool "$1")"; then
        printf '错误: 未找到工具 %s (tools/ 下无对应 .py)\n' "$1" >&2
        printf '可用工具:\n' >&2
        list_tools >&2
        return 1
    fi
    shift
    run_direct "$tool" "$@"
}

main "$@"
