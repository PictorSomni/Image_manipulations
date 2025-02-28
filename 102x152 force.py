# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
import re
import math
from PIL import Image, ImageOps, ImageFile

DPI = 300
BORDER = 5

WIDTH_DPI = 0
HEIGHT_DPI = 0
BORDER_DPI = 0

ROTATED = False

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True

features = re.search(r"(\d+)\s?x\s?(\d+)\s?([\w\s]+)?.py", sys.argv[0]) # width x height  + options

try :
    OPTIONS = features.group(3)
except Exception :
    OPTIONS = ""


if int(features.group(1)) < int(features.group(2)) :
    WIDTH = int(features.group(2))
    HEIGHT = int(features.group(1))
else :
    WIDTH = int(features.group(1))
    HEIGHT = int(features.group(2))

EXTENSION = (".jpg", ".jpeg", ".png")
FOLDER = [file for file in sorted(os.listdir()) if file.lower().endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)


def correct_round(number) :
    if number  == 89 :
        number = 9
    
    elif number  == 127 :
        number = 13
    
    elif number  == 178 :
        number = 18

    else :
        number = int(number /10)

    return number


def mm_to_pixels(mm, dpi) :
    return round((float(mm) / 25.4) * dpi)


def fit_in(max_size, primary_size, secondary_size):
    primary_ratio = (max_size/float(primary_size))
    secondary_ratio = int((float(secondary_size)*float(primary_ratio)))
    return secondary_ratio

def new_dir(name) :
    if os.path.isdir(f"{PATH}\\{name}") == False :
        os.mkdir(f"{PATH}\\{name}")


WIDTH_DPI = mm_to_pixels(WIDTH, DPI)
HEIGHT_DPI = mm_to_pixels(HEIGHT, DPI)
BORDER_DPI = mm_to_pixels(BORDER, DPI) * 2
WIDTH = correct_round(WIDTH)
HEIGHT = correct_round(HEIGHT)

NAME_SIZE = f"{HEIGHT}x{WIDTH}"
NAME_SQUARE = f"{HEIGHT}x{HEIGHT}"

#############################################################
#                           MAIN                            #
#############################################################

