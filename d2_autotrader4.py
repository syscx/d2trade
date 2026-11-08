import os, sys, time, json, keyboard, pyautogui, cv2, uuid, queue, threading
import hashlib
import sqlite3
from datetime import datetime, timezone
import numpy as np
from PIL import Image, ImageGrab
import pygetwindow as gw
from google import genai
from playwright.sync_api import sync_playwright
import re

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
    """Try a realistic price first; return Unknown when the estimate is not defensible."""
    print("正在將文字發送至 Gemini 估價...")
    cached = PRICE_DB.get(ocr_text)
    if cached is not None:
        print(f"👉 [PriceDB 快取命中] BIN {cached}")
        return cached
    system_prompt = (
        "You are a Diablo II: Resurrected item-market appraiser. "
        "Estimate a realistic current asking price using the item's exact stats. "
        "If the item text is incomplete or the value cannot be estimated responsibly, answer exactly 'Unknown'. "
        "Return one short price string only; do not invent market evidence."
    )
    try:
        res = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=f"Estimate a realistic D2R market asking price from this OCR text:\\n\\n{ocr_text}",
            config={"system_instruction": system_prompt}
        )
        price = (res.text or "").strip().splitlines()[0].strip()
        if not price or price.casefold() in {"unknown", "n/a", "error"} or len(price) > 80:
            print("Gemini 無法提供可靠的常規估價，改用偏高推薦價模式。")
            return "Unknown"
        PRICE_DB.save(ocr_text, price)
        print(f"👉 Gemini 估價結果: {price}")
        return price
    except Exception as e:
        print(f"Gemini 常規估價失敗: {e}")
        return "Unknown"


def ask_gemini_recommended_price(ocr_text):
    """Fallback: choose a higher-end but still plausible asking price in Ist."""
    prompt = (
        "You are pricing a Diablo II: Resurrected item for a seller who prefers an optimistic listing. "
        "The normal pricing pass could not produce a reliable estimate. Based only on the item text below, "
        "choose a higher-than-typical but still plausible asking price in Ist runes. "
        "Do not choose an absurd jackpot price. If the item is clearly low-value, choose a modest price. "
        "Return exactly one line: Recommend price: X Ist. X is a concise quantity such as 1, 2, 0.5, or 2x. "
        "Do not add explanations.\\n\\nItem OCR:\\n" + ocr_text
    )
    try:
        res = client.models.generate_content(model="gemini-3.8-flash", contents=prompt)
        value = (res.text or "").strip().splitlines()[0].strip()
        if not value or value.casefold() in {"unknown", "n/a", "error"} or len(value) > 80:
            raise ValueError("Gemini did not return a usable recommendation")
        if "ist" not in value.casefold():
            value = f"Recommend price: {value} Ist"
        elif not value.casefold().startswith("recommend price:"):
            value = f"Recommend price: {value}"
        print(f"👉 Gemini 偏高推薦價: {value}")
        return value
    except Exception as e:
        print(f"Gemini 偏高推薦價也失敗: {e}")
        return "Recommend price: MANUAL REVIEW (Gemini unavailable)"


