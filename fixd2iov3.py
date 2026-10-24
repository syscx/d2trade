import os
import time
import json
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
from google import genai
from google.genai import types

def get_ai_filtered_list(raw_items_data):
    """
    呼叫 Google Gemini AI 根據首頁資訊進行智慧型過濾。
    自動排除非手工裝備、已改好的裝備，並具備異常立刻 Exit 熔斷機制。
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[!] 致命錯誤：找不到 GEMINI_API_KEY 環境變數。結束程式。")
        sys.exit(1)
    
    try:
        client = genai.Client()
        prompt = f"""
        You are a Diablo 2 Resurrected expert enforcement bot for diablo2.io trading rules.
        Analyze this list from the user's shop summary page and return items that NEED manual fixing.
        CRITICAL FILTERING RULES:
        1. ONLY KEEP items that are definitely "Crafted Items" but currently have a WRONG, non-compliant name.
        2. IMMEDIATELY REMOVE any item if its title/description ALREADY contains keywords "caster", "blood", "safety", or "hit power" (case-insensitive).
        3. IMMEDIATELY REMOVE any Base items, Uniques, Sets, or Runewords (e.g., "Matriarchal Bow", "Horned Helm", "Stone of Jordan", "Shako").
        4. Maximum output count MUST NOT exceed 10 items total.
        Input Data (JSON): {json.dumps(raw_items_data, ensure_ascii=False)}
        Respond ONLY with a valid JSON array of strings containing the URLs. No markdown, no chat. Example: ["url1", "url2"]
        """
        response = client.models.generate_content(
            model='gemini-3.8-flash', 
            contents=prompt, 
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(response.text.strip())
    except Exception as e:
        print(f"[!] 致命錯誤：Google AI 模型調用或解析失敗 ({e})。結束程式。")
        sys.exit(1)

def analyze_craft_type_by_stats(page_text):
    """根據裝備固定詞綴精確判定手工類型 (Hit Power / Safety / Caster / Blood)"""
    t = page_text.lower()
    if "frost nova" in t or "knockback" in t: return "Hit Power"
    if "damage reduced by" in t or "magic damage" in t:
        if "reduce" in t: return "Safety"
    if "regenerate mana" in t or "mana regenerate" in t: return "Caster"
    if "life stolen per hit" in t or "replenish life" in t: return "Blood"
    return None

def determine_base_item_type(page_text, current_title):
    """辨識基礎物品分類 (Boots / Gloves / Ring / Amulet)"""
    combined = (page_text + " " + current_title).lower()
    if "boot" in combined: return "Boots"
    if "glove" in combined or "bracer" in combined or "gauntlet" in combined or "mitt" in combined: return "Gloves"
    if "ring" in combined: return "Ring"
    if "amulet" in combined: return "Amulet"
    return "Item"

def automate_diablo2io_edits():
    options = webdriver.ChromeOptions()
    options.add_experimental_option("detach", True)
    
    # --- 記憶登入狀態機制：在程式同級目錄下建立專屬資料夾儲存 Cookies ---
    script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
    profile_path = os.path.join(script_dir, "d2io_automation_profile")
    options.add_argument(f"--user-data-dir={profile_path}")
    options.add_argument("--start-maximized")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 10)
    actions = ActionChains(driver)
    
    # 直接前往您的個人檔案頁面 (請將 leox 換成您的帳號名稱)
    print("[!] 正在嘗試免密碼直接前往個人檔案頁面 (View Profile)...")
    driver.get("https://diablo2.io") 
    time.sleep(2.0)
    # 檢查當前是否處於登入狀態，若未登入則提示手動登入一次
    if "login" in driver.current_url or driver.find_elements(By.NAME, "username"):
        print("\n========================================================")
        print("[提示] 偵測到尚未登入。請手動登入，並切換回您的『View Profile』總覽頁面。")
        print("[重要] 下次執行時，本程式將會直接跳過此步驟直達目標頁面！")
        print("========================================================\n")
        input("[?] 瀏覽器停在您的個人檔案總覽頁面後，回到這裡按 ENTER 開始...")
    else:
        print("[✓] 成功利用本地快取憑證免密碼直達個人檔案頁面！")
    
    print("[+] 正在擷取首頁所有手工物品數據（禁止點入內頁）...")
    raw_items_data = []
    try:
        elements = driver.find_elements(By.TAG_NAME, "a")
        seen_urls = set()
        for el in elements:
            try:
                href = el.get_attribute("href")
                if href and "/trade/" in href and "-t" in href and href not in seen_urls:
                    seen_urls.add(href)
                    parent_text = ""
                    try: 
                        parent_element = el.find_element(By.XPATH, "./ancestor::*[contains(@class, 'row') or contains(@class, 'block')]")
                        parent_text = parent_element.text.strip()
                    except: 
                        parent_text = el.text.strip()
                    
                    # 本地端前置過濾：如果首頁文字就已經包含手工關鍵字，直接剔除不送給 AI
                    if any(kw in parent_text.lower() for kw in ["caster", "blood", "safety", "hit power"]): 
                        continue
                    raw_items_data.append({"url": href, "display_text_on_first_page": parent_text})
            except: continue
    except Exception as e:
        print(f"[-] 擷取首頁失敗: {e}"); return

    if not raw_items_data:
        print("[✓] 首頁檢查完畢：所有手工物品都已改好，或無任何手工商品。"); return

    # 智慧型首頁過濾（內含若發生任何 AI 異常則立刻 sys.exit 中斷終止的限制）
    target_trade_urls = get_ai_filtered_list(raw_items_data)
    
    if not target_trade_urls:
        print("[✓] 智慧審查完畢：沒有任何需要修正的錯誤手工藝品！"); return

    for index, item_url in enumerate(target_trade_urls, 1):
        print(f"\n[修復中] 進度 ({index}/{len(target_trade_urls)}) -> {item_url}")
        driver.get(item_url)
        time.sleep(2.0)
        
        try:
            page_text = driver.find_element(By.TAG_NAME, "body").text
            try: current_title = driver.find_element(By.TAG_NAME, "h1").text
            except: current_title = ""
            craft_prefix = analyze_craft_type_by_stats(page_text)
            if not craft_prefix:
                print("[-] 內頁複查：非手工品，自動跳過。"); continue
                
            item_base_type = determine_base_item_type(page_text, current_title)
            target_name = f"{craft_prefix} {item_base_type}"
            
            try:
                edit_icon = driver.find_element(By.XPATH, "//a[contains(@href, 'mode=edit') or contains(@title, 'Edit') or contains(@href, 'edit=')]")
                actions.move_to_element(edit_icon).perform()
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", edit_icon)
                time.sleep(2.5)
            except Exception as e:
                print(f"[-] 懸停點擊 Edit 圖示失敗，請手動點進修改頁。")
                input("[?] 手動進入 Edit 頁面後，在此按 ENTER 繼續...")

            # 定位輸入框並聚焦
            subject_input = wait.until(EC.presence_of_element_located((By.NAME, "subject")))
            subject_input.clear()
            time.sleep(0.3)
            
            # 點擊輸入框確保游標閃爍，並模擬逐字鍵入
            subject_input.click()
            time.sleep(0.2)
            for char in target_name:
                subject_input.send_keys(char)
                time.sleep(0.08)
                
            print("[!] 正在等待官方 Pop-up 提示浮現..."); time.sleep(3.0)
            
            # 【終極修正：純鍵盤驅動 AJAX 組合技】
            try:
                subject_input.click()
                time.sleep(0.2)
                
                # 連發兩次方向鍵向下，強制將亮條實體鎖定在跳出來的第一列上
                subject_input.send_keys(Keys.ARROW_DOWN)
                time.sleep(0.4)
                subject_input.send_keys(Keys.ARROW_DOWN)
                time.sleep(0.4)
                
                # 發送 Enter 按鍵！這會強制促使網頁 autocomplete 的監聽函式將資料覆寫進 Type 與 Rarity
                subject_input.send_keys(Keys.ENTER)
                print("[✓] 鍵盤組合技發動成功：已強制完成官方 Pop-up 選項選取！")
                time.sleep(1.0)
            except Exception as k_err:
                print(f"[-] 鍵盤連發事件失敗: {k_err}。執行後台保底機制...")
                try:
                    driver.execute_script("arguments[0].checked = true; arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", driver.find_element(By.XPATH, "//input[contains(@value, 'craft') or contains(@value, 'Craft')]"))
                except: pass

            print("========================================================")
            print(f"【待提交】裝備 [{target_name}] 已更正完畢。")
            print("👉 請確認後『手動點擊網頁上的綠色 Submit 按鈕』。")
            print("========================================================")
            input("[?] 點完 Submit 且網頁儲存跳轉後，回到這裡按 ENTER 鍵前進下一筆...")
        except Exception as e:
            print(f"[-] 處理裝備時發生異常: {e}")
            input("[?] 請手動排除，結束後在此按 ENTER 繼續...")

    print("\n[✓] 所有經由智慧篩選出的任務已處理完畢！")

if __name__ == "__main__":
    automate_diablo2io_edits()
