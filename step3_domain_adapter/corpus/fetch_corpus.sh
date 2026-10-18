#!/usr/bin/env bash
# Re-fetch the domain corpus into step3_domain_adapter/corpus/ (text only; PDFs are gitignored).
# Usage: bash step3_domain_adapter/corpus/fetch_corpus.sh            (run from the repo root or anywhere)
# Needs: curl, pdftotext (poppler-utils), python3.
#
# URL status (checked 2026-10-17 from a cloud session whose proxy blocks these hosts, so nothing
# below was downloaded from there):
#   VERIFIED-SEARCH  the exact URL appeared in a web-search result for the document, with a matching
#                    title/snippet, in that session. Not downloaded; hashes are recorded on first fetch.
#   UNVERIFIED       written from memory or inferred from a URL pattern. Try it; if it 404s, use the
#                    landing page in SOURCES.md and update the line here.
# pdf() takes several URLs and uses the first that works, so old paths stay as fallbacks.
set -uo pipefail
OUT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
UA="Mozilla/5.0 (zorbe-kyc corpus fetch)"
FAILED=()

pdf() {  # pdf <slug> <url> [fallback-url ...]
  local slug="$1"; shift
  for url in "$@"; do
    if curl -fsSL --retry 2 -m 120 -A "$UA" -o "$OUT/$slug.pdf" "$url" && head -c 5 "$OUT/$slug.pdf" | grep -q '%PDF'; then
      pdftotext -layout -enc UTF-8 "$OUT/$slug.pdf" "$OUT/$slug.txt" \
        && sed -i 's/\f/\n/g; s/[[:space:]]*$//' "$OUT/$slug.txt" \
        && echo "ok   $slug ($(wc -c <"$OUT/$slug.txt") bytes, sha256 $(sha256sum "$OUT/$slug.pdf" | cut -c1-16)) <- $url"
      return 0
    fi
    echo "     $slug: $url failed, trying next" >&2
  done
  echo "FAIL $slug"; FAILED+=("$slug"); rm -f "$OUT/$slug.pdf"
}

txt() {  # txt <slug> <url> [fallback-url ...]   (plain-text documents)
  local slug="$1"; shift
  for url in "$@"; do
    if curl -fsSL --retry 2 -m 60 -A "$UA" -o "$OUT/$slug.txt" "$url" && ! grep -qi '<html' "$OUT/$slug.txt"; then
      echo "ok   $slug <- $url"; return 0
    fi
  done
  echo "FAIL $slug"; FAILED+=("$slug"); rm -f "$OUT/$slug.txt"
}

# --- FATF -------------------------------------------------------------------
# Landing: https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Fatf-recommendations.html
pdf fatf_recommendations \
  "https://www.fatf-gafi.org/content/dam/fatf-gafi/recommendations/fatf-recommendations-2012.pdf" \
  "https://www.fatf-gafi.org/content/dam/fatf-gafi/recommendations/FATF%20Recommendations%202012.pdf"   # VERIFIED-SEARCH (both; first = June 2026 update)
# Landing: https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Peps-r12-r22.html
pdf fatf_pep_guidance_2013 \
  "https://www.fatf-gafi.org/content/dam/fatf-gafi/guidance/Guidance-PEP-Rec12-22.pdf"                  # VERIFIED-SEARCH

# --- FinCEN CDD final rule (81 FR 29398, 11 May 2016, FR Doc. 2016-10567) ------
pdf fincen_cdd_final_rule_2016 \
  "https://www.govinfo.gov/content/pkg/FR-2016-05-11/pdf/2016-10567.pdf"                                # VERIFIED-SEARCH
# Current codified text, 31 CFR 1010.230 (beneficial ownership requirements):                          # UNVERIFIED (API pattern)
curl -fsSL --retry 2 -m 60 -A "$UA" -o "$TMP/ecfr.xml" \
  "https://www.ecfr.gov/api/versioner/v1/full/$(date +%F)/title-31.xml?part=1010&section=1010.230" \
  && python3 -I -c 'import re,sys,html; t=open(sys.argv[1],encoding="utf-8").read(); t=re.sub(r"<[^>]+>","\n",t); t=html.unescape(re.sub(r"\n\s*\n+","\n\n",t)); open(sys.argv[2],"w",encoding="utf-8").write(t.strip()+"\n")' "$TMP/ecfr.xml" "$OUT/ecfr_31cfr1010_230.txt" \
  && echo "ok   ecfr_31cfr1010_230" || { echo "FAIL ecfr_31cfr1010_230"; FAILED+=(ecfr_31cfr1010_230); }

