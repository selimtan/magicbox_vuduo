#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false
build_target=${MAGICBOX_BUILD_TARGET:-enigma2}
case "$build_target" in enigma2|magicbox-image) ;; *) echo 'Unsupported Magic Box build target'; exit 2 ;; esac
build_jobs=${MAGICBOX_BUILD_JOBS:-2}
case "$build_jobs" in 1|2|3|4) ;; *) echo 'Build jobs must be between 1 and 4'; exit 2 ;; esac
if test "${MAGICBOX_DEPS_READY:-0}" != 1; then
sudo apt-get update
sudo apt-get install -y --no-install-recommends build-essential gawk wget git diffstat unzip texinfo chrpath cpio python3 python3-distutils python3-setuptools python3-pexpect python3-git python3-jinja2 xz-utils debianutils iputils-ping file locales gettext rsync bison flex swig subversion openjdk-11-jre-headless socat libproc-processtable-perl
sudo locale-gen en_US.UTF-8
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
if ! swapon --show=NAME --noheadings | grep -q /swapfile; then
    sudo fallocate -l 8G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
fi
fi
source_dir="$HOME/magicbox-source"
git config --global --replace-all url.https://github.com/openembedded/.insteadOf https://git.openembedded.org/
git config --global --add url.https://github.com/openembedded/.insteadOf git://git.openembedded.org/
git config --global --replace-all url.https://git.yoctoproject.org/.insteadOf git://git.yoctoproject.org/
git config --global http.lowSpeedLimit 1024
git config --global http.lowSpeedTime 60
if ! test -d "$HOME/openpli-oe-core/.git"; then
    git clone --depth 1 --branch release-9.2 https://github.com/OpenPLi/openpli-oe-core.git "$HOME/openpli-oe-core"
fi
cd "$HOME/openpli-oe-core"
if test "$(git rev-parse HEAD)" != 0e452344349e700c4a2a7180d61941ce75c5541e; then
    git fetch origin 0e452344349e700c4a2a7180d61941ce75c5541e
    git checkout --detach 0e452344349e700c4a2a7180d61941ce75c5541e
fi
# OpenPLi has common bbappends for other vendors too. Use its complete BSP layer
# set so those append/recipe pairs stay intact, while MACHINE remains vuduo.
mapfile -t submodules < <(git config -f .gitmodules --get-regexp '^submodule\..*\.path$' | awk '$2 != "meta-python2" {print $2}')
git submodule update --init --depth 1 --jobs 4 "${submodules[@]}"
# enigma-info reads these revisions from a fakeroot install task. Pseudo's
# effective UID differs from the real builder ownership seen by newer Git.
# Trust only the two pinned metadata checkouts used by that task.
for repository in "$HOME/openpli-oe-core" "$HOME/openpli-oe-core/openembedded-core"; do
    if ! git config --global --get-all safe.directory | grep -Fxq "$repository"; then
        git config --global --add safe.directory "$repository"
    fi
done
cp -a "$source_dir/meta-magicbox" "$HOME/openpli-oe-core/"
layers=$(python3 - <<'PY'
from pathlib import Path
import re
root = Path.cwd()
section = (root/'Makefile').read_text().split('BBLAYERS ?=',1)[1].split('\n\n',1)[0]
names = re.findall(r'\$\(CURDIR\)/([A-Za-z0-9_./-]+)', section)
names = [name for name in names if name != 'meta-python2'] + ['meta-magicbox']
assert 'meta-vuplus' in names and 'meta-dream' in names and 'meta-qt5' in names
for name in names:
    assert (root/name).is_dir(), 'Missing layer: '+name
print(' '.join(str(root/name) for name in names))
PY
)
# Reuse completed tasks and the compiler cache. Local development can use four
# jobs; the default remains two for a smaller Linux build machine.
BBLAYERS="$layers" BB_NUMBER_THREADS="$build_jobs" PARALLEL_MAKE="-j $build_jobs" make init
# OpenPLi creates site.conf only once. Update its existing scheduler settings
# explicitly as well, keeping the rest of the configured source/feed policy.
MAGICBOX_BUILD_JOBS="$build_jobs" python3 - <<'PY'
from pathlib import Path
import re
import os
path = Path('site.conf')
text = path.read_text()
jobs = os.environ['MAGICBOX_BUILD_JOBS']
for key, value in [('BB_NUMBER_THREADS', jobs), ('PARALLEL_MAKE', '-j '+jobs)]:
    text, count = re.subn(r'^'+key+r'[ \t]*=[ \t]*"[^"\n]*"[ \t]*$', key+' = "'+value+'"', text, flags=re.M)
    assert count == 1, 'Expected one existing site setting: '+key
