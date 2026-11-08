<!-- 发布说明模板：tools/package_mac.py 构建时填入 {version}、{zip}、{windows_zip}、{sha256}、{changes}（相对上一个版本的提交），写到 out/release/RELEASE_NOTES.md；发布前可以手改那份；Windows 包云端构建完后手动填 {windows_sha256}。 -->
# OttoSmasher {version}

本地运行的音 MAD 素材工作站：截取、人声分离、拉平、卡拍和检索，再交给 DAW 或视频软件；也可以让 agent 通过命令行 `otto` 操作。

## 下载

| 系统 | 文件 | SHA-256 |
|---|---|---|
| macOS 15 或更新（Apple 芯片） | `{zip}` | `{sha256}` |
| Windows 10 / 11 x64 | `{windows_zip}` | `{windows_sha256}` |

## 这一版的改动

{changes}

## 安装

**macOS**

1. 解压，把 `OttoSmasher.app` 拖进“应用程序”。
2. 第一次打开前在终端运行 `xattr -dr com.apple.quarantine /Applications/OttoSmasher.app`，再双击打开。应用没有经过 Apple 公证，不运行这条命令会被 macOS 拦下；每次替换新版本后都要再运行一次。

**Windows**

1. 解压到任意文件夹，运行 `OttoSmasher.exe`。
2. 安装包没有签名，SmartScreen 拦下时点“更多信息 → 仍要运行”。

四个模型（对齐、读音预测、音高、拉平）已随包，不用下载。人声分离需要另外安装 [PyMSS Studio](https://github.com/pymss-project/pymss-studio/releases)，并在 Studio 里手动下载模型，推荐 HyperACE v2（`bs_roformer_voc_hyperacev2`）。

详细说明见 [README](https://github.com/Axolyz/OttoSmasher#readme) 与[用户说明](https://github.com/Axolyz/OttoSmasher/blob/main/docs/user/README.md)。

## 许可

OttoSmasher 是 GPL-3.0-or-later。随包的拉平声码器 PC-NSF-HiFiGAN 是单独的组件，许可为 CC BY-NC-SA 4.0（**非商业**），不属于 GPL 部分；商业再分发前请删掉包内 `models/flatten/`（macOS 在 `OttoSmasher.app/Contents/Resources/` 下，Windows 在 `resources/` 下）。各组件的许可见包内的 `licenses/`。

## 已知限制

- Windows 基础功能已有所有者实机验证，按正式版发布。本轮新增改动通过云端验证，尚未重新实机测试；命令行自动安装、`otto open` 和 REAPER 新交接方式的实机复测见路线图。
- Windows 上按着 Alt 拖出采样，放到资源管理器不行，松开 Alt 再放可以。
- 语音分析目前只支持日语。
- 用户说明目前只有中文。
