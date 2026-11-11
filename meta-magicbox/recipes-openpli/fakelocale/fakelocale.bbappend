# Enigma2 uses en_EN for its English LC_TIME fallback. Turkish uses the full
# glibc locale installed through IMAGE_LINGUAS; do not own its LC_TIME twice.
LANGUAGES = "en_EN"
RPROVIDES_${PN} = "virtual-locale-en"
PR_append = ".magicbox1"
