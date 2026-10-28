from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import queue
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from host.player_download import DownloadCancelled, PlayerPackage, install_player, managed_player
from host.desktop_support import DesktopService, find_mpv


def exe(machine=0x8664):
    data=bytearray(256)
    data[:2]=b'MZ'
    struct.pack_into('<I',data,0x3c,0x80)
    data[0x80:0x84]=b'PE\0\0'
    struct.pack_into('<H',data,0x84,machine)
    return bytes(data)


def package(files=None):
    inner=io.BytesIO()
    with zipfile.ZipFile(inner,'w') as archive:
        for name,data in (files or {'mpv.exe':exe(),'avcodec.dll':b'test dependency'}).items():
            archive.writestr(name,data)
    outer=io.BytesIO()
    with zipfile.ZipFile(outer,'w') as archive:
        archive.writestr('payload.zip',inner.getvalue())
    data=outer.getvalue()
    spec=PlayerPackage(url='https://github.com/mpv-player/mpv/releases/download/test/test.zip',
                       sha256=hashlib.sha256(data).hexdigest(),size=len(data),key='test-player',inner_archive='payload.zip')
    return spec,data


class Response(io.BytesIO):
    def geturl(self):
        return 'https://release-assets.githubusercontent.com/test.zip'


class PlayerDownloadTests(unittest.TestCase):
    def test_verified_nested_zip_installs_dlls_and_reuses_offline(self):
        spec,data=package()
        with tempfile.TemporaryDirectory() as directory:
            player=install_player(directory,package=spec,opener=lambda *a,**k:Response(data),probe=lambda p:'mpv test')
            self.assertEqual(Path(player).read_bytes(),exe())
            self.assertTrue(Path(player).with_name('avcodec.dll').is_file())
            self.assertEqual(managed_player(directory,spec),player)
            def no_network(*args,**kwargs):
                self.fail('A verified player must be reusable offline')
            self.assertEqual(install_player(directory,package=spec,opener=no_network),player)
            receipt=json.loads(Path(player).with_name('installation.json').read_text())
            self.assertEqual(receipt['source'],spec.url)
            self.assertNotIn(directory,json.dumps(receipt))

    def test_bad_checksum_preserves_previous_working_player(self):
        spec,data=package()
        with tempfile.TemporaryDirectory() as directory:
            player=install_player(directory,package=spec,opener=lambda *a,**k:Response(data),probe=lambda p:'mpv test')
            bad=replace(spec,key='another-build',sha256='0'*64)
            with self.assertRaisesRegex(RuntimeError,'checksum'):
                install_player(directory,package=bad,opener=lambda *a,**k:Response(data))
            self.assertEqual(managed_player(directory,spec),player)
            self.assertFalse((Path(directory)/'players/another-build').exists())

    def test_cancel_during_download_does_not_install(self):
        spec,data=package({'mpv.exe':exe(),'large.dll':b'x'*(2*1024*1024)})
        cancel=threading.Event()
        def progress(message):
            if message.startswith('Downloading mpv:'):
                cancel.set()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DownloadCancelled):
                install_player(directory,cancel=cancel,progress=progress,package=spec,opener=lambda *a,**k:Response(data))
            self.assertFalse((Path(directory)/'players'/spec.key).exists())
            self.assertEqual(list((Path(directory)/'players').iterdir()),[])

    def test_archive_traversal_is_rejected_before_player_execution(self):
        spec,data=package({'../outside.txt':b'unsafe','mpv.exe':exe()})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError,'Unsafe file path'):
                install_player(directory,package=spec,opener=lambda *a,**k:Response(data),probe=lambda p:self.fail('Must not execute unsafe extraction'))
            self.assertFalse((Path(directory)/'players'/spec.key).exists())
            self.assertFalse((Path(directory)/'players/outside.txt').exists())

    def test_wrong_architecture_is_not_executed(self):
        spec,data=package({'mpv.exe':exe(0x14c)})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError,'not Windows x64'):
                install_player(directory,package=spec,opener=lambda *a,**k:Response(data),probe=lambda p:self.fail('Must not execute wrong architecture'))

    def test_corrupted_cached_dll_is_preserved_and_repaired(self):
        spec,data=package()
        with tempfile.TemporaryDirectory() as directory:
            player=install_player(directory,package=spec,opener=lambda *a,**k:Response(data),probe=lambda p:'mpv test')
            Path(player).with_name('avcodec.dll').write_bytes(b'corrupted')
            self.assertEqual(managed_player(directory,spec),'')
            restored=install_player(directory,package=spec,opener=lambda *a,**k:Response(data),probe=lambda p:'mpv test')
            self.assertEqual(managed_player(directory,spec),restored)
            self.assertEqual(len(list((Path(directory)/'players').glob(spec.key+'.previous-*'))),1)

    def test_network_failure_and_unapproved_redirect_do_not_install(self):
        spec,data=package()
        with tempfile.TemporaryDirectory() as directory:
            def offline(*args,**kwargs):
                raise OSError('offline')
            with self.assertRaisesRegex(OSError,'offline'):
                install_player(directory,package=spec,opener=offline)
            class BadResponse(Response):
                def geturl(self): return 'http://unexpected.example/test.zip'
            with self.assertRaisesRegex(RuntimeError,'approved HTTPS'):
                install_player(directory,package=spec,opener=lambda *a,**k:BadResponse(data))
            self.assertFalse((Path(directory)/'players'/spec.key).exists())

    def test_invalid_receipt_and_package_path_are_not_trusted(self):
        spec,_=package()
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'players'/spec.key
            target.mkdir(parents=True)
            (target/'installation.json').write_text(json.dumps({'archive_sha256':spec.sha256,'files':['invalid']}))
            self.assertEqual(managed_player(directory,spec),'')
            with self.assertRaises(ValueError):
                managed_player(directory,replace(spec,key='../escape'))

    def test_autodetection_checks_saved_managed_player_and_keeps_manual_override(self):
        with tempfile.TemporaryDirectory() as directory:
            profile=Path(directory)/'profile'
            managed=profile/'players/pinned/mpv.exe'
            managed.parent.mkdir(parents=True)
            managed.touch()
            manual=Path(directory)/'mpv.exe'
            manual.touch()
            with patch('host.desktop_support.managed_player',return_value=''), patch('host.desktop_support.shutil.which',return_value=None):
                self.assertEqual(find_mpv(str(managed),Path(directory)/'empty',profile),'')
                self.assertEqual(find_mpv(str(manual),data_dir=profile),str(manual))
            with patch('host.desktop_support.managed_player',return_value=str(managed)):
                self.assertEqual(find_mpv(data_dir=profile),str(managed))

    def test_desktop_worker_reports_ready_and_remains_usable_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('host.desktop_support.install_player',side_effect=[OSError('offline'),'test-mpv.exe']):
                service=DesktopService(directory)
                try:
                    for expected in ('error','mpv_ready'):
                        service.submit('download_mpv')
                        events=[]
                        while True:
                            event=service.events.get(timeout=5)
                            events.append(event)
                            if event==('busy',False): break
                        self.assertIn(expected,[kind for kind,value in events])
                finally:
                    service.submit('close')
                    self.assertTrue(service.closed.wait(5))

    def test_desktop_close_cancels_download_before_shutdown(self):
        started=threading.Event()
        def blocked_download(directory,cancel,progress):
            started.set()
            if not cancel.wait(5):
                raise TimeoutError('Close did not cancel the download')
            raise DownloadCancelled('cancelled')
        with tempfile.TemporaryDirectory() as directory:
            with patch('host.desktop_support.install_player',side_effect=blocked_download):
                service=DesktopService(directory)
                try:
                    service.submit('download_mpv')
                    self.assertTrue(started.wait(5))
                    service.submit('close')
                    self.assertTrue(service.closed.wait(5))
                    events=[]
                    while True:
                        try: events.append(service.events.get_nowait())
                        except queue.Empty: break
                    self.assertNotIn('mpv_ready',[kind for kind,value in events])
                finally:
                    if not service.closed.is_set():
                        service.submit('close')
                        service.closed.wait(5)


if __name__=='__main__':
    unittest.main()
