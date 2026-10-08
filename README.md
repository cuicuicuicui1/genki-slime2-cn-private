# 元气史莱姆2 NDS 汉化工程 / Slime Morimori Dragon Quest 2 Localization

> **公开仓库说明**：本仓库现在按“可研究、可复现、可协作”的汉化工程公开。为避免公开传播游戏本体，仓库不再保存日版 ROM、汉化 ROM、发行 ZIP、用户存档或模拟器；请使用自己合法取得的 ROM，按下方步骤做校验、提取和构建。

这是 NDS《Slime Morimori Dragon Quest 2 / 元气史莱姆2》的中文化逆向工程资料库。它不只是补丁文件，包含：

- 文本抽取结果、原文记录、译文记录、术语表与剩余扫描清单；
- NDS NitroFS／FAT 检查、资源包解包、文本占位符检查工具；
- 正文、姓名栏、暂停图形、原生 8/13/14px 字库相关的研究脚本；
- 字库来源、许可证、静态图形资源勘探结果和运行验证报告；
- 可供后来汉化者继续修改的分阶段构建记录。

## 快速开始

### 1. 准备自己的 ROM

将自己合法取得的日版 ROM 放在本地，先运行：

```powershell
python tools/nds_project.py info --rom "D:oms\Slime2_JP.nds" --expected-sha256 53a90729e750bf7288b41d205072138c14941e8810af70f4dc71a5dca6b5ba7b
```

这个 SHA-256 只用于确认研究基线，不会从仓库下载 ROM。

### 2. 安装研究依赖

```powershell
python -m pip install -r requirements.txt
```

Windows 用户建议使用 Python 3.11/3.12。需要无头 ARM 测试时再安装 `unicorn`；普通资源检查只需要 `ndspy`、`Pillow` 和 `fonttools`。

### 3. 查看和导出 NitroFS 文件

```powershell
python tools/nds_project.py list --rom "D:oms\Slime2_JP.nds"
python tools/nds_project.py extract --rom "D:oms\Slime2_JP.nds" --file msgdata.bin --out build\original\msgdata.bin
python tools/nds_project.py archive --rom "D:oms\Slime2_JP.nds" --file msgdata.bin --out build\msgdata-members
```

### 4. 检查译文是否破坏控制码

```powershell
python tools/translation_lint.py data/text/translations_appended10.json --source data/text/messages_jp.json
```

它会检查记录 ID、`<PAGE>`／`<WAIT>`／`<END>`／`<Fxxx>` 控制码、说话人栏结构和空译文；通过检查不等于已经完成游戏内实机验证。

## 工程结构

```text
data/
  text/          原文、译文、术语表、剩余记录
  manifests/     构建候选的结构和字库元数据
  reports/       受控 ARM/模拟器/存档回读报告
fonts/           字体源件与许可证
research/        静态 UI 资源勘探、图块预览、验证截图
tools/nds/       可复用的 NDS 编解码、字库、资源包模块
tools/patches/   分阶段回插和字库实验脚本（不包含 ROM）
docs/            逆向笔记、构建说明、贡献规则
examples/        可复制的配置示例
```

## 当前工程状态

仓库数据对应 2026-10-08 的 `clear-font-majority10` 研究节点：

- 正文实际回插 3505/3725 条扫描记录；这是记录比例，不代表剧情流程完成比例；
- 保留 60 个大名称图形、369 个固定姓名栏出现、4 个暂停图形和 2 个共用确认标签的记录；
- 字库采用原生 8/13/14px 路径，未用整屏放大或强行改窗口；
- 剩余重点包括标题／存档／姓名输入／教程与记录图形、部分菜单常量、动态姓名和少量特殊消费者；
- 旧实验中曾出现资源分配失败的候选，已在脚本说明和报告中标记，不应直接使用；
- 没有宣称全剧情、全菜单、全路线或硬件稳定。

更详细的边界见 [`docs/当前状态与验证边界.md`](docs/当前状态与验证边界.md)。

## 从哪里继续

- 想翻译对白：先看 [`docs/文本工作流.md`](docs/文本工作流.md) 和 `data/text/reviewed_text3550_including_holds06.json`。
- 想修字库：先看 [`docs/字库与字体残缺排查.md`](docs/字库与字体残缺排查.md)，不要直接扩大字库或改 ARM 常量。
- 想处理标题、存档、姓名输入、教程图形：先看 [`research/static-ui/inventory.json`](research/static-ui/inventory.json) 和 [`docs/图形文字工作流.md`](docs/图形文字工作流.md)。
- 想复现旧候选：查看 `tools/patches/` 的脚本头部注释和 `data/reports/` 的输入输出约束；脚本默认是研究工具，不是无条件安全的一键发布器。

## 贡献

欢迎提交：译文修订、术语统一、实机截图、资源消费者定位、字库缺字复现和测试报告。请不要提交 ROM、存档、模拟器安装包或未经许可的商业资源。详见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

## 许可证与第三方资源

本项目脚本和资料按仓库中的说明使用；字体并非本项目原创，`fonts/` 与 `字体许可与源件/` 内保留对应许可证和来源。游戏本体版权归原权利人所有，本仓库不授予游戏本体的再分发权。
