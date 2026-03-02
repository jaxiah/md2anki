# md2anki 0.1 Gold Reference 设计文档

> 文档定位：本文件是当前可发布状态（v0.1）的**基线设计说明**，用于对外说明“现在系统是什么样、如何工作、边界在哪”。
>
> 不记录历史演进过程，不追溯中间方案。

---

## 1. 目标与范围

### 1.1 发布目标

md2anki v0.1 的目标是：将 Obsidian 风格 Markdown 中的 H4 卡片块稳定同步到 Anki（Basic 模板），并在 markdown 中维护最小必要元信息，实现可重复执行（幂等）、可删除、可跳过、可回写。

### 1.2 核心能力（In Scope）

- 解析 markdown 文档中的：
  - frontmatter `ankideck`
  - H1/H2/H3 父层级
  - H4 作为卡片单元
  - 元信息行：`^anki-<id>`, `^anki-<id> DELETE`, `^noanki`, `^id-xxxx`
- 渲染 front/back markdown 为 HTML（含 wiki link / wiki image / math delimiter 规范化）。
- 与 AnkiConnect 同步：ADD / UPDATE / DELETE / SKIP。
- 维护 `sync_state.json`（按 anki note id 跟踪 hash 与来源）。
- apply 模式下回写 markdown（写入 `^anki-id`、补父节点 `^id-*`、删除后写 `^noanki`）。
- dry-run 模式下仅给出计划，不触发网络写入、不改 state、不改 markdown。

### 1.3 文件级处理门槛（重要契约）

- 仅当文件 frontmatter 中存在 `ankideck` 时，该文件才进入 md2anki 处理链路。
- 若缺少 `ankideck`：该文件会被完整跳过（不解析卡片、不渲染、不同步、不回写），并记录 warning：`missing ankideck`。
- 这同时提供了明确的用户选择：不希望被 md2anki 管理的笔记，可以不配置 `ankideck`（文件级 opt-out）。

### 1.4 非目标（Out of Scope）

- 不管理 Anki 模板（字段结构固定为 Basic: Front/Back）。
- 不做复杂冲突合并（同一目标在多源文档竞争时仅按当前输入序列处理）。
- 不保证旧版“行尾内联元信息”兼容（当前要求元信息独立行）。
- 不提供 GUI，仅提供 Python API 与 CLI。

---

## 2. 总体架构

系统采用 “3 类 + 过程式 pipeline” 结构：

1. `MarkdownProcessor`：解析与局部回写（metadata 层）。
2. `HtmlRenderer`：markdown → HTML + 媒体收集（render 层）。
3. `AnkiClient`：AnkiConnect 调用 + state 管理（sync 层）。
4. `run_pipeline`：串联 parse → route → render → sync → writeback（orchestration 层）。

### 2.1 模块关系

- 输入：`*.md` 文件列表、vault 参数、运行模式参数。
- 中间结构：
  - `ParsedDocument` / `ParsedNote`
  - `RenderedNote` / `MediaItem`
  - `SyncResult`
  - `PipelineReport`
- 输出：
  - Anki 侧变更（apply）
  - `sync_state.json`（apply）
  - markdown 回写（apply 且允许 writeback）
  - 运行摘要与错误聚合

---

## 3. 数据模型（当前实现）

### 3.1 ParsedNote

关键字段：

- 源信息：`source_file`, `line_idx_h4`
- deck：`ankideck_base`, `deck_full`
- 父节点：`parent_title`, `parent_block_id`, `parent_line_idx`, `parent_level`
- 卡片头：`h4_heading_raw`, `h4_heading_pure`
- 元信息：`anki_note_id`, `anki_meta_line_idx`, `delete_requested`, `no_anki`
- 内容：`front_md`, `back_md`, `split_by_separator`

### 3.2 渲染结果

`RenderedNote`：`front_html`, `back_html`, `back_html_with_footer`, `media_files`, `warnings`。

`MediaItem`：`filename`, `abs_path`, `base64_data`, `source_ref`。

### 3.3 状态文件结构

`sync_state.json`：

```json
{
  "schema_version": 1,
  "items": {
    "1234567890": {
      "content_hash": "...",
      "updated_ts": "2026-...",
      "source_file": "xx.md",
      "h4_heading_pure": "..."
    }
  }
}
```

