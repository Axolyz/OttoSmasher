#!/bin/sh
# 从官方源码编译 macOS arm64 的 libmpv（只开 LGPL，全部静态并进一个 libmpv.2.dylib）。
# 现成的包都不合适：media-kit 停在 mpv 0.36.0；eko5624 带 --enable-nonfree，不能再分发；MPVKit 自称只适合学习。
# 在云端机器上运行（.github/workflows/build-libmpv.yml），不在所有者的电脑上跑（要全局安装编译工具，AGENTS §4）。
# 用法：tools/build_libmpv_macos.sh <工作目录>；产物：<工作目录>/libmpv-macos-arm64-<mpv 提交>.tar.gz
set -eu

# mpv 的提交与 Windows 版（zhongfly/mpv-winbuild 的 LGPL 包）相同，两端是同一份 mpv
MPV_COMMIT=8ca245f2133773f9a7fe59e4c5bcc53f1af4407c
FFMPEG_TAG=n9.0.2
DAV1D_TAG=1.5.4
LIBPLACEBO_TAG=v7.387.0
LIBASS_TAG=0.17.5

WORK=$1
PREFIX="$WORK/prefix"
SRC="$WORK/src"
mkdir -p "$PREFIX" "$SRC"
export MACOSX_DEPLOYMENT_TARGET=14.0
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"

fetch_tag() { # 仓库地址 标签 目录
  [ -d "$SRC/$3" ] || git clone --quiet --depth 1 --branch "$2" --recurse-submodules --shallow-submodules "$1" "$SRC/$3"
}

echo "== dav1d $DAV1D_TAG"
fetch_tag https://code.videolan.org/videolan/dav1d.git "$DAV1D_TAG" dav1d
meson setup "$SRC/dav1d/build" "$SRC/dav1d" --prefix="$PREFIX" --libdir=lib --buildtype=release \
  -Ddefault_library=static -Denable_tools=false -Denable_tests=false
ninja -C "$SRC/dav1d/build" install

echo "== FFmpeg ${FFMPEG_TAG}, LGPL"
fetch_tag https://github.com/FFmpeg/FFmpeg.git "$FFMPEG_TAG" ffmpeg
(
  cd "$SRC/ffmpeg"
  ./configure --prefix="$PREFIX" --pkg-config-flags=--static \
    --enable-static --disable-shared --disable-programs --disable-doc --disable-debug \
    --disable-autodetect --enable-pthreads --enable-zlib --enable-iconv \
    --enable-videotoolbox --enable-audiotoolbox --enable-libdav1d \
    --disable-encoders --disable-muxers --disable-devices --disable-avdevice --disable-network \
    --extra-cflags="-mmacosx-version-min=$MACOSX_DEPLOYMENT_TARGET" \
    --extra-ldflags="-mmacosx-version-min=$MACOSX_DEPLOYMENT_TARGET"
  grep -q 'LGPL version 2.1 or later' ffbuild/config.mak || grep -q 'LGPL version 2.1 or later' config.h \
    || { echo "FFmpeg 的许可不是 LGPL，停止" >&2; exit 1; }
  make -j"$(sysctl -n hw.ncpu)" install
)

echo "== mpv $MPV_COMMIT"
if [ ! -d "$SRC/mpv" ]; then
  git init --quiet "$SRC/mpv"
  git -C "$SRC/mpv" fetch --quiet --depth 1 https://github.com/mpv-player/mpv.git "$MPV_COMMIT"
  git -C "$SRC/mpv" checkout --quiet FETCH_HEAD
fi
SUB="$SRC/mpv/subprojects"
mkdir -p "$SUB"
[ -d "$SUB/libplacebo" ] || git clone --quiet --depth 1 --branch "$LIBPLACEBO_TAG" --recurse-submodules --shallow-submodules \
  https://github.com/haasn/libplacebo.git "$SUB/libplacebo"
[ -d "$SUB/libass" ] || git clone --quiet --depth 1 --branch "$LIBASS_TAG" https://github.com/libass/libass.git "$SUB/libass"
(cd "$SRC/mpv" && for w in freetype2 fribidi harfbuzz; do [ -f "subprojects/$w.wrap" ] || meson wrap install "$w"; done)

# auto_features=disabled：只留播放需要的；不要 Lua、JS、GPU 输出、窗口等（画面走 render API 的软件渲染，ARCHITECTURE §10.1）
meson setup "$SRC/mpv/build" "$SRC/mpv" --prefix="$PREFIX" --libdir=lib --buildtype=release \
  --force-fallback-for=libplacebo,libass,freetype2,fribidi,harfbuzz \
  -Ddefault_library=shared -Dauto_features=disabled \
  -Dlibplacebo:default_library=static -Dlibass:default_library=static -Dfreetype2:default_library=static \
  -Dfribidi:default_library=static -Dharfbuzz:default_library=static \
  -Dharfbuzz:freetype=enabled -Dlibass:coretext=enabled -Dlibplacebo:demos=false \
  -Dgpl=false -Dlibmpv=true -Dcplayer=false -Dtests=false -Dfuzzers=false -Dbuild-date=false \
  -Dcoreaudio=enabled -Dzlib=enabled -Diconv=enabled
ninja -C "$SRC/mpv/build" libmpv.2.dylib

echo "== 打包"
OUT="$WORK/libmpv"
rm -rf "$OUT"
mkdir -p "$OUT/licenses"
cp "$SRC/mpv/build/libmpv.2.dylib" "$OUT/"
strip -x "$OUT/libmpv.2.dylib"
install_name_tool -id @rpath/libmpv.2.dylib "$OUT/libmpv.2.dylib"
codesign --force --sign - --timestamp=none "$OUT/libmpv.2.dylib"
cp "$SRC/mpv/LICENSE.LGPL" "$SRC/mpv/Copyright" "$OUT/licenses/"
cp "$SRC/ffmpeg/COPYING.LGPLv2.1" "$OUT/licenses/FFmpeg-COPYING.LGPLv2.1"
cp "$SRC/dav1d/COPYING" "$OUT/licenses/dav1d-COPYING"
cat > "$OUT/versions.txt" <<EOF
mpv $MPV_COMMIT
FFmpeg $FFMPEG_TAG
dav1d $DAV1D_TAG
libplacebo $LIBPLACEBO_TAG
libass $LIBASS_TAG
EOF

# 只允许依赖系统库，否则换一台电脑就加载不了
BAD=$(otool -L "$OUT/libmpv.2.dylib" | tail -n +2 | awk '{print $1}' | grep -vE '^(/System/|/usr/lib/|@rpath/libmpv\.2\.dylib$)' || true)
if [ -n "$BAD" ]; then
  echo "依赖了系统以外的库：$BAD" >&2
  exit 1
fi
otool -L "$OUT/libmpv.2.dylib"
vtool -show-build "$OUT/libmpv.2.dylib"

NAME="libmpv-macos-arm64-$(printf %.10s "$MPV_COMMIT").tar.gz"
tar -czf "$WORK/$NAME" -C "$WORK" libmpv
shasum -a 256 "$WORK/$NAME"
ls -la "$WORK/$NAME" "$OUT/libmpv.2.dylib"
