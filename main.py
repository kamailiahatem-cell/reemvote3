from curl_cffi import requests
from bs4 import BeautifulSoup
import time
success=0
while True:
  try:
    session = requests.Session()
    url = "https://www.radionrjfm.com/vote/20"

    # impersonate="chrome" هي السحر اللي بيعدي الحماية
    response = session.get(url, impersonate="chrome")

    print(response.status_code)
    soup = BeautifulSoup(response.text, "html.parser")
    csrf_token = soup.find("input", {"name": "_token"})["value"]
    print(f"Extracted CSRF Token: {csrf_token}")
    url="https://www.radionrjfm.com/pvote"
    res=session.get('https://www.radionrjfm.com/pvote')
    # xtoken=res.cookies.get_dict()['XSRF-TOKEN']
    # web_session=res.cookies.get_dict()['webground_session']
    # print(f"Extracted XSRF Token: {xtoken}")
    # print(f"Extracted Web Session: {web_session}")
    headers = {
                    "authority": "www.radionrjfm.com",
                    "method": "POST",
                    "path": "/pvote",
                    "scheme": "https",
                    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                    "accept-encoding": "gzip, deflate, br, zstd",
                    "accept-language": "en-US,en;q=0.9",
                    "cache-control": "max-age=0",
                    "content-type": "application/x-www-form-urlencoded",
                    # "cookie": f"webground_session={web_session}",
                    "origin": "https://www.radionrjfm.com",
                    "referer": "https://www.radionrjfm.com/vote/20",
                    "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "sec-fetch-dest": "document",
                    "sec-fetch-mode": "navigate",
                    "sec-fetch-site": "same-origin",
                    "sec-fetch-user": "?1",
                    "upgrade-insecure-requests": "1",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
                    }
    payload = {
            "gidvnrj": "20",
                "sex": "1",
                "age": "3",
                "_token": csrf_token,  # Use the extracted token
                "answers[435]": "1"
                        }
    res2=session.post(url,headers=headers,data=payload)
    print(res2.status_code)
    if response.status_code == 200:
        success+=1
        print(f"Total Succeded Trials = {success}")
  except:
    time.sleep(4)