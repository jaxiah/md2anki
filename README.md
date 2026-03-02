# md2anki

English version: [README_en.md](README_en.md)

将 Obsidian 风格 Markdown（以 `####` 为卡片）同步到 Anki 的轻量工具。

当前发布基线：`v0.1.0`

---

## 这个工具能做什么

- 从 Markdown 提取卡片并同步到 Anki（Basic 模板，`Front/Back` 字段）。
- 支持 `ADD / UPDATE / DELETE / SKIP`。
- 支持图片上传（`![[...]]`）与 wiki 链接（`[[...]]`）。
- 默认 `dry-run`（安全预览），显式开启 `apply` 才会真正写入 Anki。
- 在 apply 模式可回写 Markdown 元信息（如 `^anki-123`、`^noanki`、父节点 `^id-xxxx`）。

---

## 安装

### 1) 环境要求

- Python `>=3.10`
- 已安装 Anki 桌面端
- 已安装并启用 AnkiConnect（默认地址 `http://127.0.0.1:8765`）

### 2) 安装项目

在仓库根目录执行：

```bash
pip install -e .
```

如果需要测试依赖：

```bash
pip install -e .[test]
```

---

## 3 分钟跑通（推荐）

### 第一步：先 dry-run（默认）

```bash
md2anki --vault-root <你的Vault路径>
```

示例（PowerShell）：

```powershell
md2anki --vault-root D:/Notes/MyVault
```

你会看到类似摘要：

- `added / updated / deleted / skipped / failed`
- `dry-run actions` 数量

> dry-run 不会写 Anki、不写 state、不改 Markdown。

### 第二步：确认无误后 apply

```bash
md2anki --vault-root <你的Vault路径> --apply-anki-changes
```

> apply 会真实写入 Anki，并更新 `sync_state.json`。

---

## 常用参数

- `--vault-root`：Vault 根目录（必填）
- `vault_name` 会由 `vault-root` 的目录名自动推导（用于 `obsidian://open` 链接）
- `--asset-root`：资源目录（默认 `assets`）
- `--anki-connect-url`：AnkiConnect 地址（默认 `http://127.0.0.1:8765`）
- `--sync-state-file`：状态文件路径（默认 `<vault-root>/sync_state.json`）
- `--file`：仅处理指定 Markdown（可重复）
- `--apply-anki-changes`：开启真实写入（默认关闭）
- `--no-write-back-markdown`：apply 时禁用 Markdown 回写

只处理单文件示例：

```powershell
md2anki --vault-root D:/Notes/MyVault --file "DeckA/topic.md"
```

---

## Markdown 约定（v0.1）

### 1) 必须有 frontmatter `ankideck`

```yaml
---
ankideck: md2ankiTest
---
```

如果一个 Markdown 文件不包含 `ankideck`，md2anki 会完整跳过该文件（不渲染、不同步、不回写）。
这可以作为“文件级不纳管（opt-out）”的显式开关。

### 2) `####` 是卡片

- H4 标题作为默认 Front。
- H4 body 作为 Back。
- 若 body 内出现首个 `---` 分隔线：
  - 分隔线前并入 Front
  - 分隔线后作为 Back

### 3) 元信息必须是独立行

- `^anki-1234567890`：绑定已有 note
- `^anki-1234567890 DELETE`：删除该 note
- `^noanki`：跳过该 H4
- `^id-xxxx`：父标题 block id

> 元信息与标题之间允许空行。

### 4) 父节点规则

`deck_full` 使用最近父标题：`H3 > H2 > H1`

---

## 图片、链接、公式

### 图片

- 支持 `![[name.png]]`、`![[path/to/name.png]]`、`![[name.png|300]]`
- 先按显式路径找 `asset_root/<ref>`，否则在 `asset_root` 下递归按文件名查找
- 同名多图时会稳定选择一项并给 warning

### Wiki 链接

- `[[target|alias]]` 转换为 `obsidian://open?vault=...&file=...`

### 公式

- 非代码块区域：
  - `$...$` 规范化为 `\(...\)`
  - `$$...$$` 规范化为 `\[...\]`
- fenced code block 内不转换

---

## `sync_state.json` 是什么

状态文件用于判断“是否需要更新”，避免重复写入。

- 默认位置：`<vault-root>/sync_state.json`
- 主键：`anki_note_id`
- 记录：内容 hash、更新时间、来源文件等

如果你要“全量重建同步关系”，可以备份后删除这个文件再重新 apply。

---

## 安全使用建议

- 永远先 dry-run，再 apply。
- 首次 apply 建议先用 `--file` 限定 1~2 个文件验证。
- 发布或大改前先备份 Vault 与 Anki。

---

## 常见问题

### Q1: 为什么没有写入 Anki？

检查：

- 是否传了 `--apply-anki-changes`
- Anki 是否已启动
- AnkiConnect 是否可访问（默认 `127.0.0.1:8765`）

### Q2: 为什么某个 H4 被跳过了？

常见原因：

- 存在 `^noanki`
- frontmatter 缺少 `ankideck`
- 内容 hash 未变化（被判定为 `skip`）

### Q3: 删除后为什么写了 `^noanki`？

这是设计行为：防止该 H4 在后续运行中被再次自动 add。

---

## 开发与测试

运行自动化测试：

```bash
pytest -q
```

手动真 E2E（需显式开启）：

```powershell
$env:MD2ANKI_E2E="1"
python -m pytest tests/e2e/test_manual_e2e_flow.py -m e2e_manual -q
```

---

## 参考文档

- Gold Reference 设计文档：`doc/design_gold_reference_v0.1.md`
- 发布清单：`doc/release_checklist_v0.1.md`
