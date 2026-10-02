## EdiZon-Overlay 1.3.0
- 新增: 游戏列表, 可以管理金手指状态
## sys-clk 3.5.0
- 更新: 重新调整信息面板翻译, 对齐设置项名称 `充电 -> 充电电流`, `输入 -> 输入电流`
- 修复: 同步模式的错误, 比如 `主菜单+底座` 识别成 `官方充电器`
## Arcane 4.1.1
- 新增: `config/arcane/config.ini` 设置项 `show_arcane_versions`, `show_ovlloader_versions` 可以隐藏 arcane 和 ovlloader 的版本
	- 支持通过 `Settings 设置助手` 3.6.0+ 插件菜单项进行设置, 设置完成以后, 需要重启系统模块 `tesla`
## ## sphaira 2.1.0
- 新增: 文件浏览器显示系统模块名称
## WIZBOX 2.3.5
- 优化: 安装列表显示方式, 平铺式改成目录式
- 修复: 引导设置真实系统引导失效的问题, 会错误的写入 [Reboot::重启]
## WIZBOX 2.3.4
- 优化: 应用商店分类页有更新的应用优先显示, 其余按 a-z 排在其后
## WIZBOX 2.3.3
- 修复: 网盘登录cookies失效后, 重新发起扫码登录请求, 不再只报错
