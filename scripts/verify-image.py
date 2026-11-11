"""Validate the original Duo archive/flash format without writing a device.

This does not prove the contained OS boots or that its application works.
Layout definitions are from Linux v3.9's ubi-media.h and ubifs-media.h:
https://github.com/torvalds/linux/blob/v3.9/drivers/mtd/ubi/ubi-media.h
https://github.com/torvalds/linux/blob/v3.9/fs/ubifs/ubifs-media.h
SPDX-License-Identifier: GPL-2.0-or-later
"""
import argparse
import binascii
import hashlib
import json
from pathlib import Path
import stat
import struct
import zipfile
import zlib

ROOT_BYTES = 0x07600000
KERNEL_BYTES = 0x00400000
PEB = 0x20000
MIN_IO = 2048
LEB = 126976
ROOT = 'vuplus/duo/root_cfe_auto.jffs2'
KERNEL = 'vuplus/duo/kernel_cfe_auto.bin'
LAYOUT_VOLUME = 0x7fffefff


def require(condition, message):
    if not condition:
        raise ValueError(message)


def crc(data):
    # Linux crc32_le(~0, bytes) omits zlib's final XOR.
    return binascii.crc32(data) ^ 0xffffffff


def be32(data, offset):
    return struct.unpack_from('>I', data, offset)[0]


