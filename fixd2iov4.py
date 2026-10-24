import os, time, json, sys
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
    呼叫 Google Gemini API 根據首頁區塊純文字進行智慧篩選。
    如果發生任何錯誤或找不到 API 金鑰，立刻熔斷退出程式 (sys.exit)。
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[!] 致命錯誤：找不到 GEMINI_API_KEY 環境變數。結束程式。")
        sys.exit(1)
    try:
        client = genai.Client()
        prompt = f"""
        You are a Diablo 2 Resurrected expert enforcement bot for diablo2.io trading rules.
        Analyze this list from the user's shop overview page and filter out items that NEED manual fixing.
        
        CRITICAL FILTERING RULES:
        1. ONLY KEEP items that are definitely Crafted items but have a WRONG, non-compliant name.
        2. Compliant Craft item names MUST start with either "Caster", "Safety", "Blood", or "Hit Power" followed by their item type ("Ring", "Amulet", "Gloves", or "Boots").
        3. If an item is ALREADY correctly named (e.g. starts with "WTS Caster Amulet", "WTS Blood Boots"), REMOVE it from the list.
        4. ABSOLUTELY REMOVE any Base items, Uniques, Sets, Jewels, or Runewords (e.g., "Phase Blade", "Monarch", "Rainbow Facet", "Gore Rider", "Dracul's Grasp", "Arachnid Mesh", "Grand Charm", "Small Charm") because they cannot be crafted items.
        5. Cap the final output list to a MAXIMUM of 10 items total.
        
        Input Data (JSON): {json.dumps(raw_items_data, ensure_ascii=False)}
        Respond ONLY with a valid JSON array of strings containing the URLs that need fixing. No markdown block. Example: ["url1", "url2"]
        """
        print("[!] 正在呼叫 Google AI (Gemini-3.8-Flash) 進行智慧型首頁過濾...")
        response = client.models.generate_content(
            model='gemini-3.8-flash', contents=prompt, 
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(response.text.strip())
    except Exception as e:
        print(f"[!] 致命錯誤：Google AI 模型調用或解析失敗 ({e})。結束程式。")
        sys.exit(1)

def analyze_craft_type_by_stats(page_text):
    t = page_text.lower()
    if "frost nova" in t or "knockback" in t: return "Hit Power"
    if "damage reduced by" in t or "magic damage" in t:
        if "reduce" in t: return "Safety"
    if "regenerate mana" in t or "mana regenerate" in t: return "Caster"
    if "life stolen per hit" in t or "replenish life" in t: return "Blood"
    return None

def determine_base_item_type(page_text, current_title):
    combined = (page_text + " " + current_title).lower()
    return "Boots" if "boot" in combined else "Gloves" if ("glove" in combined or "bracer" in combined) else "Ring" if "ring" in combined else "Amulet" if "amulet" in combined else "Item"

def automate_diablo2io_edits():
    options = webdriver.ChromeOptions()
    options.add_experimental_option("detach", True)
    
    script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
    profile_path = os.path.join(script_dir, "d2io_automation_profile")
    options.add_argument(f"--user-data-dir={profile_path}")
    options.add_argument("--start-maximized")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 10)
    actions = ActionChains(driver)
    
    print("[!] 正在開啟 diablo2.io 登入頁面...")
    driver.get("https://diablo2.io")
    print("\n========================================================")
    print("[提示] 請先登入，並手動前往您可以看見完整商品清單的交易總覽頁面。")
    print("========================================================\n")
    input("[?] 當瀏覽器畫面完全顯示出您的多筆交易列表時，請回到這裡按 ENTER 開始...")
    
    # 1. 使用您原本測試成功、運作正常的首頁列表抓取邏輯
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
                    
                    raw_items_data.append({"url": href, "display_text_on_first_page": parent_text})
            except: continue
    except Exception as e:
        print(f"[-] 擷取首頁列表失敗: {e}"); return

    if not raw_items_data:
        print("[-] 總覽畫面上找不到任何符合格式的商品交易連結。"); return

    # 2. 將收集到的資料丟給 Gemini-3.8-Flash 進行智慧篩選 (熔斷機制包覆在內)
    target_trade_urls = get_ai_filtered_list(raw_items_data)

    if not target_trade_urls:
        print("[✓] 智慧審查完畢：沒有任何需要修正的錯誤手工藝品！"); return

    print(f"[✓] AI 篩選完成！共找出 {len(target_trade_urls)} 筆需要更正名稱的手工項目。開始依序處理...")

    # 3. 進入下一個 Selenium 修正步驟的自動化工作迴圈
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
                print("[-] 內頁複查防線：本商品為普通裝備，自動跳過（Skip）。"); continue
                
            item_base_type = determine_base_item_type(page_text, current_title)
            target_name = f"{craft_prefix} {item_base_type}"
            
            try:
                edit_icon = driver.find_element(By.XPATH, "//a[contains(@href, 'mode=edit') or contains(@title, 'Edit') or contains(@href, 'edit=')]")
                actions.move_to_element(edit_icon).perform()
                time.sleep(0.5)
                driver.execute_script("arguments.click();", edit_icon)
                time.sleep(2.5)
            except Exception as e:
                print(f"[-] 無法定位修改小圖示，請手動點進 Edit 頁面。")
                input("[?] 手動點入 Edit 表單頁面後，在此按 ENTER 繼續...")

            subject_input = wait.until(EC.presence_of_element_located((By.NAME, "subject")))
            subject_input.clear()
            time.sleep(0.3)
            
            subject_input.click()
            time.sleep(0.2)
            for char in target_name:
                subject_input.send_keys(char)
                time.sleep(0.08)
                
            print("[!] 等待官方 Pop-up 下拉建議選單彈出..."); time.sleep(3.0)
            
            # 使用鍵盤組合技 (ARROW_DOWN * 2 + ENTER) 強制選取浮動選單，完成後台同步
            try:
                subject_input.click()
                time.sleep(0.2)
                subject_input.send_keys(Keys.ARROW_DOWN)
                time.sleep(0.4)
                subject_input.send_keys(Keys.ARROW_DOWN)
                time.sleep(0.4)
                subject_input.send_keys(Keys.ENTER)
                print("[✓] 鍵盤組合技發動成功：已完成官方 Pop-up 選項選取！")
                time.sleep(1.0)
            except:
                try: driver.execute_script("arguments.checked = true; arguments.dispatchEvent(new Event('change', { bubbles: true }));", driver.find_element(By.XPATH, "//input[contains(@value, 'craft') or contains(@value, 'Craft')]"))
                except: pass

            print("========================================================")
            print(f"【待確認】裝備名稱已自動更正為: [{target_name}]")
            print("👉 請確認後『手動點擊網頁上的綠色 Submit 按鈕』。")
            print("========================================================")
            input("[?] 當您點完 Submit 且網頁儲存跳轉後，回到這裡按 ENTER 鍵前進下一筆裝備...")
            
        except Exception as e:
            print(f"[-] 處理裝備時發生異常: {e}")
            input("[?] 發生錯誤，請手動調整。結束後在此按 ENTER 繼續...")

    print("\n[✓] 所有經由 AI 智慧過濾篩選出的錯誤手工藝品任務已全數處理完畢！")

if __name__ == "__main__":
    automate_diablo2io_edits()
