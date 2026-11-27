#!/usr/bin/env python3
"""Put two screenshots of the same screen side by side: original on the left, layer on the right.

usage: python3 before_after.py before.jpg after.jpg out.png --left "Before: original" --right "After: GAI layer"
"""
import argparse, glob
from PIL import Image, ImageDraw, ImageFont

ap = argparse.ArgumentParser()
ap.add_argument('before'); ap.add_argument('after'); ap.add_argument('out')
ap.add_argument('--left', default='Before'); ap.add_argument('--right', default='After')
a = ap.parse_args()
fonts = glob.glob('/usr/share/fonts/**/NotoSansCJK-Bold.ttc', recursive=True) + glob.glob('/usr/share/fonts/**/*Bold*.ttf', recursive=True)
font = ImageFont.truetype(fonts[0], 30) if fonts else ImageFont.load_default()
b, c = Image.open(a.before).convert('RGB'), Image.open(a.after).convert('RGB')
gap, top = 24, 64
W, H = b.width + c.width + gap, max(b.height, c.height) + top
im = Image.new('RGB', (W, H), '#FFFFFF'); d = ImageDraw.Draw(im)
d.rectangle([0, 0, b.width, top - 8], fill='#4B5563'); d.text((16, 8), a.left, font=font, fill='#FFFFFF')
d.rectangle([b.width + gap, 0, W, top - 8], fill='#D7263D'); d.text((b.width + gap + 16, 8), a.right, font=font, fill='#FFFFFF')
im.paste(b, (0, top)); im.paste(c, (b.width + gap, top))
d.rectangle([0, top, b.width - 1, top + b.height - 1], outline='#9CA3AF'); d.rectangle([b.width + gap, top, W - 1, top + c.height - 1], outline='#9CA3AF')
im.save(a.out, optimize=True); print('wrote', a.out, im.size)
