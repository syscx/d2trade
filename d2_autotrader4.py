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
TASK_QUEUE = queue.Queue(maxsize=1)


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
        """Return a cached price only while it is fresh (24-hour TTL)."""
        norm = self._normalize(item_text)
        if not norm:
            return None
        h = self._hash(norm)
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT price, created_at, hit_count FROM price_history WHERE text_hash = ?",
                    (h,)
                ).fetchone()
                if not row:
                    return None
                price, created_at, hits = row
                try:
                    created = datetime.fromisoformat(created_at)
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - created).total_seconds()
                except (TypeError, ValueError):
                    age = float("inf")
                if age < 0 or age > 86400:
                    return None
                conn.execute("UPDATE price_history SET hit_count = ? WHERE text_hash = ?", (hits + 1, h))
                conn.commit()
                return price
        except Exception as e:
            print(f"[PriceDB] lookup error: {e}")
        return None
    def save(self, item_text: str, price: str) -> None:
        """Insert or update a price entry."""
        norm = self._normalize(item_text)
        if not norm or not price or price.strip().casefold() in {"unknown", "n/a", "error"}:
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
    try:
        pages = context.pages
        page = pages[0] if len(pages) == 1 and pages[0].url == "about:blank" else context.new_page()
        page.set_default_timeout(15000)
        page.goto("https://diablo2.io", wait_until="domcontentloaded", timeout=30000)
        try:
            close_ad = page.locator("text=Close").first
            if close_ad.is_visible(timeout=1000):
                close_ad.click(timeout=2000)
        except Exception:
            pass
        create_btn = page.locator("a:has-text('Create New Trade'), button:has-text('Create New Trade'), .btn:has-text('Create New Trade')").first
        try:
            create_btn.wait_for(state="visible", timeout=8000)
            create_btn.click(timeout=5000)
        except Exception:
            page.goto("https://diablo2.io#newtrade", wait_until="domcontentloaded", timeout=30000)
        file_input = page.locator("input[type='file']").first
        file_input.wait_for(state="attached", timeout=15000)
        print(f"[{task_id}] 3. 正在上傳裝備裁切圖以觸發網頁 OCR...")
        # Playwright set_input_files triggers native input/change events; do not dispatch duplicates.
        file_input.set_input_files(image_path)
        selector = '[contenteditable="true"], .cke_editable, .mce-content-body, textarea'
        print(f"[{task_id}] 正在等待 OCR 完成（最多 25 秒）...")
        page.wait_for_function("""(selector) => Array.from(document.querySelectorAll(selector)).some(el => {
            const r = el.getBoundingClientRect();
            const value = el.tagName === 'TEXTAREA' ? el.value : el.innerText;
            return r.width > 0 && r.height > 0 && value && value.trim().length >= 90;
        })""", arg=selector, timeout=25000)
        result = page.evaluate("""(selector) => {
            const nodes = Array.from(document.querySelectorAll(selector));
            const candidates = nodes.map((el, index) => {
                const r = el.getBoundingClientRect();
                const value = el.tagName === 'TEXTAREA' ? el.value : el.innerText;
                return {index, visible: r.width > 0 && r.height > 0, text: (value || '').trim()};
            }).filter(x => x.visible && x.text.length >= 90).sort((a,b) => b.text.length-a.text.length);
            return candidates.length ? candidates[0] : null;
        }""", selector)
        if not result or len(result['text']) < 90 or 'D2R Item Tooltip Captured' in result['text']:
            raise RuntimeError("OCR 文字未通過完整性檢查；停止填入交易表單。")
        base_text = result['text'].strip()
        print(f"[{task_id}] OCR 擷取完成，長度: {len(base_text)} 字")
        estimate = ask_gemini_to_price_only(base_text)
        price = estimate if estimate and estimate.casefold() != "unknown" else "Price estimate unavailable — please price manually"
        final_description = f"{base_text}\n\nBIN: {price}"
        editor = page.locator(selector).nth(result['index'])
        editor.wait_for(state="visible", timeout=5000)
        editor.fill(final_description, timeout=10000)
        actual = editor.input_value() if editor.evaluate("el => el.tagName === 'TEXTAREA'") else editor.inner_text()
        if actual.strip() != final_description.strip():
            raise RuntimeError("交易描述欄位回讀驗證失敗；請勿上架。")
        print(f"[{task_id}] 【完成】已填入並回讀驗證單一描述欄位。")
        print("請人工確認物品文字與價格，再自行點擊上架。")
    except Exception as e:
        print(f"[{task_id}] 工作流程停止：{type(e).__name__}: {e}")
    finally:
        if os.path.exists(image_path):
            try:
                os.remove(image_path)
            except OSError as e:
                print(f"[{task_id}] 無法清理暫存圖片 {image_path}: {e}")

def on_f9_pressed():
    task_id = uuid.uuid4().hex[:6].upper()
    raw_img = f"raw_{task_id}.png"
    cropped_img = f"crop_{task_id}.jpg"
    try:
        capture_d2r_screen(raw_img)
        detect_and_crop_tooltip(raw_img, cropped_img)
        if os.path.exists(raw_img):
            os.remove(raw_img)
        try:
            TASK_QUEUE.put_nowait((cropped_img, task_id))
            print(f"[{task_id}] 裝備掃描成功！已排入網頁自動化排程。")
        except queue.Full:
            if os.path.exists(cropped_img):
                os.remove(cropped_img)
            print(f"[{task_id}] 目前已有任務處理中；本次按鍵已拒絕，避免重複操作。")
    except Exception as e:
        print(f"[{task_id}] 裝備掃描停止：{type(e).__name__}: {e}")
        for path in (raw_img, cropped_img):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

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
        
        try:
            while True:
                try:
                cropped_img, task_id = TASK_QUEUE.get(timeout=0.25)
            except queue.Empty:
                cropped_img = task_id = None
            if cropped_img:
                try:
                    process_trading_workflow(context, cropped_img, task_id)
                finally:
                    TASK_QUEUE.task_done()
            
            try:
                _ = context.pages
            except:
                print("[系統] 瀏覽器核心已被關閉，系統安全退出。")
                break
                
        except KeyboardInterrupt:
            print("\n[系統] 收到中斷訊號，準備安全退出。")
        finally:
            keyboard.unhook_all()
            try:
                context.close()
            except Exception:
                pass

if __name__ == "__main__":
    main()
