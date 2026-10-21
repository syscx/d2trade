import os, sys, time, json, keyboard, pyautogui, cv2, uuid, queue, threading
import numpy as np
from PIL import Image, ImageGrab
import pygetwindow as gw
from google import genai
from playwright.sync_api import sync_playwright

try:
    client = genai.Client()
except Exception as e:
    print(f"【錯誤】Google AI 初始化失敗: {e}"); sys.exit(1)

# 使用固定的沙盒資料夾，關閉程式後下次開，登入狀態依然會保留
PURE_SANDBOX_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "d2_shared_sandbox_profile")

# 建立一個執行緒安全的任務佇列
TASK_QUEUE = queue.Queue()

def detect_and_crop_tooltip(f_path, o_path):
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

def capture_d2r_screen(r_path):
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
    print("正在將文字發送至 Gemini 進行最高天價估計...")
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

def process_trading_workflow(context, image_path, task_id):
    print(f"[{task_id}] 2. 正在共享環境中開啟網頁視窗...")
    page = None
    try:
        existing_pages = context.pages
        # 【核心修正】：指定引索 [0] 來讀取清單中的分頁網址，避免 list 報錯
        if len(existing_pages) == 1 and existing_pages[0].url == "about:blank":
            page = existing_pages[0]
            print(f"[{task_id}] ➔ 復用初始空白瀏覽器視窗。")
        else:
            page = context.new_page()
            print(f"[{task_id}] ➔ 開啟全新獨立視窗。")
            
        print(f"[{task_id}] 🚀 空降至 diablo2.io 交易市場...")
        page.goto("https://diablo2.io")
        page.wait_for_load_state("networkidle")
        
        # 檢查是否因為廣告牆阻擋導致流程卡死
        try:
            close_ad = page.locator("text=Close").first
            if close_ad.is_visible():
                close_ad.click()
                print(f"[{task_id}] ➔ 偵測到廣告擋牆提示，已全自動幫您關閉。")
        except: pass

        print(f"[{task_id}] ➔ 正在嘗試自動點擊 'Create New Trade' 按鈕...")
        create_btn = page.locator("a:has-text('Create New Trade'), button:has-text('Create New Trade'), .btn:has-text('Create New Trade')").first
        
        try:
            create_btn.wait_for(state="visible", timeout=8000)
            create_btn.click()
            print(f"[{task_id}] 👍 成功自動點擊 'Create New Trade'！")
        except Exception:
            print(f"[{task_id}] ⚠️ 沒看到 'Create New Trade' 按鈕，嘗試使用後備網址跳轉...")
            page.goto("https://diablo2.io#newtrade")

        # 尋找檔案上傳按鈕，放寬等待限制為只要掛載（attached）到網頁 DOM 樹就抓取
        file_input = page.locator("input[type='file']").first
        try:
            file_input.wait_for(state="attached", timeout=10000)
            page.wait_for_timeout(800)  # 給予彈出對話框動畫就緒的硬緩衝時間
        except Exception:
            print(f"\n[{task_id}] 【⚠️ 仍找不到上傳控制項】請檢查目前是否為登入狀態！")
            page.wait_for_selector("input[type='file']", state="attached", timeout=60000)

        print(f"[{task_id}] 3. 正在上傳裝備裁切圖以觸發網頁內建 OCR...")
        file_input.set_input_files(image_path)
        
        # 強制在網頁內部環境觸發上傳變更事件，確保網頁原生程式碼開始處理圖片
        page.evaluate('''() => {
            const input = document.querySelector("input[type='file']");
            if (input) {
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }''')
        
        print(f"[{task_id}] 圖片上傳成功，正在等待網頁原生解析器處理...")
        page.wait_for_timeout(6000)

        web_ocr_text = page.evaluate('''() => {
            const ed = document.querySelector('[contenteditable="true"], .cke_editable, .mce-content-body, textarea');
            if (ed) return ed.tagName === 'TEXTAREA' ? ed.value : ed.innerText;
            return "";
        }''')
        
        base_text = web_ocr_text.strip() if web_ocr_text.strip() else "D2R Item Tooltip Captured"
        print(f"[{task_id}] 👍 成功擷取文字！長度: {len(base_text)} 字")
        
        if len(base_text) < 90:
            print(f"[{task_id}] 擷取文字過短，可能未成功觸發網頁原生 OCR。")
            return

        ai_price = ask_gemini_to_price_only(base_text)
        price_str = "Look for HR" if not ai_price or any(x in ai_price for x in ["0", "Worthless", "Unknown"]) else ai_price

        final_description = f"{base_text}\n\nBIN: {price_str}"
        print(f"[{task_id}] 5. 追加填入最高 BIN 價格 (價格: {price_str})...")
        
        try:
            page.evaluate(''' (text) => {
                const eds = document.querySelectorAll('[contenteditable="true"], .cke_editable, .mce-content-body, textarea');
                eds.forEach(el => {
                    if (el.tagName === 'TEXTAREA') { el.value = text; } 
                    else { el.innerText = text; }
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                });
            } ''', final_description)
            print(f"[{task_id}] -> BIN 追加填寫成功！")
        except: pass

        print(f"\n[{task_id}] 【👍 全自動處理完成】請手動確認並點擊上架。")
        print(f"👉 處理完畢後，直接關閉該網頁視窗即可！\n")

    except Exception as e: 
        print(f"[{task_id}] 網頁自動化錯誤: {e}")
    finally:
        if os.path.exists(image_path): 
            try: os.remove(image_path)
            except: pass

def on_f9_pressed():
    task_id = uuid.uuid4().hex[:6].upper()
    raw_img = f"raw_{task_id}.png"
    cropped_img = f"crop_{task_id}.jpg"
    
    try:
        capture_d2r_screen(raw_img)
        detect_and_crop_tooltip(raw_img, cropped_img)
        if os.path.exists(raw_img): os.remove(raw_img)
        
        TASK_QUEUE.put((cropped_img, task_id))
        print(f"[{task_id}] 裝備掃描成功！已排入網頁自動化排程...")
    except Exception as e:
        print(f"[{task_id}] 裝備掃描發生錯誤: {e}")

def main():
    print("==========================================================")
    print("  D2R 一鍵 [F9] 安全單執行緒核心 ➔ 支援多視窗並行與登入共用 ")
    print("==========================================================")
    print("正在初始化共享瀏覽器核心，請稍候...")
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PURE_SANDBOX_DIR, 
            headless=False
        )
        print("🚀 [系統] 共享登入狀態的瀏覽器核心已啟動完成。")

        print("\n系統準備就緒！")
        print("👉 請進入 D2R 遊戲，滑鼠指著裝備並按下 [F9] 鍵。")
        print("👉 系統會自動導向交易區、自動點擊 'Create New Trade' 並進行估價！")
        print("----------------------------------------------------------")
        
        keyboard.add_hotkey('f9', on_f9_pressed)
        
        while True:
            try:
                cropped_img, task_id = TASK_QUEUE.get_nowait()
                process_trading_workflow(context, cropped_img, task_id)
                TASK_QUEUE.task_done()
            except queue.Empty:
                pass
            
            try:
                _ = context.pages
            except:
                print("[系統] 瀏覽器核心已被關閉，系統安全退出。")
                break
                
            time.sleep(0.1)

if __name__ == "__main__":
    main()
