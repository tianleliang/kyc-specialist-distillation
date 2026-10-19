> **Note:** this file is the retrieval log written while the corpus was being collected; some "in repo?" marks predate the manual downloads. The corpus actually used is exactly the files in this folder (14 files, ~420k tokens: FATF, FinCEN CDD rule, ICAO 9303 parts 3–5, OFAC FAQ, Wolfsberg, sanctions-list structure, address formats).

# Domain corpus: sources

Retrieved 2026-10-17 from a cloud session whose egress proxy **denied CONNECT (HTTP 403, policy)** to every primary publisher:
fatf-gafi.org, govinfo.gov, federalregister.gov, ecfr.gov, regulations.gov, fincen.gov, icao.int, wolfsberg-group.org,
db.wolfsberg-group.org, wolfsberg-principles.com, ofac.treasury.gov / treasury.gov, upu.int, webgate.ec.europa.eu,
web.archive.org, archive.org, en.wikipedia.org, huggingface.co, jsdelivr, unpkg. WebFetch could not resolve them either.
Only `raw.githubusercontent.com`, PyPI and npm were reachable. **None of the primary documents could be fetched.**

**To complete the corpus, run `bash step3_domain_adapter/corpus/fetch_corpus.sh` on the laptop.** It fetches each PDF, converts it with `pdftotext -layout`
to `<slug>.txt` (PDFs are gitignored), and rebuilds the GitHub-sourced files. URLs marked *unverified* were written from memory
because the hosts could not be checked; if one 404s, use the landing page in the notes and update the script.

Safety: no sanctions-list entries or personal data of real people are stored. OpenSanctions dataset YAMLs are cut down to
descriptive metadata (their `lookups` / `assertions` / `names` sections, which can name real entities, are removed). One
candidate (moov-io/watchman README) was **excluded** because its examples include a real SDN-listed person. The MRZ examples
in the ICAO file are ICAO's fictional specimens ("ERIKSSON ANNA MARIA", state "UTO").

**Update (lunch, Session M):** the proxy still blocks every primary publisher, and WebFetch could not resolve them either. URLs were re-checked by **web search**. A URL marked **VERIFIED-SEARCH** appeared as an exact search result with a matching title or snippet; it was **not downloaded**. **UNVERIFIED** means inferred or written from memory. `fetch_corpus.sh` now tries several URLs per document (new path first, old path as fallback), checks that a PDF really is a PDF, and prints a sha256 prefix per file. Copy those hashes into this table after the laptop fetch. ICAO moved its PDFs to `/sites/default/files/publications/DocSeries/`. Wolfsberg files now live under UUID asset paths on `db.wolfsberg-group.org`. FATF's consolidated Recommendations were last updated in June 2026. Licensing: the FATF and ICAO PDFs say "no reproduction without written permission", so the PDFs stay gitignored and only the extracted text is kept (for training).

Added: `wolfsberg_negative_news_faq_2022` (adverse-media text, which the brief lists), `eu_amld4_2015_849` (the EU PEP definitions in Art. 3(9)-(11)) and `ofac_consolidated_format_spec`. Dropped: Wolfsberg correspondent-banking principles. They are about bank-to-bank relationships, not individual onboarding, and their URL could not be found.

