"""Audit the committed files in the actual original-Duo USB image, locally.

Requires the pinned UBI Reader installed on the audit computer. No files are
extracted or executed, and no receiver or update server is contacted. Only
fresh, clean mkfs images are accepted: journal replay is deliberately outside
this check. Format integrity and known private strings are checked; boot,
runtime behavior, and the absence of every possible secret are not proved.
"""
import argparse
import contextlib
import hashlib
import importlib.metadata
import importlib.util
import io
import json
from pathlib import Path
import re
import stat
import struct
import tempfile
from types import SimpleNamespace
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
READER_REVISION = '5f45e50c813599d689b8cf88e12e7c79dec1728f'
READER_TREE_SHA256 = '3bbc7f454e1c331a9db687312ea628b3ed0b2569e7ea5af8d65afa76be3dc1db'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reader_identity():
    import ubireader
    base = Path(ubireader.__file__).parent
    rows = [path.relative_to(base).as_posix()+' '+hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(base.rglob('*.py'))]
    digest = hashlib.sha256('\n'.join(rows).encode()).hexdigest()
    version = importlib.metadata.version('ubi-reader')
    require(version == '0.8.16' and digest == READER_TREE_SHA256,
            'The installed UBI Reader differs from the checked source revision')
    return {'reader_version': version, 'reader_reference_revision': READER_REVISION,
            'reader_python_tree_sha256': digest,
            'reader_dependencies': {name: importlib.metadata.version(name)
                                    for name in ('lzallright','zstandard','cryptography')}}


class CheckedNodes:
    """Verify each indexed node CRC before UBI Reader can interpret its body."""
    def __init__(self, source, size, leb):
        self.source, self.size, self.leb = source, size, leb
        self.verify_nodes = True
        self.visited = set()
        self.last = 0
        self.at_header = False

    def seek(self, offset):
        require(0 <= offset < self.size, 'UBIFS index points outside the volume')
        self.source.seek(offset)
        self.at_header = True

    def read(self, amount):
        position = self.source.tell()
        require(0 <= amount <= self.leb and position+amount <= self.size,
                'UBIFS node read exceeds its bounds')
        data = self.source.read(amount)
        require(len(data) == amount, 'Truncated UBIFS node')
        if self.verify_nodes and self.at_header:
            require(amount == 24 and data[:4] == b'\x31\x18\x10\x06',
                    'Invalid indexed UBIFS node header')
            require(data[20] in (0, 1, 2, 3, 9), 'Unsupported node type in committed index')
            length = struct.unpack_from('<I', data, 16)[0]
            require(24 <= length <= self.leb-position % self.leb,
                    'Indexed UBIFS node crosses an eraseblock')
            require(position not in self.visited and len(self.visited) < 250000,
                    'Repeated or oversized UBIFS index')
            self.visited.add(position)
            body = self.source.read(length-24)
            require(len(body) == length-24 and
                    (~zlib.crc32(data[8:]+body) & 0xffffffff) == struct.unpack_from('<I', data, 4)[0],
                    'Indexed UBIFS node CRC failed')
            # The upstream walker must see exactly the bytes it requested.
            self.source.seek(position+amount)
        self.at_header = False
        self.last = position
        return data

    def last_read_addr(self):
        return self.last


