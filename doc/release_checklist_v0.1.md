# md2anki 发布清单（v0.1）

> 用途：每次对外发布前的最小可执行自检清单。
>
> 建议策略：严格按顺序执行，未通过项不要进入下一阶段。

---

## A. 发布前（Pre-Release）

### A1. 代码与文档一致性

- [ ] `README.md` 与当前行为一致（参数、默认 dry-run、元信息规则）。
- [ ] `doc/design_gold_reference_v0.1.md` 与当前实现一致。
- [ ] 本次改动未破坏 v0.1 约束（Basic 模板、独立元信息行、asset_root 范围）。

### A2. 本地环境准备

- [ ] Python 版本满足 `>=3.10`。
- [ ] 虚拟环境可用并已安装依赖：`pip install -e .[test]`。
- [ ] Anki 桌面已安装并可启动。
- [ ] AnkiConnect 已启用（默认 `http://127.0.0.1:8765`）。

### A3. 自动化测试

在仓库根目录执行：

```powershell
pytest -q
```

通过标准：

- [ ] 单元测试全绿
- [ ] 集成测试全绿
- [ ] 无新增与本次发版无关的阻断失败

### A4. 手动 E2E（建议发版必跑）

```powershell
$env:MD2ANKI_E2E="1"
python -m pytest tests/e2e/test_manual_e2e_flow.py -m e2e_manual -q
```

通过标准：

- [ ] 8 条手动 E2E 用例通过
- [ ] 关键链路确认：add → rerun skip → update → delete
- [ ] delete 后 Markdown 中目标卡片为 `^noanki`，且 state 清理正确

---

## B. 发版执行（Release）

### B1. 版本与变更确认

- [ ] `pyproject.toml` 版本号正确（当前基线 `0.1.0`，若补丁发布请更新）。
- [ ] 变更说明已整理（建议在 release notes 中说明“先 dry-run 再 apply”）。
- [ ] 对外说明中包含已知边界（Basic 模板、独立元信息行）。

### B2. 最小验收命令（真实 vault）

#### 1) dry-run

```powershell
md2anki --vault-root <VAULT_ROOT>
```

- [ ] 命令成功执行
- [ ] 输出统计合理（added/updated/deleted/skipped/failed）

#### 2) apply（小范围）

```powershell
md2anki --vault-root <VAULT_ROOT> --file <RELATIVE_FILE> --apply-anki-changes
```

- [ ] 仅指定文件被处理
- [ ] Anki 中卡片写入/更新符合预期
- [ ] markdown 回写位置正确（`^anki-id` 或 `^noanki`）

### B3. 全量 apply（可选）

```powershell
md2anki --vault-root <VAULT_ROOT> --apply-anki-changes
```

- [ ] 全量运行成功
- [ ] `sync_state.json` 更新正常
- [ ] rerun 后主要为 skip（幂等性通过）

---

## C. 发布后（Post-Release）

### C1. 结果留档

- [ ] 记录本次发布日期、版本、提交号。
- [ ] 保存关键命令输出（至少 dry-run 与 apply 摘要行）。
- [ ] 记录已知问题与回滚方案。

### C2. 快速回归

- [ ] 随机抽检 1~2 个 deck：Front/Back 渲染、父链接跳转、图片显示、公式显示。
- [ ] 验证删除链路未回归（DELETE 后不自动 re-add）。

---

## D. 故障处理速查

### D1. apply 无效果

排查顺序：

1. 是否遗漏 `--apply-anki-changes`
2. Anki 是否启动
3. AnkiConnect 地址是否可达
4. 目标 H4 是否被 `^noanki` 跳过
5. 是否 hash 未变化导致 skip

### D2. 图片异常

- 确认图片位于 `asset_root` 子树。
- 同名图片冲突时按 warning 指示的稳定选择路径检查。

### D3. 需要全量重建同步关系

- 先备份 vault 与 Anki。
- 备份后删除 `sync_state.json`。
- 重新 dry-run → apply。

---

## E. 发布门槛（Go / No-Go）

满足以下全部条件才建议对外发布：

- [ ] 自动化测试通过
- [ ] 手动 E2E 通过
- [ ] 最小真实 vault 验证通过（dry-run + apply）
- [ ] 文档已更新（README + 设计文档 + 本清单）
- [ ] 已知风险可接受且有回滚路径

如任一项未满足，结论：**No-Go**。