for i, file in enumerate(FOLDER) :
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"{WIDTH} x {HEIGHT} (ou {HEIGHT} x {HEIGHT})")
    print(f"En {DPI} DPI -> {WIDTH_DPI} x {HEIGHT_DPI} pixels")
    print("#" * 32 + "\n")
    print("Image {} sur {}".format(i+1, TOTAL))


    try :
        base_image = Image.open(file)
        file = file.split(".")[0]
    except Exception :
        print(Exception)
    else :
        if base_image.width < base_image.height : # IF PORTRAIT, ROTATE 90 DEGREES
            base_image = base_image.rotate(90, expand=True)
            ROTATED = True
        else :
            ROTATED = False

        if OPTIONS :
            if "force" in features.group(3).lower() : # FORCE SIZE EVEN FOR SQUARE IMAGES
                print("FORCE SIZE")
                new_dir(NAME_SIZE)
                if "bb" in features.group(3).lower() :  # WITH BORDER
                    print("BORD BLANC")
                    result = Image.new('RGB', (WIDTH_DPI - BORDER_DPI, HEIGHT_DPI - BORDER_DPI), (255, 255, 255, 255))
                    cropped_image = ImageOps.fit(base_image, (WIDTH_DPI, HEIGHT_DPI))
                    
                    offset = (result.width - cropped_image.width) // 2, (result.height - cropped_image.height) // 2
                    result.paste(cropped_image, offset)
                    result = ImageOps.expand(result, border=BORDER_DPI // 2, fill="white")
                    result = result.convert("RGB")
                    result.save(f"{PATH}\\{NAME_SIZE}\\{NAME_SIZE}_BB_{file}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

                else :
                    result = ImageOps.fit(base_image, (WIDTH_DPI, HEIGHT_DPI))
                    result = result.convert("RGB")
                    result.save(f"{PATH}\\{NAME_SIZE}\\{NAME_SIZE}_{file}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

        if base_image.width == base_image.height :  # SQUARE IMAGE
            new_dir(NAME_SQUARE)
            if OPTIONS : # OPTIONS ?
                if "bb" in features.group(3).lower() :  # WITH BORDER
                    print("BORD BLANC")
                    result = ImageOps.fit(base_image, (HEIGHT_DPI - BORDER_DPI, HEIGHT_DPI - BORDER_DPI))
                    result = ImageOps.expand(result, border=BORDER_DPI // 2, fill="white")
                    result = result.convert("RGB")
                    result.save(f"{PATH}\\{NAME_SQUARE}\\{NAME_SQUARE}_BB_{file}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

            else : # WITHOUT OPTION           
                result = ImageOps.fit(base_image, (HEIGHT_DPI, HEIGHT_DPI))
                result = result.convert("RGB")
                result.save(f"{PATH}\\{NAME_SQUARE}\\{NAME_SQUARE}_{file}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

        else :                
            if OPTIONS:   # OPTIONS ?
                if "fit" in features.group(3).lower() : # FIT-IN
                    new_dir(NAME_SIZE)
                    print("FIT-IN")
                    if "bb" in features.group(3).lower() :  # WITH BORDER
                        print("BORD BLANC")
                        result = Image.new('RGB', (WIDTH_DPI - BORDER_DPI, HEIGHT_DPI - BORDER_DPI), (255, 255, 255, 255))
                        cropped_image = base_image.resize((WIDTH_DPI - BORDER_DPI, fit_in(WIDTH_DPI - BORDER_DPI, base_image.width, base_image.height)), Image.LANCZOS)
                        if cropped_image.height > result.height :
                            cropped_image = base_image.resize((fit_in(HEIGHT_DPI - BORDER_DPI, base_image.height, base_image.width), HEIGHT_DPI - BORDER_DPI), Image.LANCZOS)
                        
                        offset = (result.width - cropped_image.width) // 2, (result.height - cropped_image.height) // 2
                        result.paste(cropped_image, offset)
                        result = ImageOps.expand(result, border=BORDER_DPI // 2, fill="white")
                        result = result.convert("RGB")

                        if ROTATED == True :
                            result = result.rotate(270, expand=True)

                        result.save(f"{PATH}\\{NAME_SIZE}\\{NAME_SIZE}_FIT_BB_{file}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

                    else :   # WITHOUT BORDER
                        result = Image.new('RGB', (WIDTH_DPI, HEIGHT_DPI), (255, 255, 255, 255))
                        cropped_image = base_image.resize((WIDTH_DPI, fit_in(WIDTH_DPI, base_image.width, base_image.height)), Image.LANCZOS)
                        if cropped_image.height > result.height :
                            cropped_image = base_image.resize((fit_in(HEIGHT_DPI, base_image.height, base_image.width), HEIGHT_DPI), Image.LANCZOS)

                        offset = (result.width - cropped_image.width) // 2, (result.height - cropped_image.height) // 2
                        result.paste(cropped_image, offset)
                        result = result.convert("RGB")

                        if ROTATED == True :
                            result = result.rotate(270, expand=True)

                        result.save(f"{PATH}\\{NAME_SIZE}\\{NAME_SIZE}_FIT_{file}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
                
                elif "sq" in features.group(3).lower() : # FORCE SQUARE
                    new_dir(NAME_SQUARE)
                    print("SQUARE")
                    if "bb" in features.group(3).lower() :  # WITH BORDER
                        print("BORD BLANC")
                        result = Image.new('RGB', (HEIGHT_DPI - BORDER_DPI, HEIGHT_DPI - BORDER_DPI), (255, 255, 255, 255))
                        cropped_image = ImageOps.fit(base_image, (HEIGHT_DPI, HEIGHT_DPI))
                        
                        offset = (result.height - cropped_image.height) // 2, (result.height - cropped_image.height) // 2
                        result.paste(cropped_image, offset)
                        result = ImageOps.expand(result, border=BORDER_DPI // 2, fill="white")
                        result = result.convert("RGB")
                        result.save(f"{PATH}\\{NAME_SQUARE}\\{NAME_SQUARE}_BB_{file}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

                    else :
                        result = ImageOps.fit(base_image, (HEIGHT_DPI, HEIGHT_DPI))
                        result = result.convert("RGB")
                        result.save(f"{PATH}\\{NAME_SQUARE}\\{NAME_SQUARE}_SQ_{file}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

                elif "bb" in features.group(3).lower() :  # WITH BORDER
                    new_dir(NAME_SIZE)
                    print("BORD BLANC")
                    result = ImageOps.fit(base_image, (WIDTH_DPI - BORDER_DPI, HEIGHT_DPI - BORDER_DPI))
                    result = ImageOps.expand(result, border=BORDER_DPI // 2, fill="white")
                    result = result.convert("RGB")

                    if ROTATED == True :
                            result = result.rotate(270, expand=True)

                    result.save(f"{PATH}\\{NAME_SIZE}\\{NAME_SIZE}_BB_{file}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

            else :  # WITHOUT OPTION (FILL-IN)
                new_dir(NAME_SIZE)
                result = ImageOps.fit(base_image, (WIDTH_DPI, HEIGHT_DPI))
                result = result.convert("RGB")

                if ROTATED == True :
                    result = result.rotate(270, expand=True)
                            
                result.save(f"{PATH}\\{NAME_SIZE}\\{NAME_SIZE}_{file}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

print("Terminé !")
# input("Terminé !\nAppuyez sur une touche pour fermer")