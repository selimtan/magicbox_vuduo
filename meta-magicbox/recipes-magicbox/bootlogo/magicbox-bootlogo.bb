SUMMARY = "User-provided Magic Box boot picture"
LICENSE = "CLOSED"
SRC_URI = "file://bootlogo.mvi file://bootlogo"
S = "${WORKDIR}"
RDEPENDS_${PN} = "showiframe"
inherit update-rc.d
INITSCRIPT_NAME = "bootlogo"
INITSCRIPT_PARAMS = "start 21 S ."

do_install() {
    install -d ${D}${datadir} ${D}${sysconfdir}/init.d ${D}/boot
    install -m 0644 ${WORKDIR}/bootlogo.mvi ${D}${datadir}/bootlogo.mvi
    install -m 0755 ${WORKDIR}/bootlogo ${D}${sysconfdir}/init.d/bootlogo
    for name in bootlogo bootlogo_wait backdrop; do
        ln -sf ${datadir}/bootlogo.mvi ${D}/boot/$name.mvi
    done
}
FILES_${PN} = "/boot ${datadir}/bootlogo.mvi ${sysconfdir}/init.d/bootlogo"