def inspect_volume(source, size, leb, patterns):
    from ubireader import settings
    from ubireader.ubifs import nodes, walk, misc, defines

    source.seek(leb)
    first = source.read(512)
    source.seek(2*leb)
    second = source.read(512)
    # Redundant master nodes have different common-header sequence numbers.
    require(first[24:] == second[24:] and
            struct.unpack_from('<I', first, 16)[0] == struct.unpack_from('<I', second, 16)[0] == 512,
            'Fresh image master node bodies must agree')
    master = nodes.mst_node(first[24:24+defines.UBIFS_MST_NODE_SZ])
    require(master.cmt_no == 0 and not master.flags & 5,
            'Only a fresh, clean mkfs image can be audited without journal replay')
    checked = CheckedNodes(source, size, leb)
    filesystem = SimpleNamespace(file=checked, leb_size=leb, master_node=master, master_key=None)
    inodes, bad = {}, []
    old_action = settings.error_action
    settings.error_action = 'exit'
    try:
        # Diagnostics can contain filenames; never print them when a check fails.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            walk.index(filesystem, master.root_lnum, master.root_offs, inodes, bad)
        require(not bad and 1 in inodes and 1 < len(inodes) <= 100000,
                'Missing or excessive committed UBIFS inodes')
        checked.verify_nodes = False

        def check(payload):
            for label, needle in patterns:
                if needle in payload or (label == 'provider_host' and needle.lower() in payload.lower()):
                    raise ValueError('Private '+label+' found in image content')

        count, total, files, links, attrs = 0, 0, 0, 0, 0
        seen, xattr_inodes, names = set(), set(), set()
        forbidden = {'etc/enigma2/magicbox-iptv/account.json',
                     'etc/enigma2/magicbox-favorites/favorites.json'}

        def visit(number, name, entry_type, depth):
            nonlocal count, total, files, links, attrs
            count += 1
            require(count <= 50000 and depth <= 64 and len(name) <= 4096,
                    'Filesystem tree exceeds the audit limits')
            require(name not in names, 'Duplicate filesystem path')
            names.add(name)
            require(name not in forbidden and '/Plugins/Extensions/MagicBox/' not in '/'+name+'/',
                    'A private receiver file or legacy launcher is present in the image')
            check(name.encode('utf-8'))
            require(number in inodes and 'ino' in inodes[number], 'Missing referenced inode')
            require(number not in xattr_inodes, 'An attribute inode is also used as a file')
            inode = inodes[number]
            info = inode['ino']
            require(not info.flags & defines.UBIFS_XATTR_FL, 'Attribute inode used in the file tree')
            modes = (stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK, stat.S_IFBLK,
                     stat.S_IFCHR, stat.S_IFIFO, stat.S_IFSOCK)
            require(0 <= entry_type < len(modes) and stat.S_IFMT(info.mode) == modes[entry_type],
                    'Directory entry type differs from its inode')
            if number in seen:
                require(entry_type != defines.UBIFS_ITYPE_DIR, 'Repeated filesystem directory')
                return
            seen.add(number)
            check(info.data)
            require(info.xattr_cnt == len(inode.get('xent', [])), 'Incomplete extended-attribute index')
            for attribute in inode.get('xent', []):
                require(attribute.inum in inodes and 'ino' in inodes[attribute.inum],
                        'Missing extended-attribute inode')
                value = inodes[attribute.inum]['ino']
                require(attribute.inum not in seen | xattr_inodes and
                        value.flags & defines.UBIFS_XATTR_FL and
                        set(inodes[attribute.inum]) == {'ino'} and
                        0 <= value.size <= 4096 and len(value.data) == value.size,
                        'Invalid extended-attribute value')
                check(attribute.name.encode('utf-8')+b'\0'+value.data)
                xattr_inodes.add(attribute.inum)
                attrs += 1
            if entry_type == defines.UBIFS_ITYPE_DIR:
                for dent in inode.get('dent', []):
                    require(dent.name not in ('', '.', '..') and '/' not in dent.name and '\0' not in dent.name,
                            'Invalid filesystem path component')
                    visit(dent.inum, name+'/'+dent.name if name else dent.name, dent.type, depth+1)
            elif entry_type == defines.UBIFS_ITYPE_REG:
                require(0 <= info.size <= 128*1024*1024, 'File exceeds the audit limit')
                total += info.size
                require(total <= 512*1024*1024, 'Image contents exceed the audit limit')
                keys = set()
                payload = bytearray(info.size)
                for block in inode.get('data', []):
                    index = block.key['khash']-(defines.UBIFS_DATA_KEY << defines.UBIFS_S_KEY_BLOCK_BITS)
                    require(0 <= index < (info.size+4095)//4096 and index not in keys and
                            0 < block.size <= min(4096, info.size-index*4096) and
                            block.compr_type in (0, 1, 2) and 0 < block.compr_len <= 4096,
                            'Invalid or unsupported file data block')
                    keys.add(index)
                    checked.seek(block.offset)
                    compressed = checked.read(block.compr_len)
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        expanded = misc.decompress(block.compr_type, block.size, compressed)
                    require(expanded is not None and len(expanded) == block.size,
                            'Decompressed file block length differs from its node')
                    payload[index*4096:index*4096+block.size] = expanded
                check(payload)
                files += 1
            elif entry_type == defines.UBIFS_ITYPE_LNK:
                require(info.size == len(info.data) <= 4096, 'Invalid symbolic link payload')
                check(info.data)
                links += 1

        visit(1, '', defines.UBIFS_ITYPE_DIR, 0)
        require(seen | xattr_inodes == set(inodes) and files > 0,
                'Unreachable or unscanned filesystem inodes')
        return {'filesystem_entries': count, 'regular_inodes': files, 'symlink_inodes': links,
                'extended_attributes': attrs, 'file_bytes_scanned': total,
                'indexed_nodes_crc_checked': len(checked.visited)}
    except SystemExit:
        raise ValueError('UBI Reader rejected the image; no successful privacy report') from None
    finally:
        settings.error_action = old_action


