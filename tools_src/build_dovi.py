"""Rebuild the small libdovi JNI library; runtime playback requires no Rust/NDK."""
from pathlib import Path
import argparse, hashlib, json, os, platform, shutil, subprocess

ROOT = Path(__file__).resolve().parent.parent
CRATE = ROOT/'android/native/dolbyvision'
TARGETS = {'arm64-v8a':('aarch64-linux-android','aarch64-linux-android26'),
           'armeabi-v7a':('armv7-linux-androideabi','armv7a-linux-androideabi26'),
           'x86_64':('x86_64-linux-android','x86_64-linux-android26')}

def collect_licenses(cargo, env, ndk):
    metadata=json.loads(subprocess.check_output([cargo,'+1.91.0','metadata','--locked','--format-version','1',
        '--manifest-path',str(CRATE/'Cargo.toml')],env=env,text=True))
    sections=['Native Dolby Vision metadata support\n\nOriginal DualTheater JNI bridge (MIT), libdovi/dolby_vision 3.4.0 (MIT), '
        'Rust dependencies and compiler/runtime notices. Kodi is a behavioral reference; no Kodi GPL code is bundled.\n']
    sections.append((CRATE/'LICENSE').read_text(encoding='utf-8')+'\n')
    for package in sorted(metadata['packages'],key=lambda x:x['name']):
        if not package.get('source'): continue
        root=Path(package['manifest_path']).parent
        files=sorted({f for pattern in ('LICENSE*','COPYING*','COPYRIGHT*','UNLICENSE*') for f in root.glob(pattern) if f.is_file()})
        if (root/'LICENSES').is_dir(): files.extend(sorted(f for f in (root/'LICENSES').rglob('*') if f.is_file()))
        if not files: files=sorted((CRATE/'license-overrides'/package['name']).glob('LICENSE*'))
        if not files: raise RuntimeError('Review missing license text: '+package['name'])
        sections.append('\n=== '+package['name']+' '+package['version']+' ('+str(package.get('license'))+') ===\n')
        for path in files: sections.append(path.name+'\n'+path.read_text(encoding='utf-8',errors='replace')+'\n')
    rustc=shutil.which('rustc')
    sysroot=Path(subprocess.check_output([rustc,'+1.91.0','--print','sysroot'],env=env,text=True).strip())
    rust_docs=sysroot/'share/doc/rust'
    for path in [rust_docs/'COPYRIGHT-library.html',*sorted((rust_docs/'licenses').glob('*.txt'))]:
        sections.append('\n=== Rust runtime notice: '+path.name+' ===\n'+path.read_text(encoding='utf-8')+'\n')
    for name in ('NOTICE','NOTICE.toolchain'):
        path=ndk/name
        sections.append('\n=== Android NDK notice: '+name+' ===\n'+path.read_text(encoding='utf-8')+'\n')
    path=ROOT/'android/app/src/main/assets/licenses/dolby-vision-native.txt'
    path.parent.mkdir(parents=True,exist_ok=True)
    text='\n'.join(line.rstrip().expandtabs(8) for line in ''.join(sections).splitlines()).rstrip()+'\n'
    path.write_text(text,encoding='utf-8',newline='\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ndk', default=os.environ.get('ANDROID_NDK_HOME'))
    p.add_argument('--host-only', action='store_true')
    args=p.parse_args()
    cargo=shutil.which('cargo')
    if not cargo: p.error('Rust 1.91.0 is required; add cargo to PATH')
    env=os.environ.copy()
    # Rust panic/source locations must not disclose a builder's private paths.
    flags=['--remap-path-prefix='+str(ROOT)+'=/src/dualtheater']
    for variable,label in (('CARGO_HOME','cargo'),('RUSTUP_HOME','rustup'),('CARGO_TARGET_DIR','target')):
        fallback = CRATE/'target' if variable=='CARGO_TARGET_DIR' else Path.home()/('.cargo' if variable=='CARGO_HOME' else '.rustup')
        flags.append('--remap-path-prefix='+str(Path(env.get(variable, fallback)).resolve())+'=/'+label)
    env['CARGO_ENCODED_RUSTFLAGS']='\x1f'.join(flags)
    env['DUALTHEATER_DOVI_FIXTURES']=str(ROOT/'android/app/src/test/resources/dovi')
    base=[cargo,'+1.91.0']
    def run(*values, environment=env):
        subprocess.run(base+list(values)+['--locked','--manifest-path',str(CRATE/'Cargo.toml')],
                       check=True, env=environment)
    run('test')
    run('build','--release') # Host JNI tests use the same implementation.
    if args.host_only: return
    if not args.ndk: p.error('Specify --ndk with Android NDK r27c (27.2.12479018)')
    ndk=Path(args.ndk).resolve()
    if '27.2.12479018' not in (ndk/'source.properties').read_text(): p.error('Expected NDK r27c')
    host='windows-x86_64' if os.name=='nt' else 'darwin-x86_64' if platform.system()=='Darwin' else 'linux-x86_64'
    tools=ndk/'toolchains/llvm/prebuilt'/host/'bin'
    target_root=Path(env.get('CARGO_TARGET_DIR',CRATE/'target'))
    binaries={}
    for abi,(target,driver) in TARGETS.items():
        settings=env.copy()
        linker=tools/(driver+'-clang'+('.cmd' if os.name=='nt' else ''))
        settings['CARGO_TARGET_'+target.upper().replace('-','_')+'_LINKER']=str(linker)
        settings['CARGO_ENCODED_RUSTFLAGS']='\x1f'.join(flags+['-C','link-arg=-Wl,-z,max-page-size=16384'])
        run('build','--release','--target',target,environment=settings)
        dest=ROOT/'android/app/src/main/jniLibs'/abi/'libdualtheater_dovi.so'
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(target_root/target/'release/libdualtheater_dovi.so',dest)
        binaries[abi]=hashlib.sha256(dest.read_bytes()).hexdigest()
    info={'bridge':'dualtheater-dovi 0.1.0','libdovi':'dolby_vision 3.4.0','rust':'1.91.0',
          'ndk':'27.2.12479018','min_api':26,'elf_page_size':16384,
          'cargo_lock_sha256':hashlib.sha256((CRATE/'Cargo.lock').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
          'native_source_sha256':hashlib.sha256((CRATE/'src/lib.rs').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
          'libraries_sha256':binaries}
    collect_licenses(cargo, env, ndk)
    info['notices_sha256']=hashlib.sha256((ROOT/'android/app/src/main/assets/licenses/dolby-vision-native.txt').read_bytes()).hexdigest()
    (CRATE/'provenance.json').write_text(json.dumps(info,indent=2)+'\n',encoding='utf-8')
    print('Built and pinned three Android ABI libraries; host Rust tests passed; notices collected.')

if __name__=='__main__': main()
