#!/bin/zsh -l
# 一键启动 OttoSmasher（开发版）：在访达里双击这个文件即可。
# 会先编译界面（约几秒），再打开应用；工作区是仓库里的 dev-workspace/（模型在 dev-workspace/Models）。
# 关掉应用后这个终端窗口可以直接关。-l：用登录 shell，才能找到 Homebrew 的 node、ffmpeg、rubberband。
cd "$(dirname "$0")" || exit 1
export OTTO_DEV=1
echo "正在编译并启动 OttoSmasher……（关闭应用后可以关掉这个窗口）"
if ! tools/npm start; then
  echo ""
  echo "启动失败，上面是出错信息。按回车键关闭窗口。"
  read -r _
fi
