import re,html,sys
md=open(sys.argv[1],encoding="utf-8").read()
def inline(t):
    t=html.escape(t); t=re.sub(r"\*\*(.+?)\*\*",r"<b>\1</b>",t); t=re.sub(r"`(.+?)`",r"<code>\1</code>",t); return t
blocks=[];pend=[];lines=md.split("\n");i=0
while i<len(lines):
    l=lines[i]
    if l.startswith("|"):
        rows=[]
        while i<len(lines) and lines[i].startswith("|"):
            rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")]); i+=1
        t="<table><thead><tr>"+"".join(f"<th>{inline(c)}</th>" for c in rows[0])+"</tr></thead><tbody>"+"".join("<tr>"+"".join(f"<td>{inline(c)}</td>" for c in r)+"</tr>" for r in rows[2:])+"</tbody></table>"
        blocks.append("<div class='blk'>"+"".join(pend)+t+"</div>"); pend=[]; continue
    m=re.match(r"(#+) (.*)",l)
    if m:
        n=len(m.group(1))
        if n==1: blocks.append(f"<h1>{inline(m.group(2))}</h1>")
        else: pend.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
    elif l.strip(): pend.append(f"<p>{inline(l)}</p>")
    i+=1
blocks+=pend
css="""@page{size:A4 landscape;margin:11mm}body{font-family:Segoe UI,Arial,sans-serif;font-size:8.4pt;color:#111}
h1{font-size:16pt;margin:0 0 6px}h2{font-size:11.5pt;margin:12px 0 4px;border-bottom:1px solid #ccc;padding-bottom:2px}h3{font-size:10pt;margin:8px 0 4px}
.blk{break-inside:avoid;page-break-inside:avoid}table{border-collapse:collapse;width:100%;margin:4px 0 8px}th,td{border:1px solid #bbb;padding:2.5px 4px;text-align:left;vertical-align:top}
th{background:#f0f0f0;font-weight:600}p{margin:4px 0}code{font-size:8pt}"""
open(sys.argv[2],"w",encoding="utf-8").write(f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{''.join(blocks)}</body></html>")
