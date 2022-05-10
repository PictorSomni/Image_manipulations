# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################

import os
import sys
import re
from PIL import Image, ImageOps
import numpy as np

#############################################################
#                           PATH                            #
#############################################################

PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################

EXTENSION = (".jpg", ".jpeg", ".png")
FOLDER = [file for file in sorted(os.listdir()) if file.lower().endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)
size = re.search(r"Warhol_(\d+)\s?x\s?(\d+)s?x\s?(\d+)s?x\s?(\d+).py",sys.argv[0]) # width x height x treshold

#############################################################
#                         VARIABLES                         #
#############################################################

WIDTH = int(size.group(1))
HEIGHT = int(size.group(2))
DPI = 300       # DPI
TRESHOLD = int(size.group(3))
DISTANCE = int(size.group(4))
COLOR_SET = [ 
    {
        'bg' : (255,255,0,255),
        'fg' : (50,9,125,255),
        'skin': (118,192,0,255)
    },
    {
        'bg' : (0,122,240,255),
        'fg' : (255,0,112,255),
        'skin': (255,255,0,255)
    },
    {
        'bg' : (50,0,130,255),
        'fg' : (255,0,0,255),
        'skin': (243,145,192,255)
    },
    {
        'bg' : (255,126,0,255),
        'fg' : (134,48,149,255),
        'skin': (111,185,248,255)
    },
    {
        'bg' : (255,0,0,255),
        'fg' : (35,35,35,255),
        'skin': (255,255,255,255)
    },
    {
        'bg' : (122,192,0,255),
        'fg' : (255,89,0,255),
        'skin': (250,255,160,255)
    },
    {
        'bg' : (0,114,100,255),
        'fg' : (252,0,116,255),
        'skin': (250,250,230,255)
    },
    {
        'bg' : (250,255,0,255),
        'fg' : (254,0,0,255),
        'skin': (139,198,46,255)
    },
    {
        'bg' : (253,0,118,255),
        'fg' : (51,2,126,255),
        'skin': (255,105,0,255)
    }
]

#############################################################
#               CONVERT MM 300DPI TO PIXELS                 #
#############################################################

WIDTH_DPI = round((float(WIDTH) / 25.4) * DPI)
HEIGHT_DPI = round((float(HEIGHT) / 25.4) * DPI)

#############################################################
#                         FUNCTIONS                         #
#############################################################

## Clears the terminal
def clear():
    os.system("cls" if os.name == "nt" else "clear")


## Creates folder if it doesn't exists
def folder(folder):
    if not os.path.exists(folder):
        os.makedirs(folder)


def darken_bg(image, color):
    '''composite image on top of a single-color image, effectively turning all
    transparent parts to that color'''
    color_layer = Image.new('RGBA', image.size, color) 
    masked_image = Image.composite(image, color_layer, image)
    return masked_image


def color_bg_fg(image, bg_color, fg_color):
    '''change transparent background to bg_color and change
    everything non-transparent to fg_color'''
    fg_layer = Image.new('RGBA', image.size, fg_color)
    bg_layer = Image.new('RGBA', image.size, bg_color) 
    masked_image = Image.composite(fg_layer, bg_layer, image)
    return masked_image


def white_to_color(image, color):
    '''change all colors close to white and non-transparent
    (alpha > 0) to be color.'''
    arr=np.array(np.asarray(image))
    r,g,b,a=np.rollaxis(arr,axis=-1)    
    mask=((r>TRESHOLD)
        & (g>TRESHOLD)
        & (b>TRESHOLD)
        & (np.abs(r-g)<DISTANCE)
        & (np.abs(r-b)<DISTANCE)
        & (np.abs(g-b)<DISTANCE)
        & (a>0)
        )
    arr[mask]=color
    image=Image.fromarray(arr,mode='RGBA')
    return image


def make_warhol_single(image, bg_color, fg_color, skin_color):
    '''create a single warhol-serigraph-style image'''
    bg_fg_layer = color_bg_fg(image, bg_color, fg_color)
    temp_dark_image = darken_bg(image, (0,0,0,255))
    skin_mask = white_to_color(temp_dark_image,(0,0,0,0))
    skin_layer = Image.new('RGBA', image.size, skin_color) 
    out = Image.composite(bg_fg_layer, skin_layer, skin_mask)
    return out


def warholify(image_file):
    try:
        base_image = Image.open(image_file).convert('RGBA')
    except Exception:
        pass
    else:
        cropped_image = ImageOps.fit(base_image, (round(WIDTH_DPI / 3), round(HEIGHT_DPI / 3)))
        warhols = []
        x, y = cropped_image.size
        for colors in COLOR_SET:
            bg = colors['bg']
            fg = colors['fg']
            skin = colors['skin']
            warhols.append(make_warhol_single(cropped_image, bg, fg, skin))

        blank_image = Image.new("RGB", (x*3, y*3))
        blank_image.paste(warhols[0], (0,0))
        blank_image.paste(warhols[1], (x,0))
        blank_image.paste(warhols[2], (x*2,0))
        blank_image.paste(warhols[3], (0,y))
        blank_image.paste(warhols[4], (x,y))
        blank_image.paste(warhols[5], (x*2,y))
        blank_image.paste(warhols[6], (0,y*2))
        blank_image.paste(warhols[7], (x,y*2))
        blank_image.paste(warhols[8], (x*2,y*2))

        folder(f"{PATH}\\Warhol")
        blank_image.save(f"{PATH}\\Warhol\\Warhol_{image_file}_{TRESHOLD}_{DISTANCE}.jpg", format='JPEG', subsampling=0, quality=100)


#############################################################
#                           MAIN                            #
#############################################################

clear()
print("Warhol")
print("#" * 30)

for index, file in enumerate(FOLDER) :
    print("image {}".format(index + 1))
    print("-" * 13)
    warholify(file)

print("Terminé !")