def le32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def validate_root(data):
    require(0 < len(data) <= ROOT_BYTES and len(data) % PEB == 0,
            'Root image size/alignment does not match the original Duo MTD0')
    blocks, layouts = {}, {}
    geometry = None
    for offset in range(0, len(data), PEB):
        block = memoryview(data)[offset:offset+PEB]
        ec = block[:64]
        require(bytes(ec[:4]) == b'UBI#' and ec[4] == 1, 'Invalid UBI erase-counter header')
        require(crc(ec[:60]) == be32(ec, 60), 'Damaged UBI erase-counter header CRC')
        vid_offset, data_offset, sequence = struct.unpack_from('>III', ec, 16)
        current = (vid_offset, data_offset, sequence)
        require(geometry is None or geometry == current, 'Mixed UBI image geometry or sequence')
        geometry = current
        require(vid_offset == MIN_IO and data_offset == PEB-LEB, 'UBI layout differs from the pinned Duo BSP')
        vid = block[vid_offset:vid_offset+64]
        require(bytes(vid[:4]) == b'UBI!' and vid[4] == 1 and vid[5] == 1,
                'The image must contain fresh dynamic UBI volumes')
        require(vid[6] == 0 and crc(vid[:60]) == be32(vid, 60), 'Damaged/copied UBI volume header')
        volume, number = struct.unpack_from('>II', vid, 8)
        require(volume in (0, LAYOUT_VOLUME), 'Unexpected volume in the generic Duo root image')
        destination = blocks if volume == 0 else layouts
        require(number not in destination, 'Duplicate logical eraseblock in a fresh image')
        destination[number] = block[data_offset:]
    require(set(layouts) == {0, 1}, 'Both UBI volume-table copies are required')
    table_size = 128*172
    require(bytes(layouts[0][:table_size]) == bytes(layouts[1][:table_size]), 'UBI volume-table copies differ')
    reserved = None
    for index in range(128):
        record = layouts[0][index*172:(index+1)*172]
        require(crc(record[:168]) == be32(record, 168), 'Damaged UBI volume-table record')
        count = be32(record, 0)
        if not count:
            continue
        require(index == 0 and reserved is None, 'The image must have exactly one root volume')
        reserved = count
        name_length = struct.unpack_from('>H', record, 14)[0]
        require(name_length == 6 and bytes(record[16:22]) == b'rootfs', 'Wrong UBI root volume name')
        require(be32(record, 4) == 1 and be32(record, 8) == 0 and record[12] == 1 and record[13] == 0,
                'Invalid root volume alignment/type/update state')
        require(record[144] & 1, 'Root volume must expand to the available flash on first boot')
    require(reserved and reserved+2 <= ROOT_BYTES//PEB, 'Root volume exceeds the physical partition')
    require(0 in blocks and 1 in blocks and 2 in blocks, 'UBIFS superblock or master blocks are absent')
    superblock = blocks[0]
    length = le32(superblock, 16)
    require(bytes(superblock[:4]) == b'\x31\x18\x10\x06' and superblock[20] == 6 and length == 4096,
            'The root volume is not a UBIFS superblock')
    require(crc(superblock[8:length]) == le32(superblock, 4), 'Damaged UBIFS superblock CRC')
    min_io, leb_size, count, maximum = struct.unpack_from('<IIII', superblock, 32)
    require(min_io == MIN_IO and leb_size == LEB, 'UBIFS geometry differs from the Duo build recipe')
    require(0 < count <= reserved and maximum >= count, 'Invalid UBIFS logical eraseblock count')
    require(set(blocks) == set(range(count)), 'UBIFS image contains missing/extra logical eraseblocks')
    require(le32(superblock, 80) == 4 and le32(superblock, 124) == 0,
            'UBIFS format is newer than the pinned 3.9 kernel supports')
    for index in (1, 2):
        node = blocks[index]
        node_length = le32(node, 16)
        require(bytes(node[:4]) == b'\x31\x18\x10\x06' and node[20] == 7 and 24 <= node_length <= LEB,
                'Invalid UBIFS master node')
        require(crc(node[8:node_length]) == le32(node, 4), 'Damaged UBIFS master node CRC')
    return {'format': 'UBI/UBIFS', 'physical_eraseblock_bytes': PEB,
            'logical_eraseblock_bytes': LEB, 'minimum_io_bytes': MIN_IO,
            'image_eraseblocks': len(data)//PEB, 'root_logical_eraseblocks': count,
            'reserved_root_eraseblocks': reserved, 'ubifs_format': le32(superblock, 80)}


def validate_kernel(data):
    require(0 < len(data) <= KERNEL_BYTES and data[:2] == b'\x1f\x8b',
            'Kernel must be the Duo BSP gzip binary and fit MTD1')
    decoder = zlib.decompressobj(16+zlib.MAX_WBITS)
    expanded = decoder.decompress(data, 32*1024*1024+1)
    require(len(expanded) <= 32*1024*1024 and decoder.eof and not decoder.unused_data,
            'Invalid, oversized or concatenated kernel gzip stream')
    require(len(expanded) >= 4096, 'Kernel payload is implausibly small')
    return {'format': 'gzip', 'expanded_bytes': len(expanded)}


def verify(path, expected_sha256=None):
    path = Path(path)
    require(0 < path.stat().st_size <= ROOT_BYTES+KERNEL_BYTES+1024*1024, 'Archive size is implausible for the original Duo')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    require(not expected_sha256 or digest == expected_sha256.lower(), 'Archive SHA256 differs from the trusted build result')
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        files = [entry for entry in entries if not entry.is_dir()]
        require(len(files) == 2 and {entry.filename for entry in files} == {ROOT, KERNEL},
                'Only the two original Vu+ Duo flash files may appear in this archive')
        for entry in entries:
            require(not entry.flag_bits & 1 and not stat.S_ISLNK(entry.external_attr >> 16),
                    'Encrypted/symlink archive members are not allowed')
            require(entry.filename in (ROOT, KERNEL, 'vuplus/', 'vuplus/duo/'), 'Unexpected archive directory')
        require(archive.getinfo(ROOT).file_size <= ROOT_BYTES and archive.getinfo(KERNEL).file_size <= KERNEL_BYTES,
                'Archive member exceeds its Duo flash partition')
        root, kernel = archive.read(ROOT), archive.read(KERNEL)
    result = {'verification_scope': 'archive, geometry and format integrity; boot/runtime validation is separate',
              'machine': 'vuduo', 'archive': path.name, 'bytes': path.stat().st_size, 'sha256': digest,
              'members': {ROOT: {'bytes': len(root), 'sha256': hashlib.sha256(root).hexdigest(), **validate_root(root)},
                          KERNEL: {'bytes': len(kernel), 'sha256': hashlib.sha256(kernel).hexdigest(), **validate_kernel(kernel)}}}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--expected-sha256')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    report = json.dumps(verify(args.image, args.expected_sha256), indent=2)+'\n'
    if args.report:
        args.report.write_text(report, encoding='utf-8')
    print(report, end='')
