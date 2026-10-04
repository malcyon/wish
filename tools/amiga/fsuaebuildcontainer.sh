#!/bin/sh
# Build the FS-UAE fork grahambates/fs-uae, branch remote_debugger_barto, in a
# clean Ubuntu 24.04 container, with the distribution's gcc.  Run inside the
# container with the source tree mounted at /src and the checkout's tools/amiga
# at /patches -- it installs packages with apt-get, so it is never run on the
# host.  The patches below are applied first; the binary is /src/fs-uae.
# Part of #464: the patched FS-UAE is the one whose GDB-remote port the
# automapper reads a live Amiga through.
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
# Wish's own changes to the fork: every fsuae-*.patch in $FSUAE_PATCHES (the
# checkout's tools/amiga, mounted read-only at /patches by default) is applied
# in name order; a patch already in the tree is skipped, and one that fits
# neither way stops the build.
PATCHES=${FSUAE_PATCHES:-/patches}
for p in "$PATCHES"/fsuae-*.patch; do
  [ -e "$p" ] || { echo "no fsuae-*.patch in $PATCHES"; exit 1; }
  if patch -p1 -R -f -s --dry-run <"$p" >/dev/null 2>&1; then
    echo "### already applied $p"
  else
    patch -p1 -N <"$p"
    echo "### applied $p"
  fi
done
echo "### bootstrap $(date -Is)"
./bootstrap
echo "### configure $(date -Is)"
./configure
echo "### make $(date -Is)"
make -j"$(nproc)" 2>&1 | tail -400
echo "### make exit=$? $(date -Is)"
ls -la fs-uae 2>/dev/null && file fs-uae
