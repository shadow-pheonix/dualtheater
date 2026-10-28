"""Generate the original phone-v1 fixture; FFmpeg is a build-only tool.

Irregular intervals distinguish missed events from a whole-period pairing error.
Both source onsets are on the same 24 fps/48 kHz timeline (2000 samples/frame).
"""
import argparse
from pathlib import Path
import subprocess

FRAMES = (48, 115, 194, 252, 341, 422)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', required=True)
    parser.add_argument('--output', default='calibration-phone-SDR-TrueHD.mkv')
    args = parser.parse_args()
    gate = '+'.join(f'between(n,{frame * 2000},{frame * 2000 + 1919})' for frame in FRAMES)
    flash = '+'.join(f'eq(n,{frame})' for frame in FRAMES)
    subprocess.run([args.ffmpeg, '-hide_banner', '-y', '-f', 'lavfi', '-i',
        'color=c=black:s=1280x720:r=24:d=22', '-f', 'lavfi', '-i',
        f"aevalsrc='if({gate},0.15*sin(2*PI*1000*n/48000),0)':s=48000:d=22",
        '-vf', f"drawbox=color=white:t=fill:enable='{flash}'", '-c:v', 'libx264',
        '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'truehd',
        '-strict', '-2', '-ac', '2', '-t', '22', '-metadata',
        'title=DualTheater phone-v1 - original SDR TrueHD stereo - NO ATMOS',
        str(Path(args.output))], check=True)


if __name__ == '__main__':
    main()