# --- ICAO Doc 9303, 8th ed. (2021, with amendments) ----------------------------
# Landing: https://www.icao.int/publications/doc-series/doc-9303  (ICAO moved its files in 2025)
pdf icao9303_p3 "https://www.icao.int/sites/default/files/publications/DocSeries/9303_p3_cons_en.pdf" \
                "https://www.icao.int/publications/Documents/9303_p3_cons_en.pdf"                       # VERIFIED-SEARCH (first); old path fallback
pdf icao9303_p4 "https://www.icao.int/sites/default/files/publications/DocSeries/9303_p4_cons_en.pdf" \
                "https://www.icao.int/publications/Documents/9303_p4_cons_en.pdf"                       # VERIFIED-SEARCH (first)
pdf icao9303_p5 "https://www.icao.int/sites/default/files/publications/DocSeries/9303_p5_cons_en.pdf" \
                "https://www.icao.int/publications/Documents/9303_p5_cons_en.pdf"                       # VERIFIED-SEARCH (first)

# --- Wolfsberg Group (asset UUID paths on db.wolfsberg-group.org) ------------
# Library: https://wolfsberg-group.org/resources
pdf wolfsberg_pep_guidance_2017 \
  "https://db.wolfsberg-group.org/assets/9c6630de-69a8-4f55-9289-4db938938e34/Wolfsberg%20Guidance%20on%20PEPs.pdf"   # VERIFIED-SEARCH
pdf wolfsberg_sanctions_screening_2019 \
  "https://db.wolfsberg-group.org/assets/4b6c2db6-696d-492e-bdd5-c51552708597/Wolfsberg%20Guidance%20on%20Sanctions%20Screening.pdf"   # VERIFIED-SEARCH
pdf wolfsberg_negative_news_faq_2022 \
  "https://db.wolfsberg-group.org/assets/b3652a98-4bc6-4b42-9f05-e378a4adbd95/Negative%20News%20Screening%20FAQs%20(2022).pdf"   # VERIFIED-SEARCH (adverse-media text for the brief)

# --- EU 4th AML Directive 2015/849 (PEP definitions, Art. 3(9)-(11); CDD/EDD articles) ---------
pdf eu_amld4_2015_849 "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX%3A32015L0849"     # VERIFIED-SEARCH

# --- OFAC list *format* documentation (no list entries) ----------------------
txt ofac_legacy_file_format_spec \
  "https://ofac.treasury.gov/system/files/126/dat_spec.txt" \
  "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/DAT_SPEC.TXT" \
  "https://www.treasury.gov/ofac/downloads/dat_spec.txt"                                                # UNVERIFIED (all three)
txt ofac_consolidated_format_spec \
  "https://www.treasury.gov/ofac/downloads/consolidated/cons_dat_spec.txt"                              # VERIFIED-SEARCH

# --- Third-party spec descriptions on GitHub (worked on 2026-10-17) ----------
R=https://raw.githubusercontent.com
gh_get() { curl -fsSL --retry 2 -m 60 -o "$TMP/$1" "$R/$2" || { echo "FAIL $2"; FAILED+=("$1"); }; }
gh_get mrz_readme.md           Arg0s1080/mrz/master/README.md
gh_get cheminfo_mrz.md         cheminfo/mrz/main/README.md
gh_get passporteye.rst         konstantint/PassportEye/master/README.rst
gh_get os_ofac_sdn.yml         opensanctions/opensanctions/main/datasets/us/ofac/us_ofac_sdn.yml
gh_get os_eu_fsf.yml           opensanctions/opensanctions/main/datasets/eu/fsf/eu_fsf.yml
gh_get os_un_sc.yml            opensanctions/opensanctions/main/datasets/_global/un_sc_sanctions/un_sc_sanctions.yml
for s in Person Sanction Passport Identification Address; do
  gh_get "ftm_${s,,}.yaml"     "opensanctions/followthemoney/main/followthemoney/schema/$s.yaml"
