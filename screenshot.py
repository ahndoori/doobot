import platform
import numpy as np
import cv2
import os
from PIL import Image, ImageGrab

PATH_VISION = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision")

def screen_image():
    img = ImageGrab.grab()
    if platform.system() == "Darwin":
        width, height = img.size
        img = img.resize(
            (width // 2, height // 2), resample=Image.Resampling.LANCZOS
        )
    return img

def screen_array():
    return np.array(screen_image())

def screen_gray():
    return cv2.cvtColor(screen_array(), cv2.COLOR_RGB2GRAY)

def match_gray_image(image, confidence_level=0.7):
    path_image = os.path.join(PATH_VISION, image)
    gray_screen = screen_gray()
    template = cv2.imread(path_image, cv2.IMREAD_GRAYSCALE)
    if template is None:
        return False
    h, w = template.shape[:2]
    res = cv2.matchTemplate(gray_screen, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
    print(path_image,max_loc,max_val,confidence_level)
    if max_val >= confidence_level:
        cx = int(max_loc[0] + w / 2)
        cy = int(max_loc[1] + h / 2)
        return (cx, cy)
    return False

def match_gray_image_all(image, confidence_level=0.7):
    path_image = os.path.join(PATH_VISION, image)
    gray_screen = screen_gray()
    template = cv2.imread(path_image, cv2.IMREAD_GRAYSCALE)
    if template is None: return []
    h, w = template.shape[:2]
    res = cv2.matchTemplate(gray_screen, template, cv2.TM_CCOEFF_NORMED)
    loc = np.where(res >= confidence_level)
    points = list(zip(*loc[::-1]))
    if not points:
        return []
    filtered_points = []
    for pt in points:
        cx = int(pt[0] + w / 2)
        cy = int(pt[1] + h / 2)
        if any(abs(cx - fx) < w and abs(cy - fy) < h for fx, fy in filtered_points):
            continue
        filtered_points.append((cx, cy))
    return filtered_points