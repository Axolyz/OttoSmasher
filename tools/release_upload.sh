#!/bin/sh
# 把构建好的文件传到这个标签的 Release 草稿；没有就新建，已经发布的不动（.github/workflows 的 release 任务）。
# 用法：tools/release_upload.sh <标签> <目录>；目录里有 RELEASE_NOTES.md 时同时更新发布说明（第一行标题去掉）。
set -eu
tag="$1"
dir="$2"
if ! gh release view "$tag" >/dev/null 2>&1; then
  gh release create "$tag" --draft --verify-tag --title "OttoSmasher ${tag#v}" --notes "发布说明待补"
fi
if [ "$(gh release view "$tag" --json isDraft --jq .isDraft)" != "true" ]; then
  echo "::error::Release $tag 已经发布，不覆盖"
  exit 1
fi
gh release upload "$tag" "$dir"/*.zip "$dir"/*.sha256 --clobber
if [ -f "$dir/RELEASE_NOTES.md" ]; then
  tail -n +3 "$dir/RELEASE_NOTES.md" > "$dir/notes.txt"
  gh release edit "$tag" --notes-file "$dir/notes.txt"
fi
