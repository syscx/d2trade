import time
import pyautogui

def fill_tradie_jewel():
    print("【請注意】請在 5 秒內將畫面倒換回您的 Chrome 交易頁面，並確保輸入法為『英文半形』！")
    print("將游標點擊在網頁的第一個輸入欄位（通常是聯賽、種類或第一個屬性搜尋框）。")
    
    # 給予使用者 5 秒鐘切換到 Chrome 視窗
    for i in range(5, 0, -1):
        print(f"倒數 {i} 秒...")
        time.sleep(1)
        
    print("開始自動填寫...")
    pyautogui.press('tab')
    time.sleep(1)
    pyautogui.press('tab')    
    time.sleep(1)
    pyautogui.press('tab')    
    time.sleep(1)
    pyautogui.press('tab')    
    time.sleep(1)

    print("Start")
    time.sleep(1)
    
    print("Non Ladder")
#    pyautogui.write("Non Ladder")
#    pyautogui.press('enter')       # 選取該屬性
    pyautogui.press('tab')
    time.sleep(2)


    print("rare")    
    pyautogui.write("rare")
    pyautogui.press('enter')       # 選取該屬性
    pyautogui.press('tab')
    time.sleep(2)

 #   pyautogui.write("PC")
 #   pyautogui.press('enter')       # 選取該屬性
    pyautogui.press('tab')
    time.sleep(2)

    print("middle already in sc")
    time.sleep(2)

#    pyautogui.write("softcore")
#    pyautogui.press('enter')       # 選取該屬性
    pyautogui.press('tab')
    time.sleep(2)

    pyautogui.press('tab')
    time.sleep(10)
    print("middle prepare to enter warlock")
    pyautogui.press('tab')
#    pyautogui.write("reign of warlock")
#    pyautogui.press('enter')       # 選取該屬性
    time.sleep(2)


    print("enter reqirement")
    # 3. 屬性 1: 15 Requirement (15% 需求降低等相關屬性)
    # 先輸入關鍵字搜尋屬性，再按 Tab 到數值欄位輸入 15
    pyautogui.write("Requirement")
    time.sleep(0.5)               # 等待網頁下拉選單出現
    pyautogui.press('enter')       # 選取該屬性
    time.sleep(0.5)

    # 4. 屬性 2: 20 poison damage
    pyautogui.write("poison damage")
    time.sleep(0.5)               # 等待網頁下拉選單出現
    pyautogui.press('enter')       # 選取該屬性
    time.sleep(0.5)
    
#shift tab x 2
#20
#tab x 2    
    
    
    pyautogui.press('tab')
    time.sleep(0.5)
    pyautogui.press('tab')
    time.sleep(0.5)
    pyautogui.press('tab')
    time.sleep(0.5)
    pyautogui.press('tab')
    time.sleep(0.5)
    #exit to price area

    # 5. 填寫價格 Price (2 jah)
    # 通常價格分為「數量」欄位與「貨幣種類」欄位

    pyautogui.write("jah")
    time.sleep(3)
    pyautogui.press('enter')
    time.sleep(0.5)
    pyautogui.press('tab')
    time.sleep(0.5)
    pyautogui.press('tab')
    time.sleep(0.5)
    pyautogui.press('tab')
    time.sleep(0.5)
    pyautogui.write("2")
    time.sleep(0.5)
    pyautogui.press('enter')    
    time.sleep(0.5)
    print("填寫完成！")

if __name__ == "__main__":
    fill_tradie_jewel()