def classify_crafted_item_title(ocr_text, task_id):
    """Deterministic crafted-item classification from diablo2.io OCR text."""
    text = " ".join((ocr_text or "").casefold().split())
    # Identify base item type from the item's actual base-name wording.
    boot_terms = (
        "boots", "greaves", "light plated boots", "chain boots",
        "heavy boots", "war boots", "battle boots", "greaves",
        "demonhide boots", "wyrmhide boots", "scarabshell boots",
        "boneweave boots", "mesh boots", "myrmidon greaves",
        " mirrored boots", "ward boots", " sharkskin boots",
    )
    is_boots = any(term.strip() in text for term in boot_terms)
    is_ring = "ring" in text
    is_amulet = "amulet" in text
    # Match the complete D2R gloves base family (normal, exceptional, elite).
    # Use full base names rather than generic words such as "gloves" or "gauntlets".
    glove_base_names = (
        "leather gloves",
        "heavy gloves",
        "chain gloves",
        "light gauntlets",
        "gauntlets",
        "demonhide gloves",
        "sharkskin gloves",
        "heavy bracers",
        "battle gauntlets",
        "war gauntlets",
        "bramble mitts",
        "vampirebone gloves",
        "vambraces",
        "crusader gauntlets",
        "ogre gauntlets",
    )
    is_gloves = any(
        re.search(rf"(?<!\w){re.escape(base_name)}(?!\w)", text)
        for base_name in glove_base_names
    )
    item_types = [
        name for name, matched in (
            ("Boots", is_boots),
            ("Ring", is_ring),
            ("Amulet", is_amulet),
            ("Gloves", is_gloves),
        ) if matched
    ]
    if len(item_types) != 1:
        print(f"[{task_id}] OCR 無法唯一判斷物品種類；保留原標題。")
        return None

    # Require the characteristic stat pair for each recipe family.
    has_mana_regen = "regenerate mana" in text or "mana regeneration" in text
    has_plus_mana = any(token in text for token in ("+ to mana", "+ mana", "increase maximum mana"))
    has_life = "+ to life" in text or "+ life" in text
    has_life_leech = "life stolen per hit" in text or "life leech" in text or "life steal" in text
    has_damage_reduce = "damage reduced by" in text or "damage reduction" in text
    has_magic_reduce = "magic damage reduced by" in text or "magic damage reduction" in text
    has_struck = "when struck" in text or "struck" in text
    has_frost_nova = "frost nova" in text

    candidates = []
    if has_mana_regen and has_plus_mana:
        candidates.append("Caster")
    if has_life and has_life_leech:
        candidates.append("Blood")
    if has_damage_reduce and has_magic_reduce:
        candidates.append("Safety")
    if has_struck and has_frost_nova:
        candidates.append("Hit Power")

    if len(candidates) != 1:
        print(f"[{task_id}] Craft 特徵不唯一或不足（{candidates}）；保留網站 OCR 原標題。")
        return None
    title = f"{candidates[0]} {item_types[0]}"
    print(f"[{task_id}] 依 OCR 屬性規則分類為：{title}")
    return title


