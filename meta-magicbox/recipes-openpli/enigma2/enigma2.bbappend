FILESEXTRAPATHS_prepend := "${THISDIR}/files:"
ENIGMA2_BRANCH = "release-9.2"
SRCREV = "65dc39356b2863915745176a16a562ec1aa366b4"
SRC_URI += "file://magicbox-native.patch file://magicbox"
DEPENDS += "json-c curl zlib"
FULL_OPTIMIZATION = "${O2_OPT}"
PR_append = ".magicbox8"
PKGV = "${PYTHON_BASEVERSION}+git${GITPKGV}+magicbox2.0.0"
RRECOMMENDS_${PN}_remove = "enigma2-plugin-skins-pli-hd"
RDEPENDS_${PN} += "${PYTHON_PN}-json"

do_install_append() {
    install -d ${D}${datadir}/enigma2/magicbox/assets/picons ${D}${datadir}/enigma2/MagicBox
    install -m 0644 ${WORKDIR}/magicbox/channels.json ${D}${datadir}/enigma2/magicbox/
    install -m 0644 ${WORKDIR}/magicbox/assets/*.jpg ${WORKDIR}/magicbox/assets/*.ttf ${WORKDIR}/magicbox/assets/OFL.txt ${D}${datadir}/enigma2/magicbox/assets/
    install -m 0644 ${WORKDIR}/magicbox/assets/*.svg ${D}${datadir}/enigma2/magicbox/assets/
    install -m 0644 ${WORKDIR}/magicbox/assets/picons/*.png ${D}${datadir}/enigma2/magicbox/assets/picons/
    install -m 0644 ${WORKDIR}/magicbox/skin.xml ${D}${datadir}/enigma2/MagicBox/skin.xml
}
FILES_${PN} += "${datadir}/enigma2/magicbox ${datadir}/enigma2/MagicBox"
