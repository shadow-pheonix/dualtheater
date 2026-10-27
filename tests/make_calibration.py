"""Generate an original SDR/TrueHD test clip with an external FFmpeg executable.

Not an HDR or Atmos sample. A white frame and 40 ms tone begin every 2 seconds.
No FFmpeg dependency is needed for normal playback.
"""
import argparse
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ffmpeg', required=True)
parser.add_argument('--output', default='calibration-SDR-TrueHD-no-Atmos.mkv')
args = parser.parse_args()
tone = 'if(lt(mod(t,2),0.04),0.15*sin(2*PI*1000*t),0)'
subprocess.run([args.ffmpeg, '-hide_banner', '-y', '-f', 'lavfi', '-i',
                'color=c=black:s=1280x720:r=24:d=20', '-f', 'lavfi', '-i',
                "aevalsrc='" + tone + "':s=48000:d=20", '-vf',
                "drawbox=color=white:t=fill:enable='lt(mod(n,48),1)'",
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-c:a', 'truehd', '-strict', '-2', '-ac', '2', '-t', '20',
                '-metadata', 'title=DualTheater flash/beep - SDR TrueHD stereo - NO ATMOS',
                '-metadata:s:a:0', 'title=TrueHD stereo calibration - no Atmos',
                str(Path(args.output))], check=True)
