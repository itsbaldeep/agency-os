#!/usr/bin/env python3
"""Dependency-free, bounded SEO measurement primitives."""
import base64, hashlib, json, os, re, subprocess, time
import urllib.parse, urllib.request
import urllib.robotparser as robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser

MAX_PAGES, MAX_BYTES, TIMEOUT, MIN_DELAY = 50, 1_000_000, 15, .2
USER_AGENT = "AgencyOS SEO Measurement/1.0 (+https://deployden.tech)"
SERVICE_ACCOUNT_FILE = "/home/agency/.config/agency/gsc-service-account.json"
PARSER_VERSION = "seo-parser-2"

def now(): return datetime.now(timezone.utc).isoformat()

def normalize_url(value, base=None):
    url = urllib.parse.urljoin(base or "", str(value or "").strip())
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname or p.username is not None or p.password is not None:
        return None
    try:
        port = p.port
    except ValueError:
        return None
    path = re.sub(r"/{2,}", "/", p.path or "/")
    host = p.hostname.lower()
    if ":" in host:
        host = "[" + host + "]"
    default = 443 if p.scheme.lower() == "https" else 80
    netloc = host if port in (None, default) else "%s:%d" % (host, port)
    return urllib.parse.urlunsplit((p.scheme.lower(), netloc, path if path.startswith("/") else "/" + path, p.query, ""))

def same_origin(url, origin):
    try:
        a, b = urllib.parse.urlsplit(url), urllib.parse.urlsplit(origin)
        return (a.scheme, a.hostname, a.port or (443 if a.scheme == "https" else 80)) == (b.scheme, b.hostname, b.port or (443 if b.scheme == "https" else 80))
    except ValueError:
        return False

class PageParser(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True); self.base=base; self.title=""; self.in_title=False; self.meta={}; self.canonical=None; self.headings=[]; self.heading=None; self.links=[]; self.images=[]; self.jsonld=False; self.jsonld_blocks=[]; self.jsonld_active=False; self.jsonld_text=""
    def handle_starttag(self, tag, attrs):
        a={str(k).lower():str(v or "") for k,v in attrs}; tag=tag.lower()
        if tag == "title": self.in_title=True
        if tag in ("h1","h2","h3","h4","h5","h6"): self.heading={"tag":tag,"text":""}; self.headings.append(self.heading)
        if tag == "meta" and a.get("name","").lower() in ("description","robots"): self.meta[a["name"].lower()]=a.get("content","").strip()
        if tag == "link" and "canonical" in {x.lower() for x in a.get("rel","").split()}: self.canonical=normalize_url(a.get("href"),self.base)
        if tag == "a" and a.get("href"):
            u=normalize_url(a["href"],self.base)
            if u: self.links.append(u)
        if tag == "img": self.images.append(a.get("alt"))
        if tag == "script" and a.get("type","").lower() == "application/ld+json": self.jsonld=True; self.jsonld_active=True; self.jsonld_text=""
    def handle_endtag(self, tag):
        if tag.lower() == "title": self.in_title=False
        if self.heading and tag.lower() == self.heading["tag"]: self.heading=None
        if tag.lower() == "script" and self.jsonld_active:
            self.jsonld_blocks.append(self.jsonld_text); self.jsonld_active=False
    def handle_data(self, data):
        if self.in_title: self.title += data
        if self.heading: self.heading["text"] += data
        if self.jsonld_active: self.jsonld_text += data

def extract_html(body, url):
    p=PageParser(url); p.feed(body.decode("utf-8","replace") if isinstance(body,bytes) else body)
    robots=p.meta.get("robots",""); links=sorted(set(p.links)); valid=[]; types=[]
    for block in p.jsonld_blocks:
        try:
            value=json.loads(block)
            for item in value if isinstance(value,list) else [value]:
                if isinstance(item,dict): valid.append(item); value_type=item.get("@type"); types.extend(value_type if isinstance(value_type,list) else [value_type] if value_type else [])
        except (TypeError,json.JSONDecodeError): pass
    return {"title":re.sub(r"\s+"," ",p.title).strip(),"meta_description":p.meta.get("description",""),"canonical":p.canonical,"headings":[{"tag":h["tag"],"text":re.sub(r"\s+"," ",h["text"]).strip()} for h in p.headings],"h1_count":sum(h["tag"] == "h1" for h in p.headings),"jsonld":p.jsonld,"jsonld_count":len(p.jsonld_blocks),"jsonld_valid_count":len(valid),"jsonld_types":sorted(set(types)),"robots":robots,"noindex":"noindex" in robots.lower(),"indexable":"noindex" not in robots.lower(),"internal_links":links,"links":links,"images":len(p.images),"missing_alt":sum(not (x or "").strip() for x in p.images)}

