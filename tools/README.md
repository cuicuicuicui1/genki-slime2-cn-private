# 工具目录

- `nds_project.py`：ROM SHA 校验、NitroFS 列表、文件导出、简单资源包解包；不会写输入 ROM。
- `translation_lint.py`：检查译文 ID、控制码、分页、说话人栏和空译文。
- `rom_audit.py`：只读比较两个 NDS 候选，检查 ARM/FNT 身份和 NitroFS allowlist。
- `run_headless.py`：按 JSON 输入计划运行 DeSmuME 无头测试，保存截图、SHA 和退出报告。
- `nds/`：可复用的 NDS 编解码、资源包、字库和布局模块。
- `patches/`：实际研究阶段的分阶段脚本。脚本顶部标注输入、输出和“实验/可发布”边界；不要跳过 manifest 和回读。

所有命令都从仓库根目录执行。脚本不会自动寻找或下载游戏 ROM。

`run_headless.py` 不会替代可视化模拟器；它适合冷启动、按键回归和截图证据。`rom_audit.py` 只读，不能修复候选 ROM。