def process_trading_workflow(context, image_path, task_id):
    """Upload the tooltip to diablo2.io, wait for its OCR, then ask Gemini to price the text."""
    print(f"[{task_id}] 2. 正在開啟 diablo2.io 交易表單...")
    try:
        pages = context.pages
        page = pages[0] if len(pages) == 1 and pages[0].url == "about:blank" else context.new_page()
        page.set_default_timeout(15000)
        page.goto("https://diablo2.io/posting.php?mode=post&f=16", wait_until="domcontentloaded", timeout=30000)

        title_input = page.locator("input[placeholder*='Enter the exact name of the item being traded']").first
        description_box = page.locator("textarea[placeholder*='Enter any comments about the item being traded']").first
        title_input.wait_for(state="visible", timeout=15000)
        description_box.wait_for(state="visible", timeout=15000)
        before_title = title_input.input_value().strip()
        before_description = description_box.input_value().strip()
        print(f"[{task_id}] 已找到交易標題與描述欄位；準備展開圖片附件區...")

        # The screenshot shows this attachment control is collapsed until clicked.
        attach_toggle = page.get_by_text("Optional: Attach a cropped screenshot of the item", exact=False).first
        attach_toggle.wait_for(state="visible", timeout=10000)
        attach_toggle.click()
        page.wait_for_timeout(300)

        file_inputs = page.locator("input[type='file']")
        file_inputs.first.wait_for(state="attached", timeout=10000)
        input_info = page.locator("input[type='file']").evaluate_all("""els => els.map((el, index) => ({
            index, accept: (el.getAttribute('accept') || '').toLowerCase(),
            name: el.getAttribute('name') || '',
            disabled: el.disabled
        }))""")
        print(f"[{task_id}] 找到檔案控制項：{input_info}")
        image_index = next((x['index'] for x in input_info if not x['disabled'] and ('image' in x['accept'] or '.png' in x['accept'] or '.jpg' in x['accept'] or '.jpeg' in x['accept'])), None)
        if image_index is None and len(input_info) == 1 and not input_info[0]['disabled']:
            image_index = input_info[0]['index']
        if image_index is None:
            raise RuntimeError("展開圖片附件區後，無法唯一確認圖片上傳欄位；停止以避免上傳到錯誤欄位。")

        upload_input = file_inputs.nth(image_index)
        print(f"[{task_id}] 3. 正在將裁切圖片上傳至 diablo2.io...")
        upload_input.set_input_files(image_path)
        # The site may consume the selected file asynchronously and then clear or
        # replace the file input. A non-empty input.files value is not proof that
        # the upload failed, so do not use it as an upload-success gate.
        print(f"[{task_id}] 圖片已交給瀏覽器檔案控制項；等待網站處理與 OCR 回填...")
        # Playwright set_input_files emits native input/change events. Do not
        # dispatch duplicates; instead verify the resulting OCR form values.

        print(f"[{task_id}] 正在等待 diablo2.io 原生 OCR 更新標題或描述欄位（最多 45 秒）...")
        print(f"[{task_id}] 上傳後欄位初始狀態：title={len(title_input.input_value().strip())} chars, description={len(description_box.input_value().strip())} chars")
        # diablo2.io first writes a transient "[Parsing item text ...]" status.
        # That status is longer than 40 chars, so length/change alone is NOT OCR completion.
        # Wait for real item text, then require it to remain unchanged for 3 polls.
        import time
        deadline = time.monotonic() + 75
        last_snapshot = None
        stable_polls = 0
        ocr_title = ""
        ocr_description = ""
        while time.monotonic() < deadline:
            current_title = title_input.input_value().strip()
            current_description = description_box.input_value().strip()
            snapshot = (current_title, current_description)
            parsing_status = bool(re.search(
                r"parsing\\s+item\\s+text|processing\\s+(?:image|screenshot)|please\\s+wait",
                current_description,
                re.IGNORECASE
            ))
            has_item_content = (
                len(current_description) >= 50
                and not parsing_status
                and bool(re.search(
                    r"defense:|kick damage:|required level:|durability:|resist|damage reduced|life stolen|mana|frost nova|\\[quote\\]",
                    current_description,
                    re.IGNORECASE
                ))
            )
            changed_from_baseline = (
                current_title != before_title or current_description != before_description
            )
            if changed_from_baseline and has_item_content:
                if snapshot == last_snapshot:
                    stable_polls += 1
                else:
                    stable_polls = 0
                if stable_polls >= 3:
                    ocr_title, ocr_description = current_title, current_description
                    break
            else:
                stable_polls = 0
            last_snapshot = snapshot
            time.sleep(0.5)
        else:
            raise RuntimeError(
                "diablo2.io 尚未提供穩定的 OCR 物品文字（可能仍在 Parsing）；"
                "為避免把 Parsing 當成物品資料，不會呼叫 Gemini 或修改表單。"
            )

        # Strip forum quote wrappers but preserve all recognized item lines.
        ocr_description = re.sub(r"^\\[quote\\]", "", ocr_description, flags=re.IGNORECASE)
        ocr_description = re.sub(r"\\[/quote\\]$", "", ocr_description, flags=re.IGNORECASE).strip()
        ocr_text = "\\n".join(part for part in (ocr_title, ocr_description) if part).strip()
        if len(ocr_text) < 50 or re.search(r"parsing\\s+item\\s+text", ocr_text, re.IGNORECASE):
            raise RuntimeError("OCR 結果仍是狀態訊息或文字不足；停止以避免錯誤估價。")
        if len(ocr_text) < 40:
            raise RuntimeError(f"網站欄位有變動，但 OCR 文字仍不足（{len(ocr_text)} 字）；不呼叫 Gemini。")
        if ocr_title == before_title and ocr_description == before_description:
            raise RuntimeError("未偵測到網站 OCR 結果變化；不呼叫 Gemini。")
        print(f"[{task_id}] diablo2.io OCR 已更新。標題：{ocr_title!r}；描述長度：{len(ocr_description)}")
        print(f"[{task_id}] 4. 判斷 Craft 類型與物品種類...")
        crafted_title = classify_crafted_item_title(ocr_text, task_id)
        if crafted_title:
            # Autocomplete is optional. Never press Enter here: on this form Enter
            # can activate the trade submit action and navigate away.
            try:
                title_input.click()
                title_input.press("Control+A")
                title_input.press("Backspace")
                title_input.press_sequentially(crafted_title, delay=80)
                if title_input.input_value().strip() != crafted_title:
                    raise RuntimeError("標題欄位未保留輸入文字")

                print(f"[{task_id}] 已逐字輸入 {crafted_title}；等待自動完成建議...")
                page.wait_for_timeout(2500)
                clicked = page.evaluate("""(target) => {
                    const input = document.querySelector(
                        "input[placeholder*='Enter the exact name of the item being traded']"
                    );
                    if (!input) return false;
                    const norm = value => (value || '').trim().toLocaleLowerCase().replace(/\\s+/g, ' ');
                    const wanted = norm(target);
                    const inputRect = input.getBoundingClientRect();
                    const candidates = Array.from(document.querySelectorAll(
                        '[role="option"], li, .ui-menu-item, .tt-suggestion, ' +
                        '.autocomplete-suggestion, [class*="suggest"]'
                    )).filter(el => {
                        const style = getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        const text = norm(el.innerText || el.textContent);
                        const visible = style.display !== 'none' &&
                                        style.visibility !== 'hidden' &&
                                        rect.width > 0 && rect.height > 0;
                        const safeTag = !['FORM', 'BUTTON', 'INPUT', 'TEXTAREA'].includes(el.tagName);
                        const nearInput = rect.top >= inputRect.top - 20 &&
                                          rect.top < inputRect.bottom + 260;
                        return visible && safeTag && nearInput && text === wanted;
                    }).sort((a, b) => {
                        const ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
                        return (ar.width * ar.height) - (br.width * br.height);
                    });
                    if (!candidates.length) return false;
                    candidates[0].dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                    candidates[0].dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
                    candidates[0].click();
                    return true;
                }""", crafted_title)
                if clicked:
                    print(f"[{task_id}] 已用滑鼠事件選取完全符合的自動完成項目。")
                else:
                    print(f"[{task_id}] 未找到安全且完全符合的下拉項目；保留標題並繼續 Gemini。")
                # Verify the form is still present; autocomplete must never navigate away.
                if title_input.count() == 0 or not title_input.is_visible():
                    print(f"[{task_id}] 自動完成後標題欄位不存在；不再操作頁面，價格流程仍嘗試繼續。")
                ocr_title = crafted_title
            except Exception as e:
                print(f"[{task_id}] 自動完成未選取（{e}）；保留標題並繼續 Gemini。")
                ocr_title = crafted_title
        else:
            print(f"[{task_id}] 無法可靠分類為指定 Craft 類型，保留網站 OCR 標題。")
        print(f"[{task_id}] OCR 原文（前 500 字）：{ocr_text[:500]}")
        print(f"[{task_id}] 5. 將網站 OCR 文字交給 Gemini 估價...")
        estimate = ask_gemini_to_price_only(ocr_text)
        if not estimate or estimate.strip().casefold() == "unknown":
            price_line = ask_gemini_recommended_price(ocr_text)
        else:
            price_line = f"BIN: {estimate}"
        # Do not attempt form writes after an unexpected navigation.
        if page.is_closed() or "/posting.php?mode=post" not in page.url:
            raise RuntimeError(
                f"diablo2.io 表單已離開或被導向（{page.url}）；"
                "為避免誤寫其他頁面，停止價格回填。請確認未提交交易。"
            )
        # Preserve the OCR textarea without firing its input/change handlers:
        # the site listens to edits there and may restart its own OCR/parser,
        # replacing valid OCR text with a transient "Parsing..." status.
        base_description = ocr_description if ocr_description else ocr_text
        final_description = f"{base_description}\n\n{price_line}"
        description_box.evaluate("""(el, value) => {
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value'
            ).set;
            setter.call(el, value);
        }""", final_description)
        if description_box.input_value().strip() != final_description.strip():
            raise RuntimeError("價格文字寫入後回讀驗證失敗；停止。")
        print(f"[{task_id}] 已保留 OCR 原文並加入價格（未觸發網站重新解析）：{price_line}")

        # The site can clear the file input after receiving the image for OCR.
        # OCR field changes are the reliable signal here; do not require the
        # transient input.files list to remain populated.
        if title_input.input_value().strip() != ocr_title:
            raise RuntimeError("交易標題在估價階段發生非預期變化；停止。")
        print(f"[{task_id}] 【完成】網站 OCR、Gemini 估價及欄位驗證完成。")
        print("請人工確認遊戲模式、平台、物品類別、圖片附件與價格，再自行點擊 Create Trade Listing。")
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
    print("  D2R 一鍵 [F9] 安全單執行緒核心 ➔ 共用登入狀態")
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
        print("👉 系統會自動導向交易區、觸發 OCR 並填入待確認描述。")
        print("👉 最終上架仍由你手動確認。按 Ctrl+C 可安全退出。")
        print("----------------------------------------------------------")
        keyboard.add_hotkey("f9", on_f9_pressed)
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
                except Exception:
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