def _loc(node,base): return [normalize_url(x.text,base) for x in node.iter() if x.tag.rsplit("}",1)[-1]=="loc" and normalize_url(x.text,base)]
def parse_sitemap_document(body, base):
    try:
        root=ET.fromstring(body); kind=root.tag.rsplit("}",1)[-1]; locs=[u for u in _loc(root,base) if same_origin(u,base)]
        return {"kind":"index" if kind=="sitemapindex" else "urlset","children":locs if kind=="sitemapindex" else [],"urls":locs if kind!="sitemapindex" else []}
    except (ET.ParseError,TypeError): return {"kind":"invalid","children":[],"urls":[]}
def parse_sitemap(body, base):
    d=parse_sitemap_document(body,base); return d["urls"] + d["children"]

def parse_robots(body, origin):
    rp=robotparser.RobotFileParser(); robots_url=urllib.parse.urlunsplit(urllib.parse.urlsplit(origin)._replace(path="/robots.txt",query="")); rp.set_url(robots_url); rp.parse(body.splitlines())
    sm=[]
    for line in body.splitlines():
        if line.lower().startswith("sitemap:"):
            u=normalize_url(line.split(":",1)[1].strip(),origin)
            if u and same_origin(u,origin): sm.append(u)
    return rp, sorted(set(sm))

