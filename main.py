from curl_cffi import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
import requests as standard_requests
import time
import random

def get_free_proxies():
    print("🔄 جاري سحب قائمة Proxies مجانية من مصادر متعددة...")
    proxies = set() # بنستخدم set عشان نمنع التكرار
    
    # أقوى 3 مصادر للبروكسيات المجانية (تتحدث كل كام ساعة)
    sources = [
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt"
    ]
    
    for source in sources:
        try:
            res = standard_requests.get(source, timeout=10)
            if res.status_code == 200:
                lines = res.text.strip().split('\n')
                proxies.update([p.strip() for p in lines if p.strip()])
        except Exception as e:
            print(f"⚠️ فشل سحب مصدر: {source}")
            
    proxy_list = list(proxies)
    print(f"✅ تم تجميع {len(proxy_list)} بروكسي مجاني جاهز للتجربة!\n")
    return proxy_list

# سحب البروكسيات وتخزينها قبل بدء التصويت
PROXY_LIST = get_free_proxies()

def send_vote(vote_id):
    # لو مفيش بروكسيات اتسحبت، نوقف
    if not PROXY_LIST:
        return 0
        
    # اختيار بروكسي عشوائي لكل تصويت
    proxy = random.choice(PROXY_LIST)
    proxies_dict = {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    
    try:
        # بنفتح Session ونركب فيها البروكسي المجاني
        session = requests.Session(impersonate="chrome", proxies=proxies_dict)
        
        # 1. سحب التوكن (خلينا الـ Timeout 10 ثواني عشان لو البروكسي ميت منضيعش وقت)
        url_get = "https://www.radionrjfm.com/vote/20"
        response = session.get(url_get, timeout=10)
        
        if response.status_code in [403, 429]:
            # print(f"[-] التصويت {vote_id}: البروكسي {proxy} محظور من الموقع.")
            return 0
            
        soup = BeautifulSoup(response.text, "html.parser")
        token_element = soup.find("input", {"name": "_token"})
        
        if not token_element:
            return 0
            
        csrf_token = token_element["value"]
        
        # 2. تثبيت الـ Cookies
        url_post = "https://www.radionrjfm.com/pvote"
        session.get(url_post, timeout=10)
        
        # 3. الهيدرز والداتا
        headers = {
            "authority": "www.radionrjfm.com",
            "method": "POST",
            "path": "/pvote",
            "scheme": "https",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://www.radionrjfm.com",
            "referer": "https://www.radionrjfm.com/vote/20",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
        }
        
        payload = {
            "gidvnrj": "20",
            "sex": "1",
            "age": "3",
            "_token": csrf_token,
            "answers[435]": "1"
        }
        
        # 4. إرسال التصويت
        res2 = session.post(url_post, headers=headers, data=payload, allow_redirects=False, timeout=10)
        
        if res2.status_code == 302:
            print(f"🎉 [+++] التصويت {vote_id} نجح بشدة! (البروكسي البطل: {proxy})")
            return 1
        else:
            return 0
            
    except Exception:
        # أنا كتمت طباعة الأخطاء هنا عشان الشاشة متتميليش (Timeout)، هنطبع النجاح بس
        # print(f"[!] التصويت {vote_id}: البروكسي {proxy} ميت أو بطيء.")
        return 0

if __name__ == "__main__":
  while True:
    start_time = time.time()
    total_votes = 300
    
    print(f"🚀 جاري ضرب {total_votes} ريكويست باستخدام البروكسيات المجانية...")
    print("⚠️ (تم كتم رسائل الخطأ للبروكسيات الميتة لعدم إزعاجك، سيظهر النجاح فقط)\n")
    
    # فتحنا 30 مسار عشان ننجز وقت، لأن البروكسيات المجانية بتقع كتير
    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(send_vote, range(1, total_votes + 1)))
        
    end_time = time.time()
    success_count = sum(results)
    
    print("\n" + "="*35)
    print(f"📊 التقرير النهائي (Free Proxies):")
    print(f"✅ التصويتات الناجحة: {success_count} من {total_votes}")
    print(f"⏱️ الوقت الإجمالي: {end_time - start_time:.2f} ثانية")
    print("="*35)