主键是 `anki_note_id`（字符串）。

---

## 4. Markdown 解析规范（Gold Rules）

### 4.1 基础规则

- frontmatter 必须存在 `ankideck`，否则整文件跳过并写 warning。
- “整文件跳过”语义是强约束：该文件不会进入后续 render/sync/writeback 任一阶段。
- H4 代表一张候选卡片。
- 父节点选择优先级：最近 `H3 > H2 > H1`。
- `deck_full = ankideck_base::parent_title`（有父节点时）；否则用 `ankideck_base`。

### 4.2 元信息识别

元信息必须为独立行（可前后空格，可与标题间隔空行）：

- `^anki-<数字>`：绑定已存在 Anki note。
- `^anki-<数字> DELETE`：请求删除该 note。
- `^noanki`：跳过该 H4，不参与 add/update/delete。
- `^id-xxxx`：父节点 block id。

### 4.3 noanki 与 delete 的路由关系

- `^noanki` 且非 delete：直接 skip。
- `^anki-id DELETE`：走删除分支。
- 同时存在 `DELETE + ^noanki`：优先 delete（删除成功后最终保持单个 `^noanki`）。

### 4.4 front/back 切分

- 在 H4 body 内，首个 `---`（允许前后空白）作为分隔线：
  - 上半段并入 Front（`H4 标题 + front_extra`）
  - 下半段为 Back
- 若无分隔线：
  - Front = `H4 标题`
  - Back = 全部 body

---

## 5. HTML 渲染与媒体策略

### 5.1 Markdown 渲染

- 使用 `markdown-it-py`（`gfm-like`，`html=True`, `breaks=True`, `linkify=False`）。
- front/back 分开渲染，Back 末尾追加父链接 footer。

### 5.2 Wiki Link

`[[target|alias]]` →

`<a href="obsidian://open?vault=<vault>&file=<target>">alias</a>`

### 5.3 父链接 URL（关键）

父链接统一写入 Back footer，格式为 `obsidian://open`。

- 若有 `parent_block_id`：目标构造为 `file_without_md#^id`，再整体作为 `file` 参数编码。
- 该实现避免 fragment 在外部 webview 丢失，确保 block 跳转可用。

### 5.4 Wiki Image 与媒体上传

`![[...]]` 规则：

- 先尝试 `asset_root/<img_ref>` 直接命中。
- 未命中则在 `asset_root` 下递归按文件名匹配。
- 多命中时按相对路径排序稳定选择第一项，并记录 warning。
- 支持宽度 token：`|300` 或 `|300px` → `width="300"`。
- 图片内容会被 base64 编码并交由 Anki `storeMediaFile` 上传。

### 5.5 数学分隔符规范化

仅在非 fenced code 区域做转换：

- `$$...$$` → `\[...\]`
- `$...$` → `\(...\)`

fenced code 中保持原样，不做替换。

---

## 6. 同步语义（AnkiClient）

### 6.1 运行模式

- **dry-run**（默认）：
  - 不发 AnkiConnect 请求
  - 不写 `sync_state.json`
  - 不改 markdown
  - 产出 `dry_run_actions`
- **apply**（`--apply-anki-changes`）：
  - 执行真实同步
  - 按需写 state 与 markdown

### 6.2 ADD / UPDATE / SKIP / DELETE 判定

- DELETE：`delete_requested=True` 且有 `anki_note_id`。
- SKIP(noanki)：`no_anki=True` 且非 delete。
- SKIP(unchanged)：有 id 且 state 中 hash 相同。
- UPDATE：有 id 且需要更新。
- ADD：无 id 且需要新增。

### 6.3 哈希策略

`content_hash` 基于 markdown 语义而非最终 HTML：

- `deck_full`
- `front_md`
- `back_md`
- `media_refs`（`filename:source_ref` 排序后）

目的：降低 footer 等渲染细节扰动导致的误 update。

### 6.4 AnkiConnect 操作序列

- 预热 deck cache（apply）。
- 必要时 `createDeck`。
- 逐媒体 `storeMediaFile`（任一失败则该 note 失败并中止其后续写字段）。
- ADD：`addNote`（Basic, Front/Back, tags=`md2anki`）。
- UPDATE：`updateNoteFields`。
- DELETE：`deleteNotes`。

---