def _fetch(url, max_bytes=MAX_BYTES, timeout=TIMEOUT, fetcher=None):
    if fetcher: return fetcher(url)
    req=urllib.request.Request(url,headers={"User-Agent":USER_AGENT,"Accept":"text/html,application/xml,text/plain,*/*"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        data=r.read(max_bytes+1)
        if len(data)>max_bytes: raise ValueError("response exceeds byte limit")
        return getattr(r,"status",200),data,normalize_url(r.geturl(), url) or url, r.headers.get("Content-Type", "")

def _response(value, requested):
    if len(value) == 2:
        return value[0], value[1], requested, ""
    return value[0], value[1], value[2] or requested, value[3] if len(value) > 3 else ""

def crawl(start,max_pages=MAX_PAGES,fetcher=None,sleep=time.sleep):
    origin=normalize_url(start)
    if not origin: raise ValueError("url must be http or https without credentials")
    cap=max(1,min(int(max_pages or MAX_PAGES),MAX_PAGES)); root=urllib.parse.urlsplit(origin); robots_url=urllib.parse.urlunsplit(root._replace(path="/robots.txt",query="")); unavailable=[]
    try: _,rb,_,_=_response(_fetch(robots_url,fetcher=fetcher),robots_url); rp,declared=parse_robots(rb.decode("utf-8","replace"),origin)
    except Exception: rp=robotparser.RobotFileParser(); rp.parse([]); declared=[]; unavailable.append(robots_url)
    sitemap_urls=list(declared); if_default=urllib.parse.urlunsplit(root._replace(path="/sitemap.xml",query=""))
    if not sitemap_urls: sitemap_urls=[if_default]
    sitemap_members=set(); sitemap_status="unavailable"; sitemap_children=[]
    for sm in sitemap_urls[:10]:
        try:
            status,body,_,_=_response(_fetch(sm,fetcher=fetcher),sm)
            if status>=400: unavailable.append(sm); continue
            doc=parse_sitemap_document(body,origin)
            if doc["kind"]=="index": sitemap_children.extend(doc["children"][:20])
            elif doc["kind"]=="urlset": sitemap_members.update(doc["urls"]); sitemap_status="available"
        except Exception: unavailable.append(sm)
    for sm in sitemap_children:
        try:
            status,body,_,_=_response(_fetch(sm,fetcher=fetcher),sm)
            if status<400:
                doc=parse_sitemap_document(body,origin); sitemap_members.update(doc["urls"]); sitemap_status="available"
            else: unavailable.append(sm)
        except Exception: unavailable.append(sm)
    queue=list(dict.fromkeys([origin]+sorted(sitemap_members))); referrers={u: ("sitemap" if u != origin else origin) for u in queue}; seen=set(); pages=[]; broken=[]; excluded=[]; last=0
    while queue and len(pages)<cap:
        url=queue.pop(0)
        if url in seen: continue
        seen.add(url)
        if not same_origin(url,origin) or not rp.can_fetch(USER_AGENT,url): excluded.append({"url":url,"reason":"external_or_robots"}); continue
        wait=MIN_DELAY-(time.monotonic()-last)
        if wait>0: sleep(wait)
        try:
            status,body,final_url,content_type=_response(_fetch(url,fetcher=fetcher),url); last=time.monotonic()
            if status>=400: broken.append({"url":url,"source_url":referrers.get(url,origin),"status":status,"error":"http_error"}); continue
            if not same_origin(final_url, origin):
                excluded.append({"url":final_url,"reason":"external_redirect"})
                continue
            if content_type and "html" not in content_type.lower():
                excluded.append({"url": final_url, "reason": "non_html"})
                continue
            fields=extract_html(body[:MAX_BYTES],final_url); fields["sitemap_member"]=url in sitemap_members or final_url in sitemap_members
            pages.append({"requested_url":url,"final_url":final_url,"url":final_url,"redirected":final_url != url,"redirect_chain":[url, final_url] if final_url != url else [url],"status":status,"content_type":content_type,"fields":fields})
            for link in fields["internal_links"]:
                if same_origin(link,origin) and link not in seen:
                    referrers.setdefault(link, url); queue.append(link)
                elif not same_origin(link,origin): excluded.append({"url":link,"reason":"external"})
        except Exception as exc: last=time.monotonic(); broken.append({"url":url,"source_url":referrers.get(url,origin),"status":None,"error":type(exc).__name__})
    page_status = "unavailable" if not pages else ("partial" if broken or unavailable else "available")
    return {"status":page_status,"pages":pages,"broken_links":broken,"robots":{"status":"available" if robots_url not in unavailable else "unavailable"},"sitemap":{"status":sitemap_status,"members":sorted(sitemap_members),"unavailable":sorted(set(unavailable)-{robots_url})},"excluded":excluded,"bounded":{"max_pages":cap,"max_bytes":MAX_BYTES,"timeout":TIMEOUT,"min_delay":MIN_DELAY,"parser_version":PARSER_VERSION,"page_cap_reached":len(pages)>=cap and bool(queue),"queued_count":len(queue)}}

def evidence_id(rule,url,*_ignored): return "seo-"+hashlib.sha256(json.dumps([rule,normalize_url(url)],separators=(",",":"),sort_keys=True).encode()).hexdigest()[:24]
def make_findings(crawl_result):
    pages=crawl_result.get("pages",[]); out=[]; captured=now()
    def add(rule,url,observed,expected): out.append({"evidence_id":evidence_id(rule,url),"rule":rule,"url":url,"observed":observed,"expected":expected,"timestamp":captured})
    titles={}; descriptions={}
    for page in pages:
        f=page["fields"]; titles.setdefault(f["title"],[]).append(page["url"]); descriptions.setdefault(f["meta_description"],[]).append(page["url"])
        if not f["title"]: add("missing_title",page["url"],"missing","non-empty unique title")
        if not f["meta_description"]: add("missing_description",page["url"],"missing","non-empty unique description")
        if f["h1_count"]!=1: add("h1_count",page["url"],f["h1_count"],1)
        if not f["jsonld"]: add("missing_jsonld",page["url"],False,True)
        elif f["jsonld_valid_count"] != f["jsonld_count"]: add("invalid_jsonld",page["url"],f["jsonld_valid_count"],f["jsonld_count"])
        if crawl_result.get("sitemap",{}).get("status")=="available" and f["indexable"] and not f["sitemap_member"]: add("indexable_absent_sitemap",page["url"],False,True)
        if f["canonical"] != page["url"]: add("canonical_mismatch",page["url"],f["canonical"] or "missing",page["url"])
        if page.get("redirected") and page.get("requested_url") in crawl_result.get("sitemap",{}).get("members",[]): add("sitemap_redirect",page["requested_url"],page["final_url"],"final 2xx canonical URL in sitemap")
    for value,urls in titles.items():
        if value and len(urls)>1:
            for u in urls: add("duplicate_title",u,value,"unique title")
    for value,urls in descriptions.items():
        if value and len(urls)>1:
            for u in urls: add("duplicate_description",u,value,"unique description")
    for broken in crawl_result.get("broken_links",[]):
        add("broken_internal_link",broken["url"],{"source_url":broken.get("source_url"),"status":broken.get("status"),"error":broken.get("error")},"2xx")
    unavailable=crawl_result.get("sitemap",{}).get("unavailable",[])
    if crawl_result.get("sitemap",{}).get("status")!="available" and not unavailable: add("sitemap_missing",pages[0]["url"] if pages else "",crawl_result.get("sitemap",{}).get("status"),"available")
    for u in crawl_result.get("sitemap",{}).get("unavailable",[]): add("sitemap_unavailable",u,"unavailable","2xx XML sitemap")
    return out

def compare_runs(previous,current):
    if not previous:return {"available":False}
    old=previous if isinstance(previous,dict) else {}; new=current if isinstance(current,dict) else {}; delta={k:new.get("counts",{}).get(k,0)-old.get("counts",{}).get(k,0) for k in sorted(set(old.get("counts",{}))|set(new.get("counts",{})))}; return {"available":True,"count_delta":delta,"delta":delta,"finding_ids_added":sorted(set(new.get("finding_ids",[]))-set(old.get("finding_ids",[]))),"finding_ids_resolved":sorted(set(old.get("finding_ids",[]))-set(new.get("finding_ids",[])))}

def normalize_pagespeed(payload):
    if not isinstance(payload,dict) or not isinstance(payload.get("lighthouseResult"),dict): return {"status":"source_unavailable","error":"malformed PageSpeed response"}
    lr=payload["lighthouseResult"]; cats=lr.get("categories"); audits=lr.get("audits")
    if not isinstance(cats,dict) or not isinstance(audits,dict): return {"status":"source_unavailable","error":"missing PageSpeed fields"}
    metrics={k:(audits[k].get("numericValue") if isinstance(audits.get(k),dict) else None) for k in ("largest-contentful-paint","cumulative-layout-shift","total-blocking-time")}
    return {"status":"available","performance_score":cats.get("performance",{}).get("score") if isinstance(cats.get("performance"),dict) else None,"scores":{k:v.get("score") for k,v in cats.items() if isinstance(v,dict) and "score" in v},"core_web_vitals":metrics}

def query_pagespeed(url,api_key=None,fetcher=None):
    key=api_key if api_key is not None else os.environ.get("PAGESPEED_INSIGHTS_API_KEY")
    if not key:return {"status":"source_unavailable","error":"API key unavailable"}
    endpoint="https://www.googleapis.com/pagespeedonline/v5/runPagespeed?"+urllib.parse.urlencode({"url":url,"strategy":"mobile","key":key})
    try:
        payload=fetcher(endpoint) if fetcher else json.loads(urllib.request.urlopen(urllib.request.Request(endpoint,headers={"User-Agent":USER_AGENT}),timeout=TIMEOUT).read(MAX_BYTES)); return normalize_pagespeed(payload)
    except Exception as e:return {"status":"source_unavailable","error":type(e).__name__}

def _b64(data):return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
def sign_jwt(header,claims,private_key):
    unsigned=_b64(json.dumps(header,separators=(",",":")).encode())+"."+_b64(json.dumps(claims,separators=(",",":")).encode()); r,w=os.pipe()
    try:
        os.write(w,private_key.encode()); os.close(w); proc=subprocess.run(["openssl","dgst","-sha256","-sign",f"/dev/fd/{r}"],input=unsigned.encode(),capture_output=True,pass_fds=(r,))
    finally:
        try:os.close(w)
        except OSError:pass
        try:os.close(r)
        except OSError:pass
    if proc.returncode:raise RuntimeError("JWT signing failed")
    return unsigned+"."+_b64(proc.stdout)

def google_access(service_account_file=SERVICE_ACCOUNT_FILE):
    try:
        with open(service_account_file) as f:a=json.load(f)
        if not all(isinstance(a.get(k),str) for k in ("client_email","private_key")):raise ValueError("invalid service account")
        t=int(time.time()); jwt=sign_jwt({"alg":"RS256","typ":"JWT"},{"iss":a["client_email"],"scope":"https://www.googleapis.com/auth/webmasters.readonly https://www.googleapis.com/auth/analytics.readonly","aud":"https://oauth2.googleapis.com/token","iat":t,"exp":t+3600},a["private_key"])
        req=urllib.request.Request("https://oauth2.googleapis.com/token",data=urllib.parse.urlencode({"grant_type":"urn:ietf:params:oauth:grant-type:jwt-bearer","assertion":jwt}).encode())
        payload=json.loads(urllib.request.urlopen(req,timeout=TIMEOUT).read(MAX_BYTES)); return {"status":"available","token":payload["access_token"]} if payload.get("access_token") else {"status":"source_unavailable","error":"token missing"}
    except Exception as e:return {"status":"source_unavailable","error":type(e).__name__}

def google_metric(url,token,payload,fetcher=None):
    if not token:return {"status":"source_unavailable","error":"access unavailable"}
    if urllib.parse.urlsplit(url).hostname not in ("searchconsole.googleapis.com","analyticsdata.googleapis.com"):return {"status":"source_unavailable","error":"untrusted API host"}
    try:
        if fetcher:response=fetcher(url,token,payload)
        else:
            req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"}); response=json.loads(urllib.request.urlopen(req,timeout=TIMEOUT).read(MAX_BYTES))
        return {"status":"available","data":response} if isinstance(response,dict) else {"status":"source_unavailable","error":"malformed response"}
    except Exception as e:return {"status":"source_unavailable","error":type(e).__name__}

def normalize_gsc(payload):
    if not isinstance(payload,dict) or "error" in payload or not ("rows" in payload or "responseAggregationType" in payload):
        return {"status":"source_unavailable","error":"malformed GSC response"}
    rows = [row for row in (payload.get("rows") or []) if isinstance(row, dict)][:250]
    clicks = sum(float(row.get("clicks", 0)) for row in rows)
    impressions = sum(float(row.get("impressions", 0)) for row in rows)
    summaries = [{
        "keys": [str(value)[:500] for value in (row.get("keys") or [])[:2]],
        "clicks": float(row.get("clicks", 0)),
        "impressions": float(row.get("impressions", 0)),
        "ctr": float(row.get("ctr", 0)),
        "position": float(row.get("position", 0)),
    } for row in rows]
    return {
        "status":"available",
        "clicks":clicks,
        "impressions":impressions,
        "ctr":clicks/impressions if impressions else 0,
        "weighted_average_position":sum(float(row.get("position",0))*float(row.get("impressions",0)) for row in rows)/impressions if impressions else 0,
        "rows":len(rows),
        "row_summaries":summaries,
    }

def normalize_ga4(payload):
    if not isinstance(payload,dict) or "error" in payload or not isinstance(payload.get("metricHeaders"),list):
        return {"status":"source_unavailable","error":"malformed GA4 response"}
    dimensions=[h.get("name") for h in payload.get("dimensionHeaders",[]) if isinstance(h,dict)]
    metrics=[h.get("name") for h in payload.get("metricHeaders",[]) if isinstance(h,dict)]
    totals={name:0 for name in metrics}
    summaries=[]
    for row in (payload.get("rows") or [])[:250]:
        if not isinstance(row,dict):
            continue
        values={}
        for name,value in zip(metrics,row.get("metricValues",[])):
            try:
                number=float(value.get("value",0))
            except (AttributeError,TypeError,ValueError):
                number=0
            totals[name]=totals.get(name,0)+number
            values[name]=number
        summaries.append({
            "dimensions":{name:str(value.get("value", ""))[:500] for name,value in zip(dimensions,row.get("dimensionValues",[]))},
            "metrics":values,
        })
    return {"status":"available","rows":len(summaries),"metrics":metrics,"totals":totals,"row_summaries":summaries}
