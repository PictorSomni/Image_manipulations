# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################

import os
import sys
import numpy as np
import cv2
from PIL import Image, ImageEnhance
from skimage import exposure

#############################################################
#                           PATH                            #
#############################################################

PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################

EXTENSION = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
FOLDER = [file for file in sorted(os.listdir()) if file.endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)
COLOR = 1.15

#############################################################
#                           MAIN                            #
#############################################################

for i, file in enumerate(FOLDER) :
    os.system('cls' if os.name == 'nt' else 'clear')
    print("Normalisation des images")
    print("#" * 30)
    print("Image {} sur {}".format(i+1, TOTAL))
    
    if file.lower() == "watermark.pgn" :
        pass

    try :
        img = cv2.imread(file)
    except Exception :
        pass
    else :
        gamma = (1/(np.average(img)/256))**2    

        img_yuv = cv2.cvtColor(img, cv2.COLOR_BGR2YUV)
        img_yuv[:,:,0] = cv2.equalizeHist(img_yuv[:,:,0])

        img_output = cv2.cvtColor(img_yuv, cv2.COLOR_YUV2BGR)
        result = cv2.addWeighted(img, 0.5, img_output, 0.5, gamma)

        result = cv2.cvtColor(result, cv2.COLOR_BGR2RGB)
        result_image = Image.fromarray(result.astype('uint8'),'RGB')

        # enhancer = ImageEnhance.Color(result_image)
        # result_image = enhancer.enhance(COLOR)
    
        result_image.save('OK_{}'.format(file), format='JPEG', subsampling=0, quality=100)

        # cv2.waitKey(0)

print("Terminé !")