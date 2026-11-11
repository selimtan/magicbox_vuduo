# OpenPLi's Python 3 compatible EMC fork, pinned for reproducible images/updates.
SRCREV = "23dc058965d4743b1d884a6dae63054c047ef2d4"
PR_append = ".magicbox3"
FILESEXTRAPATHS_prepend := "${THISDIR}/files:"
SRC_URI += "file://0001-openpli-standalone-player.patch"
LICENSE = "GPLv3+"
LIC_FILES_CHKSUM = "file://LICENSE;md5=1ebbd3e34237af26da5dc08a4e440464"
inherit magicbox-plugin-languages
EXTRA_OEMAKE += " LANGS='en tr'"
