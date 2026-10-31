<!-- 发布说明模板：tools/package_mac.py 构建时填入 {version}、{zip}、{sha256}、{changes}（相对上一个版本的提交），写到 out/release/RELEASE_NOTES.md；发布前可以手改那份。 -->
# OttoSmasher {version}（macOS）

本地运行的音 MAD 素材工作站——审阅、截取、分离、拉平、卡拍、检索，再交给 REAPER 和视频软件；也能让 LLM agent 通过命令行 `otto` 操作。

## 下载

- `{zip}`（Apple 芯片，macOS 14 或更新）
- SHA-256：`{sha256}`

## 这一版的改动

{changes}

## 安装

1. 解压，把 `OttoSmasher.app` 拖进“应用程序”。
2. 第一次打开前在终端运行一次 `xattr -dr com.apple.quarantine /Applications/OttoSmasher.app`，再双击打开
   （应用只做了本机签名、没有经过 Apple 公证，不运行这一句 macOS 会拦下它；每次替换新版本后都要再运行一次）。
3. 四个模型（对齐、读音预测、音高、拉平）已随包，不用下载。人声分离需要另外安装 [PyMSS Studio](https://github.com/pymss-project/pymss-studio/releases)。

详细说明见 [README](https://github.com/Axolyz/OttoSmasher#readme) 与 [用户使用说明](https://github.com/Axolyz/OttoSmasher/blob/main/docs/USER_GUIDE.md)。

## 许可

OttoSmasher 是 GPL-3.0-or-later。随包的拉平声码器 PC-NSF-HiFiGAN 是单独的组件，许可为 CC BY-NC-SA 4.0（**非商业**），不属于 GPL 部分；
商业再分发前请删掉 `OttoSmasher.app/Contents/Resources/models/flatten/`。各组件的许可见包内 `Contents/Resources/licenses/`。

## 已知限制

- 只有 macOS（Apple 芯片）；Windows 暂不发布。
- 语音分析目前只支持日语；界面只有简体中文。