## 7. Markdown 回写策略

### 7.1 回写触发条件

必须同时满足：

- `apply_anki_changes=True`
- `write_back_markdown=True`

### 7.2 回写内容

- ADD 成功后：在 H4 元信息区写入 `^anki-<id>`。
- DELETE 成功后：移除 `^anki-*`，补 `^noanki`（若不存在）。
- 父节点缺 `^id-*` 时：在父标题下插入。

### 7.3 稳定性机制

- 父节点 id 会在渲染前预写回并重解析，避免首轮 line_idx 漂移。
- 最终写回阶段将 bind/delete/parent 操作合并后按锚点行号倒序执行，减少跨操作漂移风险。
- 元信息扫描允许空行，且仅检查首个非空候选，避免误吞正文。

---

## 8. Pipeline 行为

`run_pipeline(...)` 固定流程：

1. 解析所有输入 markdown。
2. apply 模式下先补父节点 block id（必要时写盘并重解析）。
3. 路由 note：
   - `noanki`（非 delete）直接 skip
   - delete 走轻量 payload（无需渲染）
   - 其余走 renderer
4. 调用 `AnkiClient.sync(...)`
5. apply + writeback 时执行 markdown 回写
6. 返回 `PipelineReport`

`PipelineReport` 聚合：`added/updated/deleted/skipped/failed/errors/markdown_writebacks/dry_run_actions`。

---

## 9. CLI 与运行方式

### 9.1 入口

- 脚本：`md2anki = md2anki.cli:main`
- 模块：`python -m md2anki`

### 9.2 核心参数

- `--vault-root`（必填）
- `vault_name` 由 `--vault-root` 目录名自动推导
- `--asset-root`
- `--anki-connect-url`
- `--sync-state-file`
- `--file`（可重复，不传则递归扫描全部 `.md`）
- `--apply-anki-changes`（默认 dry-run）
- `--no-write-back-markdown`

### 9.3 退出码

- `failed > 0` 返回 `1`
- 否则返回 `0`

---

## 10. 测试基线（当前覆盖）

### 10.1 单元测试

- `MarkdownProcessor`：解析规则、层级父节点、metadata 空行容忍、delete/noanki、回写辅助。
- `HtmlRenderer`：footer URL、wiki link/image、冲突图片选择、math normalize、code fence 保护。
- `AnkiClient`：dry-run 无副作用、add/update/skip/delete、state 变更。
- `CLI`：默认 dry-run、参数透传与文件收集。

### 10.2 集成测试

- Parser + Renderer 联合行为（列表/表格/链接/图片/数学）。
- Pipeline 在临时 vault 下的 add/update/delete/noanki/冲突/多空行/多父节点写回位置。

### 10.3 手动真 E2E

- 文件：`tests/e2e/test_manual_e2e_flow.py`
- 门禁：`MD2ANKI_E2E=1`
- 覆盖时序（8 条）：初次 add、rerun skip、update、delete、noanki 保持、delete+noanki 冲突、媒体数学 roundtrip、空行鲁棒性。

---

## 11. 失败与告警语义

- 单条 note 失败不阻断全局，汇总到 `errors` 与 `failed`。
- 常见 warning：
  - 缺少 `ankideck`
  - YAML 解析失败
  - 图片缺失
  - 图片同名冲突（已给出稳定选择）
- 常见失败：
  - delete 请求缺少 `anki_note_id`
  - AnkiConnect 网络/接口错误
  - 媒体上传失败

---

## 12. 已知边界与发布注意事项

### 12.1 已知边界

- 仅支持 Basic 模板的 Front/Back 字段写入。
- 依赖 AnkiConnect version=6 API。
- 元信息要求独立行；不保证历史“行尾元信息”兼容。
- 图片解析范围限定在 `asset_root` 子树内。

### 12.2 对外发布建议

- 默认向用户强调先 dry-run，再 apply。
- 提供最小使用手册（AnkiConnect 安装、参数示例、状态文件说明）。
- 建议将手动 E2E 作为发布前 checklist（至少跑 add/rerun/delete 三段）。

---

## 13. 版本基线声明

- 基线版本：`0.1.0`
- 基线口径：以当前仓库实现与测试状态为准。
- 本文用途：作为后续迭代（0.1.x / 0.2）的对照参考（gold reference）。
