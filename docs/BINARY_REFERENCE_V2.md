# Demo 0.5：独立节奏参考与 REAPER 粘贴

本页保留 0.5 行为记录；当前三算法入口见 [Demo 0.6](THREE_RHYTHM_ROUTES_V3.md)。

浏览器仍是分析 demo，多窗口桌面 helper 的方向保持不变。

## 使用

选中一句已分析台词即生成参考，无须进行节奏检索。默认 SOFA，可切换 narabas、HubertFA、MFA。每拍 ×1 / ×2 / ×4 / ×8 格，分别为 1 / 0.5 / 0.25 / 0.125 拍；默认选连续语音总时长最接近原句的倍率。4/4 小节线只用于参考，不强行填满小节。

表格分别展示文本 mora、实际占格、长音补时或读音对应不确定的依据。长音、连续元音与附着鼻音保持单一起点，促音进入起点间占格。可以改占格并保存；恢复自动占格、人工拆分、裁切和停顿灵敏度均在句子详情中。

“mora 基准”以可靠 mora 顺序为骨架，以连续语音的时值中位数推断额外长元音占格。单句没有足够时值参照时，不能可靠推断未写出的延长；界面允许修正。没有音素到 mora 对应时明确标为时值估计，不伪造逐 mora 时间戳。

“局部周期实验”按连续语音段，用 2 / 4 秒窗口的起点强度包络、Fourier、自相关和脉冲列相关提取周期与相位；有序动态规划直接选择内部整数格距。半速/倍速候选保留，长停顿可重建相位。它会改变分配，而不仅排序；证据不足和与基准相同的情况分别标明。它仍是实验结果，不是审美评分。

启用“锁定搜索命中点”才使用查询约束，自动同步查询 BPM。命中点不在所选倍率网格、固定点之间没有足够位置或音块内多出起点时，该倍率不可用；不偷偷细分。检索分数永远不由严格卡拍误差覆盖。

## narabas 边界与弹性间隙

CTC 发射支持、估计覆盖和媒体裁切独立保存。原始输出和旧分析版本保留；narabas 音素详情同时显示发射支持和覆盖估计。CTC blank 不等于静音。覆盖估计沿原始起点向下一音素/声学安静边界扩展，不宣称重新测量了真实音素终点。

音频裁切使用完整上下文人声的低能量边界，并受邻句文字归属限制。没有明确安静边界时保留更宽范围并提示不确定性，可以人工调整。上下文人声仍可独立播放。

可伸缩间隙由声音独立检测：默认 10 ms RMS 帧，120 ms 低能量核心，阈值为句内 P85 RMS 的 25%，两侧 20 ms 保护。灵敏度 0.5–2.0 调整阈值和最短核心长度。低能量并不证明没有弱辅音/呼吸，因此间隙原声会伸缩保留，不再整段置零。明确标为促音闭塞的区间不另算休止，避免与 mora 占格重复计数。该检测与裁切所用的更保守安静边界分别实现。

## REAPER

安装项目可选依赖：`.runtime/envs/core/bin/python -m pip install -e '.[reaper]'`。

选定方案后，在“REAPER 原生粘贴”设置持久原声目录，点击“复制到 REAPER”，在目标轨道 Cmd+V。无需插件或用户导入脚本。默认首个元音对齐编辑光标，前导辅音出现在光标前；也可选择文件左边界。光标应给前导声音留足空间。本轮按固定 BPM、4/4 验收，helper 与工程 BPM 应一致。

导出的 WAV 为当前选择版本的未变速原声。拉伸标记消费严格渲染的同一时间映射，包括起点、8 ms 起音保护区辅助标记、首尾和弹性间隙。保留保护区意味着标记数多于节奏点数。REAPER 与 Rubber Band 的音质可能不同，但源/目标位置对应相同。原声文件使用内容哈希命名，关闭 helper 或清理试听缓存不删除。

macOS 原生 `REAPERMedia` 为 UTF-8、NUL 分隔记录；不是普通剪贴板字符串。实测 7.79 的 POSITION、SNAPOFFS、LENGTH 同时记录秒与拍，SM 记录目标秒、源秒、辅助参数与拍位置。复制前完成原声和 manifest 写入，复制失败显式报错，不退化为普通 WAV 粘贴。

## 接口与再生成

- `POST /api/cues/{id}/quantization-plans`：`analysis_kind, bpm, strategy(mora|local_period), density(1|2|4|8|null), lock_query, query?`；返回方案、冲突、mora 和周期证据。
- `POST /api/cues/{id}/settings`：版本对应的占格覆盖与停顿灵敏度；改变后旧方案失效。人工拆分或恢复分组会归档并清除旧单元的占格覆盖，避免编号错位。
- `POST /api/cues/{id}/crop`：上下文范围内的人工首尾界限，不允许删去已标记音素。
- `POST /api/cues/{id}/reaper`：`plan_id, analysis_kind, variant, directory?, origin`；返回持久原声路径与复制状态，不声称已经导入 REAPER。
- `GET /api/search?analyzed_only=true`：只显示已分析素材，列表分别显示模型状态。

所有试听与导出都检查方案的分析/分组身份。旧原始分析保留；相同上游输出且音素顺序未变时可复用人工拆分，不跨不同上游结果猜测拆分索引。

重建：`scripts/rebuild_references.py`；只重试 MFA 失败样本：`scripts/retry_mfa_failures.py`；真实音频核心回归：`scripts/validate_references.py`。均使用 `.runtime/envs/core/bin/python`。重试扩大 MFA 搜索束，原始失败结果和每次重试记录分别保存。

参考：[CTC 发射与空白](https://docs.pytorch.org/audio/2.1/tutorials/ctc_forced_alignment_api_tutorial.html)、[REAPER 标记 API](https://www.reaper.fm/sdk/reascript/reascripthelp.html#SetTakeStretchMarker)。
