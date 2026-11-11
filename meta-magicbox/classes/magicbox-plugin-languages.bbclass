# Apply only to the plugin recipes which embed catalogs in their runtime IPKs.
# Filtering PKGD also keeps a later package update from restoring other languages.
python magicbox_limit_plugin_languages() {
    import os
    import shutil

    value = d.getVar('PKGD')
    if not value or not os.path.isabs(value) or os.path.islink(value):
        bb.fatal('An ordinary absolute package staging directory is required')
    root = os.path.realpath(value)
    if root == os.path.sep or not os.path.isdir(root):
        bb.fatal('A package staging directory is required')

    def supported(name):
        return name.lower().split('.')[0].replace('-', '_').split('_')[0] in ('en', 'tr')

    removed = 0
    for base, directories, files in os.walk(root, followlinks=False, topdown=False):
        if 'LC_MESSAGES' not in directories or supported(os.path.basename(base)):
            continue
        if os.path.commonpath([root, os.path.realpath(os.path.dirname(base))]) != root:
            bb.fatal('A plugin catalog path escaped package staging')
        shutil.rmtree(base)
        removed += 1
    for base, directories, files in os.walk(root, followlinks=False):
        if 'LC_MESSAGES' in directories and not supported(os.path.basename(base)):
            bb.fatal('An unrequested plugin catalog remains in the package')
    bb.note('Magic Box plugin languages: English/Turkish only; removed %d catalog directories' % removed)
}
PACKAGE_PREPROCESS_FUNCS += " magicbox_limit_plugin_languages"