def audit_image(path, expected_sha256, account):
    require(re.fullmatch('[0-9a-fA-F]{64}', expected_sha256) is not None,
            'An independently recorded image SHA256 is required')
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'An ordinary image archive is required')
    verifier = load('duo_privacy_image_format', 'verify-image.py')
    report = verifier.verify(path, expected_sha256)
    identity = reader_identity()
    patterns = load('duo_privacy_patterns', 'audit-rootfs-privacy.py').account_patterns(account)
    root = report['members'][verifier.ROOT]
    leb, peb = root['logical_eraseblock_bytes'], root['physical_eraseblock_bytes']
    size = root['root_logical_eraseblocks']*leb
    with tempfile.TemporaryFile(dir=path.parent) as logical, zipfile.ZipFile(path) as archive:
        logical.truncate(size)
        with archive.open(verifier.ROOT) as image:
            for _ in range(root['image_eraseblocks']):
                block = image.read(peb)
                require(len(block) == peb, 'Truncated image root eraseblock')
                volume, number = struct.unpack_from('>II', block, 2048+8)
                if volume == 0:
                    require(number*leb < size, 'Root eraseblock outside the volume')
                    logical.seek(number*leb)
                    logical.write(block[4096:4096+leb])
            require(not image.read(1), 'Unexpected trailing root data')
        logical.flush()
        result = inspect_volume(logical, size, leb, patterns)
    with path.open('rb') as image:
        digest = hashlib.file_digest(image, 'sha256').hexdigest()
    require(digest == report['sha256'], 'Image changed during the privacy audit')
    from ubireader.ubifs import walk, misc, nodes
    module_hashes = {module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                     for module in (walk, misc, nodes)}
    return {'passed': True, 'scope': 'actual ZIP: fresh committed UBIFS paths, file contents, links and xattrs; known account strings/common encodings',
            'image_sha256': digest, 'root_member_sha256': root['sha256'], **result,
            'private_account_files_absent': True, 'legacy_launcher_plugin_absent': True,
            'known_provider_username_password_absent': True,
            **identity, 'reader_module_sha256': module_hashes,
            'audit_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'journal_replay': False, 'boot_verified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--private-account', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    arguments = parser.parse_args()
    if (arguments.report.resolve() in (arguments.image.resolve(), arguments.private_account.resolve()) or
            arguments.report.is_symlink()):
        parser.error('The report must be a separate ordinary file')
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = audit_image(arguments.image, arguments.sha256, arguments.private_account)
    except BaseException as error:
        arguments.report.write_text(json.dumps({'passed': False, 'error_type': type(error).__name__})+'\n', encoding='utf-8')
        raise SystemExit('Image privacy audit failed; no successful report. '+type(error).__name__) from None
    arguments.report.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))
