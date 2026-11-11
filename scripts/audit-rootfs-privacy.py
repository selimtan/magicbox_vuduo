"""Audit a generic root-filesystem tar locally before publishing its image.

The receiver account is read only on this computer. Neither its contents nor
their hashes are included in the report or sent to the build/update server.
This is a privacy check, not a boot, ABI or flash-format verification.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import urllib.parse


def account_patterns(path):
    account = json.loads(Path(path).read_text(encoding='utf-8'))
    url, username, password = (str(account.get(key, '')) for key in ('url', 'username', 'password'))
    hostname = urllib.parse.urlsplit(url).hostname
    if not hostname or not username or not password:
        raise ValueError('A valid local account reference is required for the privacy audit')
    patterns = []
    for label, value in [('provider_url', url), ('provider_host', hostname),
                         ('username', username), ('password', password)]:
        for text in (value, urllib.parse.quote(value, safe=''), json.dumps(value, ensure_ascii=True)[1:-1]):
            needle = text.encode('utf-8')
            if len(needle) < 4:
                raise ValueError('A reference is too short for an unambiguous binary privacy audit')
            if (label, needle) not in patterns:
                patterns.append((label, needle))
    patterns.append(('basic_auth', base64.b64encode((username+':'+password).encode('utf-8'))))
    return patterns


def audit(path, patterns):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(1024*1024):
            digest.update(block)
    overlap = max(len(needle) for _, needle in patterns)-1
    count, total, regular = 0, 0, 0
    forbidden = {'etc/enigma2/magicbox-iptv/account.json',
                 'etc/enigma2/magicbox-favorites/favorites.json'}

    def check(payload, index):
        for label, needle in patterns:
            found = needle in payload
            if label == 'provider_host':
                found = found or needle.lower() in payload.lower()
            if found:
                # Do not echo a secret or a possibly secret-bearing filename.
                raise ValueError('Private '+label+' found in archive member #'+str(index))

    with tarfile.open(path, 'r|*') as archive:
        for entry in archive:
            count += 1
            if count > 50000 or len(entry.name) > 4096:
                raise ValueError('Root archive metadata exceeds the audit limits')
            parts = PurePosixPath(entry.name).parts
            if '..' in parts or entry.name.startswith('/'):
                raise ValueError('Unexpected root archive member path')
            name = '/'.join(part for part in parts if part != '.')
            if name in forbidden or '/Plugins/Extensions/MagicBox/' in '/'+name+'/':
                raise ValueError('A private receiver file or legacy launcher is present in the generic root')
            check((entry.name+'\n'+entry.linkname).encode('utf-8', 'surrogateescape'), count)
            if entry.isfile():
                regular += 1
                total += entry.size
                if not 0 <= entry.size <= 128*1024*1024 or total > 512*1024*1024:
                    raise ValueError('Root archive contents exceed the audit limits')
                tail = b''
                received = 0
                with archive.extractfile(entry) as source:
                    while block := source.read(65536):
                        received += len(block)
                        joined = tail+block
                        check(joined, count)
                        tail = joined[-overlap:] if overlap else b''
                if received != entry.size:
                    raise ValueError('The root archive contains truncated file data')
    if not count or not regular:
        raise ValueError('An empty archive cannot pass a root privacy audit')
    return {'passed': True, 'scope': 'generic root archive: private paths and known account strings/common encodings',
            'artifact': path.name, 'artifact_sha256': digest.hexdigest(),
            'archive_members': count, 'regular_files': regular, 'file_bytes_scanned': total,
            'private_account_files_absent': True, 'legacy_launcher_plugin_absent': True,
            'known_provider_username_password_absent': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rootfs_tar', type=Path)
    parser.add_argument('--private-account', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = audit(args.rootfs_tar, account_patterns(args.private_account))
    except Exception as error:
        # A failed new check must not leave an earlier passing report in place.
        args.report.write_text(json.dumps({'passed': False, 'error_type': type(error).__name__})+'\n', encoding='utf-8')
        raise
    args.report.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
