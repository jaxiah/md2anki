# MEMORY

> 用于记录会话存档。新条目追加在最上方（倒序）。

## 当前长期化指令（常驻）

- 当用户明确说出“存档”时：
	- 必须更新根目录 `MEMORY.md`；
	- 记录本会话已完成事项、遇到的问题、解决方式、注意事项/风险点、长期化指令；
	- 同步任务状态清单（`[x]` 已完成 / `[-]` 进行中 / `[ ]` 下一步）。

---

## 会话归档 - 2026-03-01（E2E 里程碑）

### 时间
- 2026-03-01（本地时间）

### 本会话已完成事项
- 完成 Phase 3/4 关键实现收敛：`AnkiClient`（ADD/UPDATE/DELETE/SKIP、state 管理、dry-run）、过程式 `run_pipeline` 编排与 markdown 回写。
- 新增并完善 `DELETE` + `^noanki` 全链路能力：
	- parser 识别 `^anki-<id> DELETE` 与 `^noanki`；
	- delete 成功后写回“删除 `^anki` 行 + 补 `^noanki`”；
	- 冲突优先级 `DELETE > ^noanki`。
- 修复同文件多条 H4 写回错位问题：回写操作统一按锚点行号倒序执行，避免行号漂移。
- 补上父节点 block id 回写，并修复由“父节点预写回导致 H4 行号陈旧”引发的二次错位：预写回后重解析刷新行号。
- 将内容 hash 改为 markdown 语义（`deck + front_md + back_md + media_refs`），不再使用 `front_html/back_html_with_footer`。
- 新增 CLI 最小入口（默认 dry-run）与脚本注册，支持手动指定 vault/sync_state/file。
- 构建手动 E2E 套件与固定真实 vault：
	- `tests/e2e/manual_vault`（含多类型 markdown 与真实图片 `gwyn.jpg` 复制资产）；
	- `tests/e2e/test_manual_e2e_flow.py`（8 条严格时序 case，人工检查 Anki 侧）。
- 完成回归验证：单元测试全量通过（40 passed），pipeline 集成测试通过（9 passed），手动 E2E 多条关键 case 已通过。

### 遇到的问题
- `test_01_rerun_should_skip` 出现意外 UPDATE：首轮前后 footer 链接变化（父节点 block id）影响 hash。
- 同文件多条回写时出现 `^anki-...` 插入错位。
- 父节点 block id 曾未写回；补写后又引入“旧行号写回”的连锁问题。
- 手动 E2E 在 quiet 输出下“看起来没跑”，可观测性不足。

### 解决方式
- hash 改为 markdown-based，排除 HTML/footer 影响。
- pipeline 写回改为统一操作列表（bind/delete/parent）按行号倒序执行。
- 父节点预写回后立即重解析文件，刷新 H4 行号再执行后续回写。
- 增加多父节点/多 H4 的集成回归用例，覆盖写回位置与 parent id 写回。
- 将手动 E2E 门禁改为显式失败提示（含可复制命令），并移除全局 pytest quiet 以提升可见性。

### 注意事项 / 风险点
- 手动 E2E case 依赖严格顺序与前置状态；重跑前需将 `manual_vault` 与 Anki 测试 deck 手动回退/清理。
- `sync_state` 目前包含辅助字段（`source_file`/`h4_heading_pure`）用于可观测性，业务判定仅依赖 `anki_note_id -> content_hash`。
- 真实 E2E 会写入本地 Anki（`md2ankiTest` 前缀 deck）；建议继续使用前缀隔离并按批次清理。

### 用户长期化指令（持续生效）
- 用户说“存档”时，必须优先更新根目录 `MEMORY.md`，并按固定小节完整记录。
- 复杂代码生成任务默认流程：先设计文档 -> 用户 review 通过 -> 再开始编码。
- 项目重构保持轻量：3 类 + 过程式 pipeline，避免过度设计。
- 默认使用中文沟通（除非用户明确要求英文）。

### 任务状态清单
- [x] 已完成：Phase 1~4 现阶段核心能力（解析/渲染/同步/写回）、DELETE+^noanki 能力、CLI、单元与集成回归、手动 E2E 8 条用例设计与落地。
- [-] 进行中：手动真实 E2E 按顺序逐条复核（用户执行中）。
- [ ] 下一步：基于手动 E2E 结果做收尾修正；补充 Anki 侧人工核验清单文档与（可选）一键 reset 脚本。

## 会话归档 - 2026-03-01（续）

### 时间
- 2026-03-01（本地时间）

### 本会话已完成事项
- 完成 Phase 2 `HtmlRenderer` 的实现收敛与验证：公式保持原样、不做专门转换；wiki link / wiki image 渲染稳定。
- 完成 parser + renderer 两模块集成测试建设与回归：新增独立 fixture（markdown + assets），并确保关键场景通过。
- 按要求将集成测试图片 fixture 替换为根目录真实图片 `gwyn.jpg` 的内容，并通过哈希与测试回归确认。
- 为集成测试增加结果导出开关：
	- parser 结果导出 JSON；
	- renderer 结果导出 HTML 预览页。
- 将集成测试 renderer 导出变量重命名为 `DUMP_INTEGRATION_RENDERER_HTML`，并清理历史遗留 renderer JSON 产物。
- 同步更新 [refactor_design.md](refactor_design.md)：修正文档与当前实现不一致项（公式策略、集成测试方式、导出产物与开关命名）。

