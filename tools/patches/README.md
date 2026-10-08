# 分阶段脚本说明

`tools/patches/` 是研究过程中的真实构建脚本，不是把 ROM 打包进仓库的“一键破解器”。每个脚本应先阅读头部注释，再按照自己的 ROM 路径、基线 SHA 和 manifest 调整参数。

## 脚本类别

| 类别 | 作用 | 默认风险边界 |
|---|---|---|
| `build_*body*` | 正文记录、固定姓名等回插 | 需要先做控制码／字库／布局检查 |
| `build_*speaker*` | 小姓名栏和说话人资源 | 容易受固定宽度和共享图块影响 |
| `build_*pause*` | 暂停界面图形文字 | 只允许在已定位的资源成员中改写 |
| `build_*font*` / `build_*native*` | 字库与原生字号试验 | 必须检查 RAM 上界、BSS 和字形完整性 |
| `build_*experiment*` | 失败或未完成方案 | 不得直接当成发行候选 |

## 推荐构建顺序

1. 用 `tools/nds_project.py info` 检查自己合法取得的日版 ROM SHA-256。
2. 用 `tools/nds_project.py extract/archive` 导出输入资源，保存 manifest。
3. 修改 `data/text/` 中的译文，运行 `tools/translation_lint.py`。
4. 只运行一个阶段脚本，输出到新的 `build/` 目录；不要覆盖输入 ROM 或已验收候选。
5. 用 `tools/rom_audit.py diff` 检查实际改变的 NitroFS 文件是否在脚本声明的 allowlist 内。
6. 使用 `tools/run_headless.py` 进行冷启动、截图和普通存档回读；即时存档不可跨 ROM SHA 复用。
7. 把候选 SHA、运行计划、退出码和失败边界写入 `data/reports/` 后再提交。

## 路径与基线

公开仓库不携带 ROM，也不保证所有旧脚本能在任意目录直接运行。旧脚本中若存在本地绝对路径，应替换为仓库根目录下的相对路径；不要删除 SHA 门禁来“让脚本跑起来”。
