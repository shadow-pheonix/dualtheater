"""User-initiated mpv download from upstream, never redistributed in our EXE."""
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import subprocess
import tempfile
import threading
import urllib.request
from urllib.parse import urlsplit
import uuid
import zipfile


@dataclass(frozen=True)
class PlayerPackage:
    url: str = 'https://github.com/mpv-player/mpv/releases/download/v0.41.0/mpv-v0.41.0-x86_64-w64-mingw32.zip'
    sha256: str = 'a49811c0752c108b8260636f9c6f6fcb97406641c98b30f1e7b500dfb20177de'
    size: int = 39002683
    key: str = 'mpv-0.41.0-x64-a49811c0'
    inner_archive: str = 'mpv-git-2025-12-21-41f6a64-x86_64.zip'


PACKAGE = PlayerPackage()
DOWNLOAD_PAGE = 'https://github.com/mpv-player/mpv/releases/tag/v0.41.0'
MAX_EXPANDED = 512 * 1024 * 1024


class DownloadCancelled(RuntimeError):
    pass


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as file:
        for block in iter(lambda:file.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def _target(directory, package):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,100}',package.key):
        raise ValueError('Invalid player package identity')
    return Path(directory).resolve()/'players'/package.key


def managed_player(directory, package=PACKAGE):
    target=_target(directory,package)
    try:
        receipt=json.loads((target/'installation.json').read_text(encoding='utf-8'))
        if receipt['archive_sha256']!=package.sha256 or not isinstance(receipt['files'],dict) or not receipt['files']:
            return ''
        if 'mpv.exe' not in receipt['files']:
            return ''
        for name,digest in receipt['files'].items():
            path=PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                return ''
            file=target.joinpath(*path.parts)
            if not file.is_file() or file.is_symlink() or sha256(file)!=digest:
                return ''
        return str(target/'mpv.exe')
    except (OSError,ValueError,KeyError,TypeError):
        return ''


def _probe_player(executable):
    result=subprocess.run([str(executable),'--no-config','--version'],stdin=subprocess.DEVNULL,
                          capture_output=True,timeout=20,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    output=(result.stdout+result.stderr).decode('utf-8',errors='replace')
    if result.returncode or not output.lower().startswith('mpv '):
        raise RuntimeError('Downloaded mpv could not start. Use Browse to select your working mpv.exe.')
    return output.splitlines()[0][:180]


def install_player(directory, cancel=None, progress=None, package=PACKAGE,
                   opener=urllib.request.urlopen, probe=_probe_player):
    cancel=cancel or threading.Event()
    progress=progress or (lambda message:None)
    def check_cancel():
        if cancel.is_set():
            raise DownloadCancelled('mpv download cancelled; your previous player was kept.')
    check_cancel()
    existing=managed_player(directory,package)
    if existing:
        progress('Downloaded mpv is ready; no network download needed.')
        return existing
    target=_target(directory,package)
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.mpv-download-',dir=target.parent) as temporary:
        temporary=Path(temporary)
        archive_path=temporary/'player.zip'
        request=urllib.request.Request(package.url,headers={'User-Agent':'DualTheater-mpv-setup'})
        progress('Connecting to the official mpv GitHub download…')
        received=last_report=0
        with opener(request,timeout=20) as response, archive_path.open('wb') as file:
            final=urlsplit(response.geturl())
            if final.scheme!='https' or not (final.hostname=='github.com' or
                                             (final.hostname or '').endswith('.githubusercontent.com')):
                raise RuntimeError('mpv download redirected outside the approved HTTPS source.')
            while True:
                check_cancel()
                block=response.read(256*1024)
                if not block:
                    break
                received+=len(block)
                if received>package.size:
                    raise RuntimeError('mpv download size did not match the pinned package.')
                file.write(block)
                if received-last_report>=1024*1024:
                    progress(f'Downloading mpv: {received/1048576:.0f} / {package.size/1048576:.0f} MB…')
                    last_report=received
        check_cancel()
        progress('Verifying the download…')
        if received!=package.size or sha256(archive_path)!=package.sha256:
            raise RuntimeError('mpv checksum verification failed. No player was installed; retry or use Browse.')
        stage=temporary/'runtime'
        stage.mkdir()
        with zipfile.ZipFile(archive_path) as outer:
            nested=outer.getinfo(package.inner_archive)
            if nested.file_size>package.size+1024*1024:
                raise RuntimeError('Unexpected nested mpv archive size.')
            payload=io.BytesIO(outer.read(nested))
        progress('Extracting mpv and its supporting DLLs…')
        with zipfile.ZipFile(payload) as archive:
            members=archive.infolist()
            if len(members)>2000 or sum(item.file_size for item in members)>MAX_EXPANDED:
                raise RuntimeError('Unexpected mpv archive contents.')
            seen=set()
            for item in members:
                check_cancel()
                name=item.filename.replace('\\','/')
                path=PurePosixPath(name)
                if (path.is_absolute() or '..' in path.parts or ':' in name or
                        stat.S_ISLNK(item.external_attr>>16) or name.casefold() in seen):
                    raise RuntimeError('Unsafe file path in mpv archive.')
                seen.add(name.casefold())
                destination=stage.joinpath(*path.parts)
                if not destination.resolve().is_relative_to(stage.resolve()):
                    raise RuntimeError('Unsafe file path in mpv archive.')
                if item.is_dir():
                    destination.mkdir(parents=True,exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    with archive.open(item) as source,destination.open('wb') as output:
                        while True:
                            check_cancel()
                            block=source.read(256*1024)
                            if not block: break
                            output.write(block)
        executable=stage/'mpv.exe'
        if not executable.is_file():
            raise RuntimeError('The mpv download did not contain mpv.exe.')
        with executable.open('rb') as file:
            if file.read(2)!=b'MZ':
                raise RuntimeError('Downloaded player is not a Windows executable.')
            file.seek(0x3c)
            offset=struct.unpack('<I',file.read(4))[0]
            file.seek(offset)
            if file.read(6)!=b'PE\0\0\x64\x86':
                raise RuntimeError('Downloaded player is not Windows x64.')
        check_cancel()
        progress('Checking that mpv starts (no audio is played)…')
        version=probe(executable)
        check_cancel()
        files={str(path.relative_to(stage)).replace('\\','/'):sha256(path)
               for path in stage.rglob('*') if path.is_file()}
        (stage/'installation.json').write_text(json.dumps({'source':package.url,
            'archive_sha256':package.sha256,'version':version,'files':files},indent=2),encoding='utf-8')
        # Preserve an incomplete/corrupt previous directory; never delete an existing player.
        if target.exists():
            target.rename(target.with_name(target.name+'.previous-'+uuid.uuid4().hex[:8]))
        stage.rename(target)
        progress('mpv is ready. Choose HDMI audio, then start the TV connection.')
        return str(target/'mpv.exe')
