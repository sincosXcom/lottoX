import os
import requests
import gspread
from google.oauth2.service_account import Credentials
import json

# 辅助函数：获取环境变量，不存在则报错
def get_required_env(name):
    value = os.environ.get(name)
    if not value:
        raise Exception(f"缺少环境变量 {name}，请在 GitHub Secrets 中配置")
    return value

LOTTERIES = {
    "快乐8": {
        "url": get_required_env('KL8_URL'),
        "num_cols": 20,
        "sheet": "kl8",
        "convert_issue": False
    },
    "双色球": {
        "url": get_required_env('SSQ_URL'),
        "num_cols": 7,
        "sheet": "ssq",
        "convert_issue": False
    },
    "大乐透": {
        "url": get_required_env('DLT_URL'),
        "num_cols": 7,
        "sheet": "dlt",
        "convert_issue": False
    },
    "福彩3D": {
        "url": get_required_env('SD_URL'),
        "num_cols": 3,
        "sheet": "sd",
        "convert_issue": False
    },
    "排列3": {
        "url": get_required_env('P3_URL'),
        "num_cols": 3,
        "sheet": "p3",
        "convert_issue": True
    },
    "排列5": {
        "url": get_required_env('P5_URL'),
        "num_cols": 5,
        "sheet": "p5",
        "convert_issue": True
    },
    "七星彩": {
        "url": get_required_env('QXC_URL'),
        "num_cols": 7,
        "sheet": "qxc",
        "convert_issue": False
    },
    "七乐彩": {
        "url": get_required_env('QLC_URL'),
        "num_cols": 8,
        "sheet": "qlc",
        "convert_issue": False
    },
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def format_date(date_str):
    parts = date_str.split('-')
    if len(parts) == 3:
        return f"{parts[0]}-{int(parts[1])}-{int(parts[2])}"
    return date_str

def fetch_latest_issues(name, config):
    url = config['url']
    num_cols = config['num_cols']
    convert = config.get('convert_issue', False)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'utf-8'
        if resp.status_code != 200:
            print(f"{name} HTTP {resp.status_code}")
            return []
        lines = resp.text.splitlines()
    except Exception as e:
        print(f"{name} 请求异常: {e}")
        return []

    data_rows = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("URL:") or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2 + num_cols:
            continue
        issue = parts[0]
        if convert:
            issue = issue[2:]
        date_str = format_date(parts[1])
        numbers = []
        for n in parts[2:2+num_cols]:
            try:
                numbers.append(int(n))
            except ValueError:
                numbers.append(n)
        data_rows.append([issue, date_str] + numbers)

    if not data_rows:
        return []
    data_rows.sort(key=lambda x: int(x[0]))
    return [data_rows[-1]]

def update_google_sheet(sheet_name, latest_row):
    creds_json = os.environ.get('GOOGLE_CREDS')
    if not creds_json:
        raise Exception("缺少 GOOGLE_CREDS 环境变量")
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open("lotto_data")
    worksheet = spreadsheet.worksheet(sheet_name)

    all_rows = worksheet.get_all_values()
    existing_issues = set(row[0] for row in all_rows if row)
    if latest_row[0] in existing_issues:
        print(f"{sheet_name} 期号 {latest_row[0]} 已存在，跳过")
        return

    worksheet.append_row(latest_row)
    print(f"{sheet_name} 已追加最新期号 {latest_row[0]}")

def main():
    for name, config in LOTTERIES.items():
        print(f"处理 {name}...")
        latest = fetch_latest_issues(name, config)
        if latest:
            update_google_sheet(config["sheet"], latest[0])
        else:
            print(f"  {name} 未获取到最新数据")

if __name__ == "__main__":
    main()