retention = 'RM_WORK_EXCLUDE_append = " magicbox-image enigma2"'
text = text.replace('RM_WORK_EXCLUDE_append = " magicbox-image"', retention)
if retention not in text.splitlines():
    text += '\n# Keep the final root for privacy checks and Enigma2 for incremental device fixes.\n'+retention+'\n'
path.write_text(text)
PY
if ! grep -q 'MAGICBOX_CONFIG' site.conf; then
    cat >>site.conf <<'EOF'
# MAGICBOX_CONFIG
ENIGMA2_BRANCH = "release-9.2"
DISTRO_NAME = "magicbox"
DISTRO_VERSION = "2.0.0"
DISTRO_FEED_URI = "https://45.87.174.241:8448/feeds/magicbox-2/vuduo"
EOF
fi
python3 - <<'PY'
from pathlib import Path
import os
import re
marker = Path.home()/'.magicbox-fast-tmp'
stop, abort = '8G', '3G'
if marker.exists():
    value = marker.read_text()
    assert value in ('12884901888 /dev/nbd2\n', '42949672960 /dev/nbd2\n')
    volume_bytes = int(value.split()[0])
    assert os.stat('build/tmp').st_dev != os.stat(Path.home()).st_dev, 'Fast TMPDIR is not mounted'
    space = os.statvfs('build/tmp')
    assert volume_bytes*9//10 < space.f_blocks*space.f_frsize <= volume_bytes
    stop, abort = '2G', '1G'
path = Path('site.conf')
text = path.read_text()
rule = 'BB_DISKMON_DIRS = "STOPTASKS,${TMPDIR},'+stop+',100K ABORT,${TMPDIR},'+abort+',50K"'
text, count = re.subn(r'^BB_DISKMON_DIRS[ \t]*=[^\n]*$', rule, text, flags=re.M)
assert count <= 1, 'Duplicate build disk monitors'
if not count:
    text += '\n'+rule+'\n'
path.write_text(text)
PY
source build/env.source
cd build
export MACHINE=vuduo
if test -f "$HOME/.magicbox-sysroot-repair"; then
    test "$(cat "$HOME/.magicbox-sysroot-repair")" = 'binutils-cross-mipsel gcc-cross-mipsel'
    # Recreate missing assembler staging and all GCC configure results that
    # depended on it. Other completed recipes and source downloads stay cached.
    bitbake -c cleansstate binutils-cross-mipsel gcc-cross-mipsel
    rm -f "$HOME/.magicbox-sysroot-repair"
fi
if test -f "$HOME/.magicbox-repair-cleanup"; then
    cleanup=$(cat "$HOME/.magicbox-repair-cleanup")
    case "$cleanup" in
        'libmpc-native linux-libc-headers gcc-source-10.3.0'|'linux-libc-headers gcc-source-10.3.0') ;;
        *) echo 'Unexpected task repair marker'; exit 1 ;;
    esac
    read -r -a cleanup_recipes <<<"$cleanup"
    bitbake -c clean "${cleanup_recipes[@]}"
    rm -f "$HOME/.magicbox-repair-cleanup"
fi
bitbake "$build_target"
