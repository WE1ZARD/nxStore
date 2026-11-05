## SaltyNX 2.1.4
- NVN games should boot now faster
- Fix compatibility with OpenGL games that don't use uniform buffers for shaders (f.e. Dragon Quest Builders)
- Fix compatibility with OpenGL games having small thread stack on swap thread (f.e. Dragon Quest Builders)
- Fix compatibility with NVN games reserving 2GB for GPU use (Old Lego games)
	- Old NVN games have offset stored as signed 32-bit value so our new reservation was causing overflow in their case, Core now reserves buffer for shaders before game does it for GPU
- Fix compatibility with games using nn::diag::GetRequiredBufferSizeForGetAllModuleInfo() manually that abort when output is 0 (f.e. Hitman Absolution 1.4_107768, older updates don't use it)
- Increase size of NVNSampler to fit data expected by old and new NVN (code had size 0x30, old NVN used 0x60)
## WIZBOX 2.5.1
- 修复: 游戏库偶尔会缓存不成功的问题
## WIZBOX 2.5.0
- 修复: 错误/结果弹窗无法触屏关闭的问题, 现在点击弹窗外部或「返回」按钮即可关闭
- 修复: 自动超频写入成功后残留 `hoc.kip.bak`, 重启后它被当作 KIP 加载导致超频参数失效
