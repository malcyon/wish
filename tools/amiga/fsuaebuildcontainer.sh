#!/bin/sh
# Build the FS-UAE fork grahambates/fs-uae, branch remote_debugger_barto, in a
# clean Ubuntu 24.04 container, with the distribution's gcc.  Run inside the
# container with the source tree mounted at /src -- it installs packages with
# apt-get, so it is never run on the host.  Part of #464: the patched FS-UAE
# is the one whose GDB-remote port the automapper reads a live Amiga through.
# fsuaebuildclang.sh is the same build with clang.
set -eu
export DEBIAN_FRONTEND=noninteractive
echo "### apt start $(date -Is)"
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  autoconf automake build-essential gettext pkg-config \
  libfreetype6-dev libglew-dev libglib2.0-dev libjpeg-dev \
  libmpeg2-4-dev libopenal-dev libpng-dev libsdl2-dev libsdl2-ttf-dev \
  libtool libxi-dev libxtst-dev zip zlib1g-dev >/dev/null
echo "### apt done $(date -Is)"
gcc --version | head -1
cd /src
echo "### bootstrap $(date -Is)"
./bootstrap
echo "### configure $(date -Is)"
./configure
echo "### make $(date -Is)"
make -j"$(nproc)" 2>&1 | tail -400
echo "### make exit=$? $(date -Is)"
ls -la fs-uae 2>/dev/null && file fs-uae
