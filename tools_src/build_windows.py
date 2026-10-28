"""Build the x64 portable EXE on Windows. No user settings or mpv are bundled."""
import argparse
from pathlib import Path
import shutil
import re
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dist', default=str(root/'dist'))
parser.add_argument('--work', default=str(root/'build/windows'))
args = parser.parse_args()
if sys.platform != 'win32':
    raise SystemExit('Build the Windows EXE on Windows with Python 3.11 x64.')
work = Path(args.work).resolve()
work.mkdir(parents=True,exist_ok=True)
licenses = work/'licenses'
licenses.mkdir(exist_ok=True)
python_root = Path(sys.base_prefix)
python_license = python_root/'LICENSE.txt'
tk_license = python_root/'tcl/tk8.6/license.terms'
for source, name in ((python_license,'Python-LICENSE.txt'),(tk_license,'Tk-license.terms')):
    if not source.is_file():
        raise SystemExit('Missing runtime license: '+name)
    shutil.copyfile(source,licenses/name)
# The Tcl distribution license is kept alongside the source repo's upstream notices.
shutil.copyfile(root/'docs/licenses/Tcl-license.terms', licenses/'Tcl-license.terms')
command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed',
         '--name','DualTheater','--noupx','--paths',str(root),'--distpath',str(Path(args.dist).resolve()),
         '--workpath',str(work/'pyinstaller'),'--specpath',str(work),
         '--icon',str(root/'assets/dualtheater.ico')]
version = re.search(r"VERSION = '([^']+)'", (root/'host/desktop_support.py').read_text(encoding='utf-8'))[1]
android_version = re.search(r"versionName '([^']+)'", (root/'android/app/build.gradle').read_text(encoding='utf-8'))[1]
if version != android_version:
    raise SystemExit('Windows and Android beta versions must match.')
numbers = tuple(map(int, re.match(r'(\d+)\.(\d+)\.(\d+)-beta\.(\d+)',version).groups()))
metadata = work/'version_info.txt'
metadata.write_text(f'''VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers!r}, prodvers={numbers!r}, mask=0x3f, flags=0x2,
                   OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('FileDescription', 'DualTheater experimental home theater player'),
    StringStruct('ProductName', 'DualTheater'), StringStruct('FileVersion', '{version}'),
    StringStruct('ProductVersion', '{version}'), StringStruct('OriginalFilename', 'DualTheater.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
''',encoding='utf-8')
command += ['--version-file',str(metadata)]
for source, destination in ((root/'host/controller.html','host'),(root/'host/select_audio.lua','host'),
                            (root/'assets/dualtheater.ico','assets'),(root/'assets/dualtheater.png','assets'),
                            (root/'THIRD_PARTY_NOTICES.md','.'),(licenses,'licenses')):
    command += ['--add-data',str(source)+';'+destination]
command.append(str(root/'desktop_main.py'))
subprocess.run(command,cwd=root,check=True)
print('Built portable DualTheater.exe. Python/Tk are included; use Download mpv or Browse on Connect.')
