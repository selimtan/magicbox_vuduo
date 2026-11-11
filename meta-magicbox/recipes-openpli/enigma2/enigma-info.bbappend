# Revision metadata must also work with the pinned, shallow source checkouts.
# Use the core layer's declared series and a real commit when no tag is present.
python __anonymous () {
    body = d.getVar("do_install", False)
    name_line = "OE_NAME=`cd ${OPENPLI_BASE} && git submodule | grep \"meta-openembedded\" | cut -d '(' -f 2 | cut -d ')' -f 1 | cut -d '/' -f 3 | cut -d'-' -f 1`"
    describe = "git describe --match=yocto*"
    if body.count(name_line) != 1 or body.count(describe) != 1:
        bb.fatal("Unexpected enigma-info revision metadata implementation")
    body = body.replace(name_line, 'OE_NAME="${LAYERSERIES_CORENAMES}"')
    identity = "displaydistro='OpenPLi'"
    if body.count(identity) != 1:
        bb.fatal("Unexpected enigma-info display identity implementation")
    body = body.replace(identity, "displaydistro='Magic Box OS'")
    d.setVar("do_install", body.replace(describe, describe + " --always"))
}
PR_append = ".magicbox1"
