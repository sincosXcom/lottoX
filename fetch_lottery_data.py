import requests
import gspread
from google.oauth2.service_account import Credentials
import os
from datetime import datetime

def fetch_latest_kl8():
    """从API获取最新快乐8开奖数据"""
    # 方案A: 使用 apihz.cn (免费，注册获取ID和KEY)
    # url = "https://cn.apihz.cn/api/caipiao/kuaile8.php"
    # params = {
    #     'id': os.environ['API_ID'],    # 从环境变量获取
    #     'key': os.environ['API_KEY'],  # 从环境变量获取
    #     'qh': ''        # 空表示最新期号
    # }
    # 方案B: 使用 jumdata (免费)
    # url = "https://api.jumdata.com/lottery/winning"
    # params = {'type': 'kl8', 'expect': ''}
    
    # 为演示，先使用 jumdata 格式
    url = "https://api.jumdata.com/lottery/winning"
    params = {'type': 'kl8', 'expect': ''}
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get('code') == 200:
            item = data['data']
            numbers = item['openCode'].split(',')
            return {
                "expect": item['expect'],
                "date": item['time'][:10],
                "numbers": numbers[:20]
            }
        return None
    except Exception as e:
        print(f"API 请求失败: {e}")
        return None

def update_google_sheet(latest_data):
    """将最新数据追加或更新到Google Sheets"""
    scope = ["https://spreadsheets.google.com/feeds", 
             "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(
        eval(os.environ['GOOGLE_CREDS']),
        scopes=scope
    )
    client = gspread.authorize(creds)
    sheet = client.open("lotto_data").worksheet("kl8")
    
    # 检查是否已存在
    records = sheet.get_all_values()
    for row in records:
        if row[0] == latest_data["expect"]:
            print(f"期号 {latest_data['expect']} 已存在，跳过")
            return
    
    new_row = [latest_data["expect"], latest_data["date"]] + latest_data["numbers"]
    sheet.append_row(new_row)
    print(f"已添加期号 {latest_data['expect']} 的数据")

def main():
    data = fetch_latest_kl8()
    if data:
        update_google_sheet(data)
    else:
        print("获取数据失败")

if __name__ == '__main__':
    main()
