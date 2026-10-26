# 撤销与记录

* 你做的每个修改都记在你的**会话**（`OTTO_AGENT_SESSION`）名下，来源是 `agent`。
* `otto call edits.history '{"session": "<会话>"}'` 列出你的编辑，新的在前（`label`、`changes`、`undoneBy`）。
* `otto call edits.undoSession '{"session": "<会话>"}'` 从新到旧全部撤销。遇到之后又被改过的那条
  （所有者或别的会话改的）就停下，在 `blocked` 里报告；`remaining` 是还剩几条。
* `edits.undoOne {"editId"}` 撤销指定的一条（`edits.history` 标着 `undoable` 时：它改过的东西之后没被再改过）。
* `edits.undo` 撤销任何人最近一条可以安全撤销的编辑；撤自己的工作优先用 `edits.undoSession`。
* 所有者在应用的「操作历史」面板里能看到这些（谁改了什么），也能在那里撤回你的会话。
* **不在编辑记录里**（所以 `edits.undoSession` 撤不掉）：新建的采样、原素材与音轨
  （登记、分离结果、回导）、已完成的任务、导出的文件。
  建出来的采样只能用 `samples.delete` 删除，而它需要所有者确认——所以先计划再建，
  并记下你建的 ID（`samples.createPlanned` 会返回）报告给所有者。
* 危险命令（总览第 6 条）永远撤销不了。