done
gh_get addrfmt_readme.md       OpenCageData/address-formatting/master/README.md
gh_get addrfmt_worldwide.yaml  OpenCageData/address-formatting/master/conf/countries/worldwide.yaml
gh_get libaddr_readme.md       google/libaddressinput/master/README.md

cat > "$TMP/build.py" <<'PY'
import sys, re, pathlib
raw = pathlib.Path(sys.argv[1]); out = pathlib.Path(sys.argv[2])
KEEP = {"title","summary","description","publisher","url","data","coverage"}
def meta_only(text):
    # Keep descriptive top-level keys only. lookups/assertions/names can contain real entities.
    res, keep = [], False
    for line in text.splitlines():
        m = re.match(r'^([a-z_]+):', line)
        if m: keep = m.group(1) in KEEP
        if keep and not line.lstrip().startswith('#'): res.append(line)
    return "\n".join(res)
R = "https://raw.githubusercontent.com/"
def hdr(t, u): return f"\n\n{'='*78}\n{t}\nSource: {u}\n{'='*78}\n\n"
docs = {
 "icao9303_mrz_thirdparty.txt": [
  ("mrz (Python) README: ICAO 9303 MRZ TD1/TD2/TD3/MRVA/MRVB generation and checking", "Arg0s1080/mrz/master/README.md", "mrz_readme.md", None),
  ("mrz (JavaScript, cheminfo) README: MRZ formats and parsing", "cheminfo/mrz/main/README.md", "cheminfo_mrz.md", None),
  ("PassportEye README: MRZ recognition", "konstantint/PassportEye/master/README.rst", "passporteye.rst", None)],
 "sanctions_list_structure.txt": [
  ("OpenSanctions dataset metadata: US OFAC SDN (metadata only; lookups/assertions removed)", "opensanctions/opensanctions/main/datasets/us/ofac/us_ofac_sdn.yml", "os_ofac_sdn.yml", meta_only),
  ("OpenSanctions dataset metadata: EU Financial Sanctions Files (metadata only)", "opensanctions/opensanctions/main/datasets/eu/fsf/eu_fsf.yml", "os_eu_fsf.yml", meta_only),
  ("OpenSanctions dataset metadata: UN Security Council Consolidated List (metadata only)", "opensanctions/opensanctions/main/datasets/_global/un_sc_sanctions/un_sc_sanctions.yml", "os_un_sc.yml", meta_only)]
  + [(f"FollowTheMoney schema: {s}", f"opensanctions/followthemoney/main/followthemoney/schema/{s}.yaml", f"ftm_{s.lower()}.yaml", None)
     for s in ["Person","Sanction","Passport","Identification","Address"]],
 "address_formats.txt": [
  ("OpenCage address-formatting README", "OpenCageData/address-formatting/master/README.md", "addrfmt_readme.md", None),
  ("OpenCage address-formatting: per-country templates (conf/countries/worldwide.yaml)", "OpenCageData/address-formatting/master/conf/countries/worldwide.yaml", "addrfmt_worldwide.yaml", None),
  ("Google libaddressinput README", "google/libaddressinput/master/README.md", "libaddr_readme.md", None)],
}
for name, parts in docs.items():
    buf = []
    for t, u, fn, fx in parts:
        p = raw / fn
        if not p.exists(): continue
        s = p.read_text(encoding="utf-8", errors="replace")
        buf.append(hdr(t, R + u) + (fx(s) if fx else s).strip() + "\n")
    (out / name).write_text("".join(buf).lstrip(), encoding="utf-8")
    print("ok  ", name, (out / name).stat().st_size, "bytes")
PY
python3 -I "$TMP/build.py" "$TMP" "$OUT"

echo; [ ${#FAILED[@]} -eq 0 ] && echo "All sources fetched." || echo "Failed: ${FAILED[*]}"
