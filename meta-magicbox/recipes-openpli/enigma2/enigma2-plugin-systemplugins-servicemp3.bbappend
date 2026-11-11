# Keep pending IPTV connection cancellation off the multi-second state wait.
SRCREV = "bdb5a908276b69a913ca50cb8c274d1b5977ad82"
PR_append = ".magicbox3"
FILESEXTRAPATHS_prepend := "${THISDIR}/files:"
SRC_URI += "file://magicbox-stream-cancel.patch"
