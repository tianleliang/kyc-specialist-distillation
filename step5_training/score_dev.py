import json, sys, collections, glob, os
gold={json.loads(l)["case_id"]:json.loads(l) for l in open("data/dev/cases.jsonl",encoding="utf-8")}
def P(x):
    try: return json.loads(x) if isinstance(x,str) else x
    except Exception: return None
F=["name_status","date_of_birth_status","document_number_status","expiry_status","address_status"]
print(f"{'run (150 dev)':40s} {'valid':>5} {'dec':>5} {'risk':>5} {'fields':>6} {'actR':>5} {'scr':>5}")
for d in sorted(glob.glob("outputs/student/*__dev")):
    pr={json.loads(l)["case_id"]:P(json.loads(l)["output"]) for l in open(d+"/predictions.jsonl",encoding="utf-8")}
    n=len(gold); ok=lambda c: isinstance(pr.get(c),dict)
    acc=lambda f: sum(ok(c) and pr[c].get(f)==g["expected"][f] for c,g in gold.items())/n*100
    fa=sum(acc(f) for f in F)/len(F)
    tp=fn=0
    for c,g in gold.items():
        ga=set(g["expected"]["required_actions"]); pa=set(pr[c].get("required_actions",[])) if ok(c) else set()
        tp+=len(ga&pa); fn+=len(ga-pa)
    scr=sum(ok(c) and sorted((h["hit_id"],h["disposition"]) for h in pr[c].get("screening",[]))==sorted((h["hit_id"],h["disposition"]) for h in g["expected"]["screening"]) for c,g in gold.items())/n*100
    print(f"{os.path.basename(d)[:40]:40s} {sum(ok(c) for c in gold)/n*100:5.0f} {acc('decision'):5.1f} {acc('risk_tier'):5.1f} {fa:6.1f} {tp/max(1,tp+fn)*100:5.1f} {scr:5.1f}")
