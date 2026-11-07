import os, sys, time, json, keyboard, pyautogui, cv2, uuid, queue, threading
import hashlib
import sqlite3
from datetime import datetime, timezone
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

# 價格歷史資料庫路徑（與 sandbox profile 同目錄，方便管理）
PRICE_DB_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "d2_price_history.db")

# 建立一個執行緒安全的任務佇列
TASK_QUEUE = queue.Queue()


# ---------------------------------------------------------------------------
# Simple Price History DB (SQLite)
# ---------------------------------------------------------------------------
class PriceHistoryDB:
    """Lightweight local cache so identical item texts skip Gemini re-queries."""

    def __init__(self, db_path: str = PRICE_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    text_hash   TEXT PRIMARY KEY,
                    item_text   TEXT NOT NULL,
                    price       TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    hit_count   INTEGER DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at
                ON price_history(created_at)
            """)
            conn.commit()

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize item text for consistent hashing (whitespace + case)."""
        return " ".join(text.strip().lower().split())

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get(self, item_text: str):
        """Return cached price string if present, else None."""
        norm = self._normalize(item_text)
        if not norm:
            return None
        h = self._hash(norm)
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT price, hit_count FROM price_history WHERE text_hash = ?",
                    (h,)
                ).fetchone()
                if row:
                    price, hits = row
                    conn.execute(
                        "UPDATE price_history SET hit_count = ? WHERE text_hash = ?",
                        (hits + 1, h)
                    )
                    conn.commit()
                    return price
        except Exception as e:
            print(f"[PriceDB] lookup error: {e}")
        return None

    def save(self, item_text: str, price: str) -> None:
        """Insert or update a price entry."""
        norm = self._normalize(item_text)
        if not norm or not price:
            return
        h = self._hash(norm)
        now = datetime.now(timezone.utc).isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO price_history (text_hash, item_text, price, created_at, hit_count)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(text_hash) DO UPDATE SET
                        price = excluded.price,
                        created_at = excluded.created_at,
                        hit_count = hit_count + 1
                """, (h, item_text[:2000], price, now))
                conn.commit()
        except Exception as e:
            print(f"[PriceDB] save error: {e}")


# Global DB instance
PRICE_DB = PriceHistoryDB()


def detect_and_crop_tooltip(f_path, o_path):
    """Crop a likely tooltip; fail closed when no plausible region is found."""
    print("正在透過電腦視覺掃描 D2R 提示框...")
    img = cv2.imread(f_path)
    if img is None:
        raise RuntimeError("截圖檔案無法讀取。")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best_box, max_area = None, 0
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if 150 < w < (gray.shape[1] * 0.5) and 150 < h < (gray.shape[0] * 0.8):
            if w * h > max_area:
                max_area, best_box = w * h, (x, y, w, h)
    if not best_box:
        raise RuntimeError("找不到可信的裝備提示框；已停止，避免把整個桌面送去 OCR。")
    x, y, w, h = best_box
    p = 5
    crop = img[max(0, y-p):min(gray.shape[0], y+h+p), max(0, x-p):min(gray.shape[1], x+w+p)]
    if crop.size == 0 or crop.shape[0] < 100 or crop.shape[1] < 100:
        raise RuntimeError("偵測到的提示框尺寸異常；已停止處理。")
    if not cv2.imwrite(o_path, crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95]):
        raise RuntimeError("無法寫入提示框裁切圖片。")
    return o_path


def capture_d2r_screen(r_path):
    """Capture only the game window. Never silently fall back to the desktop."""
    print("\n[F9 觸發] 正在擷取遊戲視窗...")
    d2r_windows = gw.getWindowsWithTitle("Diablo II: Resurrected")
    if not d2r_windows:
        raise RuntimeError("找不到 Diablo II: Resurrected 視窗；請確認遊戲已開啟。")
    d2r_win = d2r_windows[0]
    if getattr(d2r_win, "isMinimized", False):
        raise RuntimeError("遊戲視窗目前已最小化。")
    try:
        d2r_win.activate()
        time.sleep(0.35)
    except Exception as e:
        raise RuntimeError(f"無法將遊戲視窗切到前景：{e}") from e
    left, top, right, bottom = d2r_win.left, d2r_win.top, d2r_win.right, d2r_win.bottom
    if right <= left or bottom <= top:
        raise RuntimeError("遊戲視窗尺寸無效。")
    ImageGrab.grab(bbox=(left, top, right, bottom)).save(r_path)
    if not os.path.exists(r_path) or os.path.getsize(r_path) < 1024:
        raise RuntimeError("遊戲截圖為空或檔案尺寸異常。")
    return r_path
def ask_gemini_to_price_only(ocr_text):
    """Return a cautious estimate; never invent a fallback price."""
    print("正在將文字發送至 Gemini 估價...")
    cached = PRICE_DB.get(ocr_text)
    if cached is not None:
        print(f"👉 [PriceDB 快取命中] BIN {cached}")
        return cached
    system_prompt = (
        "You are a cautious Diablo II: Resurrected item-market appraiser. "
        "Estimate a realistic current asking price, not the highest imaginable price. "
        "If the item text is incomplete, ambiguous, or lacks important stats, answer exactly 'Unknown'. "
        "Return one short price string only. Do not invent comparable sales or certainty."
    )
    try:
        res = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=f"Estimate a realistic D2R market asking price from this OCR text:\n\n{ocr_text}",
            config={"system_instruction": system_prompt}
        )
        price = (res.text or "").strip()
        price = price.splitlines()[0].strip() if price else "Unknown"
        if not price or price.casefold() in {"unknown", "n/a", "error"} or len(price) > 80:
            print("Gemini 無法可靠估價；不會自動填入猜測價格。")
            return "Unknown"
        print(f"👉 Gemini 估價結果: BIN {price}")
        PRICE_DB.save(ocr_text, price)
        return price
    except Exception as e:
        print(f"Gemini 計價失敗: {e}")
        return "Unknown"

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
        normalized_price = ai_price.strip() if ai_price else ""
        price_str = (
            "Look for HR"
            if not normalized_price or normalized_price.casefold() == "unknown"
            else normalized_price
        )

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
        print(f"📦 [系統] 價格歷史資料庫: {PRICE_DB_PATH}")

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
