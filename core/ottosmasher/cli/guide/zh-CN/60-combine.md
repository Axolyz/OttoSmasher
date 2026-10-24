# 把应用和你自己的工具组合起来

应用是素材库和分析引擎；判断和其他工具由你提供。常见做法：

## 判断内容，再写回成标签

读文本（`textLayer.list`；采样读到的段用 `speech.sample`），用你自己的推理判断，然后打标签
（`samples.batchEdit` → `edits.apply`），或者从挑出来的段建采样（主题 `samples`）。
标签是交接点：之后的检索和导出都按它筛选。

## 采样的画面 → 图像工具 → 再带回来

1. 拿到采样：`otto call samples.ids '{"tags": {"expr": "topic:game"}}'`。
2. 对每个采样，要么导出片段（`exports.video {"id", "version": "original"} --wait`），要么读它的画面来自哪里：
   `visuals.forSample {"id"}` → `binding.path`（媒体文件）、`binding.mode`、`binding.offset`，以及采样的 `start`/`end`
   和 `mapping`（资产时间 → 原素材时间）。用你自己的 ffmpeg 从片段或原文件里抽帧。
3. 用你的工具处理（例如本机的抠图模型）。结果写在工作区**之外**。
4. 需要的话把结果绑回采样作为画面：`visuals.bind {"ownerType": "sample", "ownerId", "path"}`
   （图片 = 静态画面，gif = 循环，视频 = 同步）。`path: null` 摘下绑定。可撤销。

## 在别处处理过的音频 → 回到素材库

`reimport.preview {"assetId", "start", "path"}` → `reimport.commit` 把处理过的文件放回某条轨的某个位置
（复制进素材库，并新建一个全长采样）。分离和拉平是内置的（`separation.submit`、`flatten.*`）。

## 从别处来的字幕

语音识别、删翻译、猜说话人：都在文件上做，保持同名，然后
`subtitles.previewMany` → `subtitles.importMany`。重新导入会显示新增 / 不变 / 替换；手改过的段受保护。

## 让所有者知情

大的或模棱两可的决定（哪些台词算“和游戏相关”、用哪个模型分离）在写入前给所有者一个简短的总结。
你的修改在应用里显示为“资料已更新”，可以按会话撤回。
