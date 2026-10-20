import os
import re
import time
import cv2
import keyboard
import pygetwindow as gw
import pytesseract
from PIL import ImageGrab

# =========================================================================
# 請確認您的 Tesseract 執行檔路徑正確
# =========================================================================
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# 全域記憶體
memory = {"life": None, "resistances": {}, "price": None}


def capture_d2r_screen(r_path="raw_screen.png"):
    print("\n[F10 Triggered] Capturing game window...")
    d2r_windows = gw.getWindowsWithTitle("Diablo II: Resurrected")
    if not d2r_windows or len(d2r_windows) == 0:
        d2r_windows = gw.getWindowsWithTitle("Diablo")
        
    if d2r_windows and len(d2r_windows) > 0:
        d2r_win = d2r_windows
        try:
            if d2r_win.left is not None and (d2r_win.right - d2r_win.left) > 100:
                d2r_win.activate()
                time.sleep(0.1)
                ImageGrab.grab(
                    bbox=(d2r_win.left, d2r_win.top, d2r_win.right, d2r_win.bottom)
                ).save(r_path)
                return r_path
        except Exception as win_err:
            print(f"[Window Mode Warning] Unable to bound window coordinates: {win_err}")

    ImageGrab.grab().save(r_path)
    return r_path


def detect_and_crop_tooltip(f_path, o_path="temp_tooltip.jpg"):
    print("Scanning for D2R tooltip frame via computer vision...")
    img = cv2.imread(f_path)
    if img is None:
        return f_path
    
    h_img, w_img = img.shape[:2]
    
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(
        thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    best_box, max_area = None, 0
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if (
            150 < w < (w_img * 0.5)
            and 150 < h < (h_img * 0.8)
        ):
            if w * h > max_area:
                max_area = w * h
                best_box = (x, y, w, h)
    if best_box:
        x, y, w, h = best_box
        p = 5
        cv2.imwrite(
            o_path,
            img[
                max(0, y - p) : min(h_img, y + h + p),
                max(0, x - p) : min(w_img, x + w + p),
            ],
            [int(cv2.IMWRITE_JPEG_QUALITY), 95],
        )
        return o_path
    return f_path


def clean_ocr_text(text):
    """【D2R 終極抗性與生命值校正】完美修復所有字體扭曲"""
    text = text.upper()

    # 1. 🔥 關鍵修正：解決毒素（Poison）在 D2R 字體中被誤判為 PEISON 或 PISON 的問題
    text = text.replace("PEISON", "POISON")
    text = text.replace("PISON", "POISON")

    # 2. 解決字母 O 被誤判成數字 0 (零) 的情況
    text = text.replace("T0 LIFE", "TO LIFE")
    text = text.replace("T0LIFE", "TO LIFE")

    # 3. 消除夾在中間的 T 雜訊
    text = text.replace("RESIST T+", "RESIST +")
    text = text.replace("RESISTANCES T+", "RESISTANCES +")

    # 4. 解決 RESIST 雙字母與黏字字體扭曲
    text = text.replace("RESISST", "RESIST ")
    text = text.replace("RESIIST", "RESIST ")
    text = text.replace("RESISTT", "RESIST ")
    
    text = text.replace("LIGHTNINGRESIST", "LIGHTNING RESIST")
    text = text.replace("FIRERESIST", "FIRE RESIST")
    text = text.replace("COLDRESIST", "COLD RESIST")
    text = text.replace("POISONRESIST", "POISON RESIST")
    text = text.replace("ALLRESISTANCES", "ALL RESISTANCES")
    text = text.replace("BEASST", "BEAST") # 順便修復這次名稱標題的雙 S 雜訊
    text = text.replace("CELP", "COLD")

    # 5. 強效補號機制
    text = re.sub(r"RESIST\s*T\s*(\d+)", r"RESIST +\1", text)
    text = re.sub(r"RESIST\s*([IL\d]+)%", r"RESIST +\1%", text)
    text = re.sub(r"RESISTANCES\s*([IL\d]+)%", r"RESISTANCES +\1%", text)

    # 6. 智慧數字 1 還原
    text = re.sub(r"\+([IL\d]+)%", lambda m: "+" + m.group(1).replace("I", "1").replace("L", "1") + "%", text)

    # 7. 生命值（LIFE）防粘字校正
    text = re.sub(r"(\d+)T\s*LIFE\b", r"\g<1> TO LIFE", text)
    text = re.sub(r"(\d+)TE\s*LIFE\b", r"\g<1>0 TO LIFE", text)
    text = re.sub(r"\bTE\s+LIFE\b", "TO LIFE", text)
    text = re.sub(r"\bT\s+LIFE\b", "TO LIFE", text)
    text = re.sub(r"(\d+)Q", r"\g<1>0", text)

    return text


def perform_ocr_and_parse(img_path):
    """載入裁切後的圖片進行本地 OCR 辨識與高容錯解析"""
    global memory

    try:
        custom_config = "--psm 6 -c tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+%"
        text = pytesseract.image_to_string(
            img_path, lang="eng", config=custom_config
        )
    except Exception as e:
        print(f"OCR Failed!\nError: {e}")
        return

    cleaned_text = clean_ocr_text(text)

    print("\n--- Cleaned OCR Text Output ---")
    print(cleaned_text.strip())
    print("----------------------------")

    found_life = None
    found_res = {}
    
    price_str = "1"

    # 1. 提取 LIFE
    life_match = re.search(r"(\+?\d+)\s*(TO)?\s*LIFE", cleaned_text)
    if life_match:
        found_life = "".join(c for c in life_match.group(1) if c.isdigit())
        memory["life"] = found_life

    # 2. 提取抗性 (RESIST)
    res_patterns = {
        "Fire Res": r"(\+?\d+%?)\s*(TO\s+)?FIRE\s*RESIST|\bFIRE\s*RESIST\s*(\+?\d+%?)",
        "Lightning Res": r"(\+?\d+%?)\s*(TO\s+)?LIGHTNING\s*RESIST|\bLIGHTNING\s*RESIST\s*(\+?\d+%?)",
        "Cold Res": r"(\+?\d+%?)\s*(TO\s+)?COLD\s*RESIST|\bCOLD\s*RESIST\s*(\+?\d+%?)",
        "Poison Res": r"(\+?\d+%?)\s*(TO\s+)?POISON\s*RESIST|\bPOISON\s*RESIST\s*(\+?\d+%?)",
        "All Res": r"(\+?\d+%?)\s*(TO\s+)?ALL\s*RESISTANCES|\bALL\s*RESISTANCES\s*(\+?\d+%?)",
    }

    for res_name, pattern in res_patterns.items():
        res_match = re.search(pattern, cleaned_text)
        if res_match:
            val = res_match.group(1) or res_match.group(3)
            clean_val = "".join(c for c in val if c.isdigit())
            if clean_val:
                clean_val += "%"
                found_res[res_name] = clean_val
                memory["resistances"][res_name] = clean_val

    # 螢幕列印當前結果
    print("\n[Scan Results (D2R Font Optimized)]")
    if found_life:
        print(f"❤️ Life: +{found_life}")
    if found_res:
        for k, v in found_res.items():
            print(f"🛡️ {k}: {v}")
    if not found_res and not found_res:
        print("No Life or Resistance modifiers detected on this item.")

    if found_res and found_life:
        price_str = "4"
    elif found_res or found_life:
        price_str = "3"
    else:
        price_str = "2"
    memory["price"] = price_str
    
    print(f"❤️ price set: +{memory["price"]}")


def on_f10_pressed():
    try:
        raw_img = capture_d2r_screen()
        cropped_img = detect_and_crop_tooltip(raw_img)

        if os.path.exists(cropped_img):
            perform_ocr_and_parse(cropped_img)
        else:
            print("Error: Cropped tooltip file not found.")
    except Exception as e:
        print(f"An unexpected error occurred during F10 processing: {e}")


def on_f11_pressed():
    print("\n========================================")
    print("  [F11 Memory Recall - Session History]  ")
    print("========================================")

    has_data = False
    if memory["life"]:
        print(f"❤️ Remembered Life value: +{memory['life']}")
        has_data = True

    if memory["resistances"]:
        print("🛡️ Remembered Resistances:")
        for k, v in memory["resistances"].items():
            print(f"  - {k}: {v}")
        has_data = True

    print(f" Ready to send trade price set: +{memory["price"]}")
    

    if not has_data:
        print("Memory is clean. Press [F10] on an item first!")
    print("========================================\n")


if __name__ == "__main__":
    print("=== D2R Local OCR Tool (Peison Fix Patch Active) ===")
    print("📌 Run Diablo II: Resurrected in [Windowed] or [Borderless] mode.")
    print("⌨️ Keybindings:")
    print("   [F10] -> Capture, Crop, Fix Font Errors & Extract target stats")
    print("   [F11] -> Display last stored Life/Resist values on screen")
    print("   [Ctrl + C] -> Exit Script")
    print("============================================")

    keyboard.add_hotkey("f10", on_f10_pressed)
    keyboard.add_hotkey("f11", on_f11_pressed)

    keyboard.wait()
