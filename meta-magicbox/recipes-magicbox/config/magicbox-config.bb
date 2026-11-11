SUMMARY = "Magic Box OS identity, native home defaults and exclusive update feeds"
LICENSE = "GPLv2"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/GPL-2.0-only;md5=801f80980d171dd6425610833a22dbe6"
SRC_URI = "file://magicbox-updates.crt file://settings file://lamedb file://userbouquet.magicbox.tv file://bouquets.tv"
S = "${WORKDIR}"
DEPENDS = "curl"
RDEPENDS_${PN} = "ca-certificates wget"
PACKAGE_ARCH = "${MACHINE_ARCH}"
PR_append = ".magicbox3"
FILES_${PN} += "${datadir}/ca-certificates/magicbox"
ERROR_QA_append = " installed-vs-shipped"

do_install() {
    install -d ${D}${sysconfdir}/opkg ${D}${sysconfdir}/enigma2 ${D}${datadir}/ca-certificates/magicbox
    install -m 0644 ${WORKDIR}/settings ${D}${sysconfdir}/enigma2/settings
    install -m 0644 ${WORKDIR}/lamedb ${D}${sysconfdir}/enigma2/lamedb
    install -m 0644 ${WORKDIR}/userbouquet.magicbox.tv ${D}${sysconfdir}/enigma2/userbouquet.magicbox.tv
    install -m 0644 ${WORKDIR}/bouquets.tv ${D}${sysconfdir}/enigma2/bouquets.tv
    install -m 0644 ${WORKDIR}/magicbox-updates.crt ${D}${datadir}/ca-certificates/magicbox/updates.crt
    for arch in all ${TUNE_PKGARCH} ${MACHINE_ARCH}; do
        echo "src/gz magicbox2-$arch https://45.87.174.241:8448/feeds/magicbox-2/vuduo/$arch" >> ${D}${sysconfdir}/opkg/magicbox-feed.conf
    done
    echo 'option cache_dir /tmp/magicbox-opkg' >> ${D}${sysconfdir}/opkg/magicbox-feed.conf
    echo 'Magic Box OS 2.0.0 (OpenPLi 9.2 source base)' > ${D}${sysconfdir}/magicbox-release
}
pkg_postinst_${PN}() {
    if [ -n "$D" ]; then
        echo 'magicbox/updates.crt' >> $D${sysconfdir}/ca-certificates.conf
    else
        grep -q '^magicbox/updates.crt$' ${sysconfdir}/ca-certificates.conf || echo 'magicbox/updates.crt' >> ${sysconfdir}/ca-certificates.conf
        update-ca-certificates
    fi
}
CONFFILES_${PN} = "${sysconfdir}/enigma2/settings ${sysconfdir}/enigma2/lamedb ${sysconfdir}/enigma2/userbouquet.magicbox.tv ${sysconfdir}/enigma2/bouquets.tv ${sysconfdir}/opkg/magicbox-feed.conf"