### 遇到的问题
- 集成测试导出格式从 JSON 改为 HTML 后，测试文件出现一次 `IndentationError`（缩进异常）。
- 文档中存在与现状不一致的描述（例如旧的数学归一化措辞、测试组织描述偏差）。

### 解决方式
- 立即修正 `tests/integration/test_parser_renderer_integration.py` 的函数缩进并回归测试，恢复为稳定通过。
- 对 `refactor_design.md` 进行最小同步修订：只改过期描述，不改整体设计结构。

### 注意事项 / 风险点
- 集成测试调试产物默认开启，长期运行会持续写入 `tests/integration/_parser_renderer_debug/`，可能带来工作区噪声。
- renderer 导出已切换为 HTML；如本地脚本仍使用旧环境变量名（`DUMP_INTEGRATION_RENDERER_JSON`）将不会生效。
- 当前仍未进入 Phase 3（AnkiClient + `sync_state`）实装，后续联调前需先补设计确认。

### 用户长期化指令（持续生效）
- 用户说“存档”时，必须优先更新根目录 `MEMORY.md`，并按固定小节完整记录。
- 复杂代码生成任务默认流程：先设计文档 -> 用户 review 通过 -> 再开始编码。
- 项目重构保持轻量：3 类 + 过程式 pipeline，避免过度设计。
- 默认使用中文沟通（除非用户明确要求英文）。

### 任务状态清单
- [x] 已完成：Phase 2（HtmlRenderer）核心实现、单测与 parser+renderer 集成测试、调试导出能力（parser JSON / renderer HTML）、文档同步。
- [-] 进行中：无。
- [ ] 下一步：Phase 3 设计与实现（`AnkiClient` + `sync_state`）并补 mock 集成测试；随后完成过程式 pipeline 串联验证。

## 会话归档 - 2026-03-01

### 时间
- 2026-03-01（本地时间）

### 本会话已完成事项
- 新建并持续更新重构设计文档 [refactor_design.md](refactor_design.md)，将架构收敛为 3 个核心类（`MarkdownProcessor`/`HtmlRenderer`/`AnkiClient`）+ 过程式 pipeline。
- 建立 Phase 1 工程骨架：`pyproject.toml`、`md2anki/` 包结构、最小可运行入口与占位实现。
- 实现并多轮迭代 `MarkdownProcessor`：
	- H4 父节点选择改为最近上层（H3 > H2 > H1）；
	- 父节点 block id 改为标题下独立行，命名 `^id-xxxx`；
	- H4 anki id 改为标题下独立行 `^anki-<id>`；
	- 标题与元信息行之间支持任意空行；
	- 识别到的 `^anki-...` 不进入 front/back 正文。
- 扩充并重构单测 [tests/unit/test_markdown_processor.py](tests/unit/test_markdown_processor.py)：覆盖多空行、父节点回退、分隔符、YAML 异常、回写去重等场景。
- 为测试导出增加默认开启 JSON 开关，支持在 JSON 中同时查看 `raw_md` 与 `raw_md_lines` 对照 parsed 结果。
- 清理了测试过程中产生的 `__pycache__` 临时文件夹，保持工作区整洁。

### 遇到的问题
- 文档大补丁应用时出现一次 patch 上下文漂移失败。
- 初次运行 pytest 时环境缺少 `pytest` 包。
- 解析规则演进较快（父节点规则、id 位置、命名、空行容忍），早期测试用例与实现存在短暂不一致风险。

### 解决方式
- 对补丁改为分段、精确上下文应用，避免一次性大块替换。
- 在虚拟环境中安装 `pytest` 后再执行针对性测试。
- 采用“先改实现、再补/改测试、最后跑回归”的闭环；每轮需求变更后均执行 `pytest tests/unit/test_markdown_processor.py` 验证。

### 注意事项 / 风险点
- 当前规范明确不兼容旧式“标题行尾 id”写法；后续若导入历史笔记需单独迁移脚本。
- `MarkdownProcessor` 规则已较严格，后续 `HtmlRenderer`/`pipeline` 需保持同一元信息语义，避免解析与同步层规则分叉。
- 测试 JSON 导出默认开启，会持续生成文件；如需减少噪声可通过环境变量关闭。

### 用户长期化指令（持续生效）
- 用户说“存档”时，必须优先更新根目录 `MEMORY.md`，并按固定小节完整记录。
- 复杂代码生成任务默认流程：先设计文档 -> 用户 review 通过 -> 再开始编码。
- 本项目重构保持轻量：3 类 + 过程式 pipeline，避免过度设计。

### 任务状态清单
- [x] 已完成：Phase 1 骨架、`MarkdownProcessor` 首版与规则迭代、单测扩充与 JSON 对照导出、设计文档同步更新。
- [-] 进行中：无。
- [ ] 下一步：Phase 2 实现 `HtmlRenderer`（wiki link/image、math 归一化、父节点跳转 footer）并补齐对应测试。

## Session Archive Template

### 时间
- YYYY-MM-DD HH:mm (本地时间)

### 本会话已完成事项
- 

### 遇到的问题
- 

### 解决方式
- 

### 注意事项 / 风险点
- 

### 用户长期化指令（持续生效）
- 

### 任务状态清单
- [x] 已完成：
- [-] 进行中：
- [ ] 下一步：
