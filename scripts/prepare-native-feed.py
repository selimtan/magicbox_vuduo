"""Prepare a separate native-OS feed from the exact installed-image manifest.

Run after a successful image build. Nothing is published or installed here.
Only the packages actually listed by that image are copied; the legacy plugin
cannot satisfy the native Enigma2/configuration package requirements.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile

ARCHES=('all','mips32el','vuduo')


def hashes(path):
    sha,md5=hashlib.sha256(),hashlib.md5()
    with path.open('rb') as stream:
        while block:=stream.read(1024*1024):
            sha.update(block)
            md5.update(block)
    return {'sha256':sha.hexdigest(),'md5':md5.hexdigest(),'bytes':path.stat().st_size}


def control(path):
    """Read only the bounded control member, without extracting any paths."""
    path=Path(path)
    if path.is_symlink() or not 0 < path.stat().st_size <= 128*1024*1024:
        raise ValueError('Unexpected IPK file type or size')
    raw=None
    binary=None
    with path.open('rb') as source:
        if source.read(8)!=b'!<arch>\n':
            raise ValueError('IPK is not a Debian ar archive')
        while header:=source.read(60):
            if len(header)!=60 or header[58:]!=b'`\n':
                raise ValueError('Invalid IPK ar header')
            name=header[:16].decode('ascii').strip().rstrip('/')
            size=int(header[48:58])
            start=source.tell()
            if size<0 or start+size>path.stat().st_size:
                raise ValueError('Truncated IPK member')
            if name=='debian-binary':
                if binary is not None or size>16:
                    raise ValueError('Ambiguous IPK format marker')
                binary=source.read(size)
            elif name.startswith('control.tar.'):
                if raw is not None or size>1024*1024:
                    raise ValueError('Ambiguous or oversized IPK control archive')
                raw=source.read(size)
            source.seek(start+size+(size%2))
    if binary!=b'2.0\n' or raw is None:
        raise ValueError('Missing IPK format marker or control archive')
    payload=None
    total=0
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r|*') as archive:
        for index,entry in enumerate(archive,1):
            total+=entry.size
            if index>128 or not 0<=entry.size<=1024*1024 or total>2*1024*1024:
                raise ValueError('IPK control content exceeds limits')
            if entry.name in ('control','./control'):
                if payload is not None or not entry.isfile():
                    raise ValueError('Ambiguous IPK control file')
                payload=archive.extractfile(entry).read()
    if payload is None:
        raise ValueError('IPK has no control file')
    text=payload.decode('utf-8').replace('\r\n','\n').rstrip('\n')+'\n'
    fields={}
    last=None
    for line in text.splitlines():
        if line[:1] in (' ','\t'):
            if last is None:
                raise ValueError('Unexpected control continuation')
            fields[last]+='\n'+line
        else:
            key,separator,value=line.partition(':')
            if not separator or not re.fullmatch('[A-Za-z][A-Za-z0-9-]*',key) or key in fields:
                raise ValueError('Invalid or duplicate IPK control field')
            fields[key]=value.lstrip()
            last=key
    if not re.fullmatch('[a-z0-9][a-z0-9+.-]*',fields.get('Package','')):
        raise ValueError('Unexpected package name')
    if not re.fullmatch(r'[^\s/]+',fields.get('Version','')) or fields.get('Architecture') not in ARCHES:
        raise ValueError('Unexpected package version or architecture')
    if any(key in fields for key in ('Filename','Size','MD5Sum','SHA256sum')):
        raise ValueError('Index-only fields must not be present in a control file')
    return fields,text


def image_manifest(path):
    rows=set()
    names=set()
    for line in Path(path).read_text().splitlines():
        if len(line.split())!=3:
            raise ValueError('Expected package, architecture and version in the image manifest')
        name,arch,version=line.split()
        if arch not in ARCHES or name in names:
            raise ValueError('Unexpected architecture or duplicate image package')
        names.add(name)
        rows.add((name,arch,version))
    enigma=[row for row in rows if row[0]=='enigma2']
    if len(enigma)!=1 or enigma[0][1]!='vuduo' or 'magicbox2.0.0' not in enigma[0][2]:
        raise ValueError('A native Magic Box Enigma2 image manifest is required')
    if not {'magicbox-config','magicbox-bootlogo'}<=names or 'enigma2-plugin-extensions-magicbox' in names:
        raise ValueError('The image must use native configuration/bootlogo and have no legacy launcher plugin')
    return rows


def catalog_languages(path):
    """Reject foreign catalogs in the actual runtime IPK, not just the image.

    Image postprocessing alone cannot prevent an unfiltered update from
    restoring a plugin's other languages. No package paths are extracted.
    """
    control(path)
    raw=None
    with Path(path).open('rb') as source:
        source.seek(8)
        while header:=source.read(60):
            name=header[:16].decode('ascii').strip().rstrip('/')
            size=int(header[48:58])
            start=source.tell()
            if name.startswith('data.tar.') or name=='data.tar':
                if raw is not None or size>128*1024*1024:
                    raise ValueError('Ambiguous or oversized IPK data archive')
                raw=source.read(size)
            source.seek(start+size+(size%2))
    if raw is None:
        raise ValueError('IPK has no data archive')
    languages=set()
    total=0
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r|*') as archive:
        for index,entry in enumerate(archive,1):
            total+=entry.size
            if index>100000 or not 0<=entry.size<=256*1024*1024 or total>1024*1024*1024:
                raise ValueError('IPK data content exceeds inspection limits')
            parts=PurePosixPath(entry.name).parts
            if 'LC_MESSAGES' not in parts:
                continue
            position=parts.index('LC_MESSAGES')
            if position==0:
                raise ValueError('IPK has an ambiguous catalog path')
            language=parts[position-1]
            # glibc's C/POSIX/fake category data is a system baseline,
            # not an additional selectable UI language.
            if (parts[:3]==('usr','lib','locale') and
                    language in ('C','C.utf8','C.UTF-8','POSIX','fake')):
                continue
            if language.lower().split('.')[0].replace('-','_').split('_')[0] not in ('en','tr'):
                raise ValueError('Unrequested translation catalog in IPK: '+Path(path).name)
            languages.add(language)
    return sorted(languages)


def prepare(deploy,manifest_path,image_report_path,output):
    required=image_manifest(manifest_path)
    image=json.loads(Path(image_report_path).read_text())
    if image.get('machine')!='vuduo' or not re.fullmatch('[0-9a-f]{64}',image.get('sha256','')):
        raise ValueError('A verified original-Duo image report is required')
    selected={}
    deploy=Path(deploy).resolve()
    for arch in ARCHES:
        folder=deploy/arch
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError('Missing expected package deployment directory')
        for path in sorted(folder.glob('*.ipk')):
            fields,text=control(path)
            identity=tuple(fields[key] for key in ('Package','Architecture','Version'))
            if identity not in required:
                continue
            if identity in selected or fields['Architecture']!=arch:
                raise ValueError('Ambiguous package build or misplaced package architecture')
            if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._+%:~=-]*[.]ipk',path.name):
                raise ValueError('Unsafe package deployment filename')
            selected[identity]=(path,fields,text,catalog_languages(path))
    missing=required-set(selected)
    if missing:
        raise ValueError('Missing exact image packages: '+', '.join(sorted(name for name,_,_ in missing)))
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    packages=[]
    for arch in ARCHES:
        folder=output/arch
        folder.mkdir()
        entries=[]
        for identity,(path,fields,text,languages) in sorted(selected.items()):
            if fields['Architecture']!=arch:
                continue
            before=hashes(path)
            destination=folder/path.name
            shutil.copyfile(path,destination)
            after=hashes(destination)
            if before!=after:
                raise ValueError('Package changed during feed collection')
            entries.append(text+'Filename: '+path.name+'\nSize: '+str(after['bytes'])+'\nMD5Sum: '+after['md5']+'\nSHA256sum: '+after['sha256']+'\n\n')
            packages.append({'package':identity[0],'architecture':identity[1],'version':identity[2],
                             'file':arch+'/'+path.name,'bytes':after['bytes'],'sha256':after['sha256'],
                             'catalog_languages':languages})
        index=''.join(entries).encode('utf-8')
        (folder/'Packages').write_bytes(index)
        (folder/'Packages.gz').write_bytes(gzip.compress(index,mtime=0))
    result={'version':'2.0.0','family':'magicbox-2','machine':'vuduo','image_sha256':image['sha256'],
            'created_at':datetime.now(timezone.utc).isoformat(),'published':False,'receiver_boot_verified':False,
            'image_manifest_sha256':hashes(Path(manifest_path))['sha256'],'packages':packages,
            'allowed_ui_languages':['en','tr'],'package_catalog_language_policy_checked':True}
    (output/'release.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'prepared':str(output),'packages':len(packages),'published':False,'image_sha256':image['sha256']}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deploy-ipk',type=Path,required=True)
    parser.add_argument('--image-manifest',type=Path,required=True)
    parser.add_argument('--image-report',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    prepare(args.deploy_ipk,args.image_manifest,args.image_report,args.output)
