import os, re
from firecrawl import V1FirecrawlApp

API_KEY=os.getenv('FIRECRAWL_API_KEY')
URL='https://basketball.eurobasket.com/player/Jase-Febres/423908'
app=V1FirecrawlApp(api_key=API_KEY)
res=app.scrape_url(URL, formats=['markdown','html'])
res_dict = res.model_dump() if hasattr(res,'model_dump') else (res.__dict__ if hasattr(res,'__dict__') else {})
md = res_dict.get('markdown','') or ''
html = res_dict.get('html','') or ''
text = md + "\n" + re.sub('<[^<]+?>',' ', html)
with open('/root/.openclaw/scripts/eurobasket_raw.txt','w') as f:
    f.write(text)
print('saved')
