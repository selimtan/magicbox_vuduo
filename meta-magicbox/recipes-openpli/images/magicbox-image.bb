require recipes-openpli/images/openpli-enigma2-image.bb

SUMMARY = "Magic Box OS 2.0 for the original Vu+ Duo, native Enigma2 home"
DISTRO_NAME = "magicbox"
DISTRO_VERSION = "2.0.0"
IMAGE_BASENAME = "magicbox"
IMAGE_INSTALL_remove = "distro-feed-configs 3rd-party-feed-configs openpli-bootlogo"
IMAGE_INSTALL += "magicbox-config magicbox-bootlogo enigma2-plugin-extensions-enhancedmoviecenter"
# The upstream package-index task depends on building a stock OpenPLi image.
# Our feed is collected from this image's exact manifest after verification.
DEPENDS_remove = "package-index"
IMAGE_LINGUAS = "en-gb tr-tr"
IMAGE_LOCALES_ARCHIVE = "0"

python magicbox_limit_languages() {
    import os
    import shutil

    root = os.path.realpath(d.getVar('IMAGE_ROOTFS'))
    locale_roots = [os.path.join(root, value.lstrip('/'), 'locale')
                    for value in (d.getVar('libdir'), d.getVar('datadir'))]
    baseline = {'fake', 'C', 'C.utf8', 'C.UTF-8', 'POSIX'}

    def required_baseline(path):
        return os.path.dirname(path) == locale_roots[0] and os.path.basename(path) in baseline

    def supported(name):
        return name.lower().split('.')[0].replace('-', '_').split('_')[0] in ('en', 'tr')

    def remove(path):
        # The image root is private build output; never follow external links.
        if os.path.commonpath([root, os.path.realpath(os.path.dirname(path))]) != root:
            bb.fatal('Locale path escaped the image root')
        if os.path.islink(path) or not os.path.isdir(path):
            os.unlink(path)
        else:
            shutil.rmtree(path)

    for base, directories, files in os.walk(root, followlinks=False, topdown=False):
        if 'LC_MESSAGES' in directories and not supported(os.path.basename(base)):
            if required_baseline(base):
                continue
            remove(base)
    for parent in locale_roots:
        if not os.path.isdir(parent):
            continue
        for name in os.listdir(parent):
            path = os.path.join(parent, name)
            if (os.path.isdir(path) or os.path.islink(path)) and not supported(name):
                if not required_baseline(path):
                    remove(path)
    # Assert the final filesystem policy before mkfs, including plugin catalogs.
    for base, directories, files in os.walk(root, followlinks=False):
        if 'LC_MESSAGES' in directories and not supported(os.path.basename(base)):
            if not required_baseline(base):
                bb.fatal('An unrequested UI language remains in the image')
    for language in ('en', 'tr'):
        catalog = os.path.join(root, d.getVar('datadir').lstrip('/'), 'enigma2/po', language, 'LC_MESSAGES/enigma2.mo')
        if not os.path.isfile(catalog):
            bb.fatal('A requested Enigma2 translation catalog is absent: ' + language)
}

magicbox_verify_rootfs() {
    test -e ${IMAGE_ROOTFS}${bindir}/enigma2 || bbfatal "Native Enigma2 is absent"
    test -e ${IMAGE_ROOTFS}${datadir}/enigma2/magicbox/channels.json || bbfatal "TV catalog is absent"
    test ! -d ${IMAGE_ROOTFS}${libdir}/enigma2/python/Plugins/Extensions/MagicBox || bbfatal "Legacy MagicBox plugin must not be in this image"
    test ! -e ${IMAGE_ROOTFS}${sysconfdir}/enigma2/magicbox-iptv/account.json || bbfatal "A private IPTV account entered the generic image"
    test ! -e ${IMAGE_ROOTFS}${sysconfdir}/enigma2/magicbox-favorites/favorites.json || bbfatal "Private favorites entered the generic image"
    grep -qx 'config.misc.initialchannelselection=False' ${IMAGE_ROOTFS}${sysconfdir}/enigma2/settings || bbfatal "The native home must not launch the legacy first-channel selector"
    grep -aq 'MagicBoxHomeActions' ${IMAGE_ROOTFS}${bindir}/enigma2 || bbfatal "Native home widget is absent from the Enigma2 binary"
    if grep -r -E '^[[:space:]]*src(/gz)?[[:space:]].*(openpli|downloads\.openpli)' ${IMAGE_ROOTFS}${sysconfdir}/opkg*; then
        bbfatal "An upstream update feed remains enabled"
    fi
    actual_feeds=$(grep -rh -E '^[[:space:]]*src(/gz)?[[:space:]]' ${IMAGE_ROOTFS}${sysconfdir}/opkg* | awk '{print $3}' | sort)
    expected_feeds=$(printf '%s\n' 'https://45.87.174.241:8448/feeds/magicbox-2/vuduo/all' 'https://45.87.174.241:8448/feeds/magicbox-2/vuduo/mips32el' 'https://45.87.174.241:8448/feeds/magicbox-2/vuduo/vuduo' | sort)
    test "$actual_feeds" = "$expected_feeds" || bbfatal "The image must contain exactly the three Magic Box update feeds"
    cat ${IMAGE_ROOTFS}${datadir}/ca-certificates/magicbox/updates.crt >> ${IMAGE_ROOTFS}${sysconfdir}/ssl/certs/ca-certificates.crt
}
ROOTFS_POSTPROCESS_COMMAND += "magicbox_limit_languages; magicbox_verify_rootfs; "
