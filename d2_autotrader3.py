import os, sys, time, json, keyboard, pyautogui, cv2
import numpy as np
from PIL import Image, ImageGrab
import pygetwindow as gw
from google import genai
from playwright.sync_api import sync_playwright

try:
    client = genai.Client()
except Exception as e:
    print(f"【錯誤】Google AI 初始化失敗: {e}"); sys.exit(1)

PURE_SANDBOX_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "d2_pure_sandbox_profile")
IS_RUNNING = False

def detect_and_crop_tooltip(f_path, o_path="temp_tooltip.jpg"):
    print("正在透過電腦視覺掃描 D2R 提示框...")
    img = cv2.imread(f_path)
    if img is None: return f_path
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best_box, max_area = None, 0
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if 150 < w < (gray.shape[1] * 0.5) and 150 < h < (gray.shape[0] * 0.8):
            if w * h > max_area: max_area = w * h; best_box = (x, y, w, h)
    if best_box:
        x, y, w, h = best_box; p = 5
        cv2.imwrite(o_path, img[max(0,y-p):min(gray.shape[0],y+h+p), max(0,x-p):min(gray.shape[1],x+w+p)], [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        return o_path
    return f_path

def capture_d2r_screen(r_path="raw_screen.png"):
    print("\n[F9 觸發] 正在擷取遊戲視窗...")
    d2r_windows = gw.getWindowsWithTitle("Diablo II: Resurrected")
    if d2r_windows and len(d2r_windows) > 0:
        d2r_win = d2r_windows[0]
        try: d2r_win.activate(); time.sleep(0.1)
        except: pass
        ImageGrab.grab(bbox=(d2r_win.left, d2r_win.top, d2r_win.right, d2r_win.bottom)).save(r_path)
        return r_path
    ImageGrab.grab().save(r_path); return r_path

def ask_gemini_to_price_only(ocr_text):
    print("3. 正在將文字發送至 Gemini 3.8 Flash 進行最高天價估計...")
    system_prompt = (
        "You are an aggressive and elite D2R whale-tier market appraiser. "
        "Estimate the HIGHEST POSSIBLE market value (Premium BIN Price) for wealthy collectors. Do NOT lowball.\n"
        "Rules: Valuable items in High Runes (e.g., '5x Jah', '3x Ber'). Mid items in Perfect Amethysts ('40 PA'). Small charms in '5 PGems'. "
        "If worthless, output exactly '0 (Worthless)'. Respond ONLY with the final value string without ANY conversation or markdown."
    )
    try:
        res = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=f"Appraise this item text at highest premium value:\n\n{ocr_text}",
            config={"system_instruction": system_prompt}
        )
        price = res.text.strip()
        print(f"👉 Gemini 天價估計結果: BIN {price}"); return price
    except Exception as e:
        print(f"Gemini 計價失敗: {e}"); return "Unknown"

def process_trading_workflow(image_path):
    print("2. 啟動隔離的自動化沙盒瀏覽器進程...")
    try:
        with sync_playwright() as p:
            browser_context = p.chromium.launch_persistent_context(user_data_dir=PURE_SANDBOX_DIR, headless=False)
            page = browser_context.pages[0]
            print("🚀 直接導向並空降至 diablo2.io 商品建立頁面...")
            page.goto("https://diablo2.io")
            page.wait_for_load_state("networkidle")

            if "login" in page.url or page.locator("input[type='file']").count() == 0:
                print("\n【⚠️ 首次沙盒認證】請完成登入，未來將全自動直跳！")
                page.wait_for_selector("input[type='file']", state="attached", timeout=60000)

            file_input = page.locator("input[type='file']").first
            file_input.wait_for(state="attached", timeout=15000)
            print("3. 正在將 OpenCV 精準裁切後的裝備小圖上傳至網頁以觸發網頁內建 OCR...")
            file_input.set_input_files(image_path)
            
            # 讓網頁後台去完成它自己的圖片分析與自動分類（保證不卡死）
            print("圖片上傳成功，正在等待 diablo2.io 網頁原生解析器處理與分類裝備...")
            time.sleep(6)

            # 撈出網頁原生解析完畢後生成的文字
            web_ocr_text = page.evaluate('''() => {
                const ed = document.querySelector('[contenteditable="true"], .cke_editable, .mce-content-body, textarea');
                if (ed) return ed.tagName === 'TEXTAREA' ? ed.value : ed.innerText;
                return "";
            }''')
            
            base_text = web_ocr_text.strip() if web_ocr_text.strip() else "D2R Item Tooltip Captured"
            print(f"👍 成功從網頁編輯器擷取文字！長度: {len(base_text)} 字")
            
            if len(base_text) < 90:
                sys.exit()

            # 呼叫大配額 Gemini 3.8 Flash 進行天價估價
            ai_price = ask_gemini_to_price_only(base_text)
            
            if not ai_price or "0" in ai_price or "Worthless" in ai_price or "Unknown" in ai_price:
                price_str = "Look for HR"
            else:
                price_str = ai_price

            # 保留網頁本來的 OCR 結果，在尾端換行追加天價 BIN
            final_description = f"{base_text}\n\nBIN: {price_str}"
            print(f"5. 正在將最高 BIN 價格追加填入網頁編輯器尾端 (價格: {price_str})...")
            
            try:
                page.evaluate(''' (text) => {
                    const eds = document.querySelectorAll('[contenteditable="true"], .cke_editable, .mce-content-body, textarea');
                    eds.forEach(el => {
                        if (el.tagName === 'TEXTAREA') { el.value = text; } 
                        else { el.innerText = text; }
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                    });
                } ''', final_description)
                print("   -> 網頁編輯器尾端 BIN 追加填寫成功！")
            except: pass

            print("\n【👍 全自動處理完成】請手動確認並點擊上架。")
            print("👉 提示：點擊上架成功網頁跳轉後，或手動「直接關閉網頁視窗」皆可繼續下一件！")
            
            # 【關鍵修改 1】：將 timeout 設為 0（無限等待），這樣你慢慢看、慢慢改都不會超時拋出異常
            # 【關鍵修改 2】：使用 try-except 包裹，不論是手動關閉視窗還是程式結束，都能優雅釋放
            try:
                # 同時監聽「視窗被關閉」或「URL 改變 (代表點擊提交成功跳轉了)」
                # 這裡為了保險，先使用無限期等待關閉視窗
                page.wait_for_event("close", timeout=0)
            except Exception:
                pass
                
            print("視窗已關閉，安全釋放沙盒鎖...")
            browser_context.close()
            
    except Exception as e: 
        print(f"網頁自動化錯誤: {e}")

def on_f9_pressed():
    global IS_RUNNING
    if IS_RUNNING: print("\n【⚠️ 系統警告】前一個交易視窗尚未關閉！"); return
    try:
        IS_RUNNING = True
        raw_img = capture_d2r_screen()
        cropped_img = detect_and_crop_tooltip(raw_img)
        
        # 核心優化：直接跳過容易卡住的本地 Windows 處理，秒速啟動沙盒網頁，100% 不卡死
        process_trading_workflow(cropped_img)
    finally:
        IS_RUNNING = False; print("="*40 + "\n【解鎖】回到監聽等待狀態...")

def main():
    print("==========================================================")
    print("  暗黑 2 一鍵 [F9] 網頁原生 OCR 導向 ➔ 獨立沙盒 ➔ 100%防卡死  ")
    print("==========================================================")
    print("👉 你的日常 Chrome 完全不需要關閉，互不干擾。")
    print("👉 請進入 D2R 遊戲，滑鼠指著裝備並按下 [F9] 鍵。")
    print("----------------------------------------------------------")
    keyboard.add_hotkey('f9', on_f9_pressed); keyboard.wait()

if __name__ == "__main__":
    main()