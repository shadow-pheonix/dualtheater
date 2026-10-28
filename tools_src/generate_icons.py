"""Render original DualTheater vector geometry to native Android and Windows assets."""
from pathlib import Path
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / 'assets'
ASSETS.mkdir(exist_ok=True)
NAVY, TEAL, WHITE = '#101827', '#44dfcd', '#eff6ff'
# One geometry definition drives SVG, Android VectorDrawable and raster/ICO exports.
shapes = [
    ('round', (8, 8, 248, 248, 52), NAVY, None, 0),
    ('round', (100, 57, 218, 144, 14), '#163247', TEAL, 7),
    ('round', (36, 91, 186, 190, 16), NAVY, WHITE, 8),
    ('poly', (93, 115, 93, 165, 136, 140), TEAL, None, 0),
    ('line', (111, 192, 111, 208), None, WHITE, 7),
    ('line', (87, 209, 136, 209), None, WHITE, 7),
]


def vector_path(kind, points):
    if kind == 'round':
        x, y, right, bottom, radius = points
        return (f'M{x+radius},{y} H{right-radius} Q{right},{y} {right},{y+radius} '
                f'V{bottom-radius} Q{right},{bottom} {right-radius},{bottom} '
                f'H{x+radius} Q{x},{bottom} {x},{bottom-radius} '
                f'V{y+radius} Q{x},{y} {x+radius},{y} Z')
    pairs = list(zip(points[::2], points[1::2]))
    return 'M' + ' L'.join(f'{x},{y}' for x, y in pairs) + (' Z' if kind == 'poly' else '')


svg, android = [], []
for kind, points, fill, stroke, width in shapes:
    path = vector_path(kind, points)
    svg.append(f'<path d="{path}" fill="{fill or "none"}" stroke="{stroke or "none"}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"/>')
    android.append(f'<path android:pathData="{path}" android:fillColor="{fill or "#00000000"}" android:strokeColor="{stroke or "#00000000"}" android:strokeWidth="{width}" android:strokeLineJoin="round" android:strokeLineCap="round"/>')
(ASSETS/'dualtheater.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">\n'+'\n'.join(svg)+'\n</svg>\n',encoding='utf-8')
drawable = ROOT/'android/app/src/main/res/drawable/icon.xml'
drawable.write_text('<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="108dp" android:height="108dp" android:viewportWidth="256" android:viewportHeight="256">\n'+'\n'.join(android)+'\n</vector>\n',encoding='utf-8')
phone_drawable = ROOT/'android/calibration/src/main/res/drawable/icon.xml'
phone_drawable.parent.mkdir(parents=True,exist_ok=True)
phone_drawable.write_text(drawable.read_text(encoding='utf-8'),encoding='utf-8')

scale = 4
image = Image.new('RGBA',(256*scale,256*scale))
draw = ImageDraw.Draw(image)
for kind, points, fill, stroke, width in shapes:
    coordinates = tuple(n*scale for n in points)
    if kind == 'round':
        draw.rounded_rectangle(coordinates[:4], radius=coordinates[4], fill=fill, outline=stroke, width=width*scale)
    elif kind == 'poly':
        draw.polygon(list(zip(coordinates[::2],coordinates[1::2])),fill=fill)
    else:
        draw.line(coordinates,fill=stroke,width=width*scale)
        radius=width*scale/2
        for x,y in zip(coordinates[::2],coordinates[1::2]):
            draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=stroke)
icon=image.resize((256,256),Image.Resampling.LANCZOS)
icon.save(ASSETS/'dualtheater.png')
icon.save(ASSETS/'dualtheater.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])

banner=Image.new('RGB',(1280,720),NAVY)
banner.paste(icon.resize((440,440),Image.Resampling.LANCZOS),(55,140),icon.resize((440,440),Image.Resampling.LANCZOS))
font_path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/segoeuib.ttf'
font=ImageFont.truetype(str(font_path),106)
small=ImageFont.truetype(str(font_path),32)
draw=ImageDraw.Draw(banner)
draw.text((535,220),'DUAL',font=font,fill=WHITE)
draw.text((535,335),'THEATER',font=font,fill=TEAL)
draw.text((542,475),'NATIVE PICTURE. LOSSLESS SOUND.',font=small,fill='#b8c8db')
target=ROOT/'android/app/src/main/res/drawable-nodpi'
target.mkdir(exist_ok=True)
banner.resize((320,180),Image.Resampling.LANCZOS).save(target/'tv_banner.png')
banner.resize((960,540),Image.Resampling.LANCZOS).save(ASSETS/'tv-banner-preview.png')
print('Generated original matching vector, ICO, PNG and Android TV banner assets.')