| file | title | publisher | URL(s) in fetch_corpus.sh (first that works wins) | URL status (2026-10-17) | doc date | in repo? |
|---|---|---|---|---|---|---|
| `fatf_recommendations.txt` | FATF Recommendations (incl. Interpretive Notes) | FATF | https://www.fatf-gafi.org/content/dam/fatf-gafi/recommendations/fatf-recommendations-2012.pdf ; fallback .../FATF%20Recommendations%202012.pdf. Landing: https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Fatf-recommendations.html | VERIFIED-SEARCH (both) | 2012, updated June 2026 | no, laptop fetch |
| `fatf_pep_guidance_2013.txt` | FATF Guidance: Politically Exposed Persons (R.12 and R.22) | FATF | https://www.fatf-gafi.org/content/dam/fatf-gafi/guidance/Guidance-PEP-Rec12-22.pdf. Landing: https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Peps-r12-r22.html | VERIFIED-SEARCH | June 2013 | no, laptop fetch |
| `fincen_cdd_final_rule_2016.txt` | Customer Due Diligence Requirements for Financial Institutions, 81 FR 29398 | FinCEN | https://www.govinfo.gov/content/pkg/FR-2016-05-11/pdf/2016-10567.pdf | VERIFIED-SEARCH | 2016-05-11 | **yes** |
| `ecfr_31cfr1010_230.txt` | 31 CFR 1010.230 (current codified text) | eCFR | https://www.ecfr.gov/api/versioner/v1/full/{date}/title-31.xml?part=1010&section=1010.230 | UNVERIFIED (API pattern) | current | no |
| `icao9303_p3.txt` | ICAO Doc 9303 Part 3: Specifications common to all MRTDs | ICAO | https://www.icao.int/sites/default/files/publications/DocSeries/9303_p3_cons_en.pdf ; fallback https://www.icao.int/publications/Documents/9303_p3_cons_en.pdf. Landing: https://www.icao.int/publications/doc-series/doc-9303 | VERIFIED-SEARCH (new path) | 8th ed. 2021, amended 2022/2024 | no, laptop fetch |
| `icao9303_p4.txt` | ICAO Doc 9303 Part 4: TD3 passports | ICAO | .../DocSeries/9303_p4_cons_en.pdf ; fallback old path | VERIFIED-SEARCH (new path) | 8th ed., amended 2024/2026 | no, laptop fetch |
| `icao9303_p5.txt` | ICAO Doc 9303 Part 5: TD1 cards | ICAO | .../DocSeries/9303_p5_cons_en.pdf ; fallback old path | VERIFIED-SEARCH (new path) | 8th ed. | no, laptop fetch |
| `icao9303_mrz_thirdparty.txt` | Third-party MRZ descriptions (Arg0s1080/mrz, cheminfo/mrz, PassportEye READMEs) | GitHub | raw.githubusercontent.com (see script) | fetched OK | current | **yes** |
| `wolfsberg_pep_guidance_2017.txt` | Wolfsberg Guidance on PEPs | Wolfsberg Group | https://db.wolfsberg-group.org/assets/9c6630de-69a8-4f55-9289-4db938938e34/Wolfsberg%20Guidance%20on%20PEPs.pdf. Landing: https://wolfsberg-group.org/resources/general/50 | VERIFIED-SEARCH | 2017 | no, laptop fetch |
| `wolfsberg_sanctions_screening_2019.txt` | Wolfsberg Guidance on Sanctions Screening | Wolfsberg Group | https://db.wolfsberg-group.org/assets/4b6c2db6-696d-492e-bdd5-c51552708597/Wolfsberg%20Guidance%20on%20Sanctions%20Screening.pdf. Landing: https://wolfsberg-group.org/resources/168/53 | VERIFIED-SEARCH (two file sizes are listed, so there may be two versions) | 2019 | no, laptop fetch |
| `wolfsberg_negative_news_faq_2022.txt` | Wolfsberg Negative News Screening FAQs | Wolfsberg Group | https://db.wolfsberg-group.org/assets/b3652a98-4bc6-4b42-9f05-e378a4adbd95/Negative%20News%20Screening%20FAQs%20(2022).pdf. Landing: https://wolfsberg-group.org/resources/168/118 | VERIFIED-SEARCH | 2022-05-11 | no, laptop fetch |
| `eu_amld4_2015_849.txt` | Directive (EU) 2015/849 (4th AMLD) | EUR-Lex | https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX%3A32015L0849 (original text; consolidated: https://eur-lex.europa.eu/eli/dir/2015/849) | VERIFIED-SEARCH | 2015 | no, laptop fetch |
| `ofac_legacy_file_format_spec.txt` | OFAC SDN fixed-width/CSV data specification (dat_spec) | OFAC | https://ofac.treasury.gov/system/files/126/dat_spec.txt ; https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/DAT_SPEC.TXT ; https://www.treasury.gov/ofac/downloads/dat_spec.txt | UNVERIFIED (all three; the first was quoted in an OFAC FAQ). Avoid `home.treasury.gov/.../dat_spec_0.txt`, which a search snippet shows is not the spec | n/a | no |
| `ofac_consolidated_format_spec.txt` | OFAC consolidated (non-SDN) list data specification | OFAC | https://www.treasury.gov/ofac/downloads/consolidated/cons_dat_spec.txt | VERIFIED-SEARCH | n/a | no |
| `sanctions_list_structure.txt` | OpenSanctions dataset metadata + FollowTheMoney schemas | OpenSanctions (GitHub) | raw.githubusercontent.com (see script) | fetched OK | current | **yes** |
| `address_formats.txt` | OpenCage address-formatting templates + READMEs | OpenCage, Google (GitHub) | raw.githubusercontent.com (see script) | fetched OK | current | **yes** |
| (EU consolidated list XSD) | EU Financial Sanctions Files XML schema | European Commission | https://webgate.ec.europa.eu/fsd/fsf (portal) | blocked; not in script | n/a | no |
| (UPU addressing docs) | UPU S42 | UPU | https://www.upu.int/en/postal-solutions/programmes-services/addressing-solutions | blocked; S42 is not free; not in script | n/a | no |

## Manually downloaded (Sat 2026-10-17, browser; automated fetch was blocked by every publisher)
PDFs kept locally in `corpus/manual_pdfs/` (gitignored); text extracted with `pypdf` into the `.txt` files below.

| File | Source document | Publisher |
|---|---|---|
| `fatf_recommendations_2012.txt` | The FATF Recommendations (International Standards on Combating ML/TF/PF), 2012, as updated | FATF |
| `fatf_pep_guidance_2013.txt` | FATF Guidance: Politically Exposed Persons (Recommendations 12 and 22), 2013 | FATF |
| `icao9303_p3.txt` | ICAO Doc 9303 Machine Readable Travel Documents, Part 3: Specifications Common to all MRTDs (incl. check digits) | ICAO |
| `icao9303_p4.txt` | ICAO Doc 9303, Part 4: Machine Readable Passports (TD3) | ICAO |
| `icao9303_p5.txt` | ICAO Doc 9303, Part 5: TD1 size MROTDs (ID cards) | ICAO |
| `wolfsberg_pep_statement_2017.txt` | Wolfsberg Group Statement / Guidance on PEPs, May 2017 | Wolfsberg Group |
| `wolfsberg_sanctions_screening.txt` | Wolfsberg Guidance on Sanctions Screening | Wolfsberg Group |
| `wolfsberg_negative_news_faq_2022.txt` | Wolfsberg Negative News Screening FAQs, 2022 | Wolfsberg Group |
| `ofac_faq_122.txt` | OFAC FAQ 122 (alias / identifier conventions) | US Treasury OFAC |
| `ofac_technical_actions.txt` | OFAC technical actions page (list format changes) | US Treasury OFAC |

Public documents, used only as unlabeled text for the stage-2 domain adapter. No personal data is used.
