#!/bin/sh
# Build the FS-UAE fork grahambates/fs-uae, branch remote_debugger_barto, with
# clang, in a clean container with the source tree mounted at /src and the
# checkout's tools/amiga at /patches -- it installs packages with apt-get, so it
# is never run on the host.  It applies the same patches as
# fsuaebuildcontainer.sh.  Part of #464: the same build as
# fsuaebuildcontainer.sh with clang instead of gcc, the
# configure and make output kept in /tmp/conf.log and /tmp/make.log and the
# compiler errors grepped out at the end.  Exits with make's own status.
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  autoconf automake build-essential clang gettext pkg-config \
  libfreetype6-dev libglew-dev libglib2.0-dev libjpeg-dev \
  libmpeg2-4-dev libopenal-dev libpng-dev libsdl2-dev libsdl2-ttf-dev \
  libtool libxi-dev libxtst-dev zip zlib1g-dev >/dev/null
clang --version | head -1
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
make distclean >/dev/null 2>&1 || true
echo "### bootstrap $(date -Is)"
./bootstrap >/dev/null
echo "### configure $(date -Is)"
./configure CC=clang CXX=clang++ >/tmp/conf.log 2>&1 || { tail -40 /tmp/conf.log; exit 1; }
tail -30 /tmp/conf.log
echo "### make $(date -Is)"
set +e
make -j"$(nproc)" CC=clang CXX=clang++ >/tmp/make.log 2>&1
rc=$?
echo "### make exit=$rc $(date -Is)"
grep -nE 'error:|Error [0-9]' /tmp/make.log | head -40
ls -la fs-uae 2>/dev/null && file fs-uae
exit $rc
