"""30-item KYC knowledge probe for the domain adapter: MRZ rules, PEP / CDD definitions, list and
alias conventions, address formats. Synthetic questions, each answerable from a corpus document.

Format: multiple choice, 4 options, scored by length-normalised option log-likelihood ("cloze"
scoring, as for base-model benchmarks), so it needs no instruction following and works the same
before and after continued pretraining. ``scores()`` reports accuracy and the mean margin
(log-prob of the right option minus the best wrong one), which moves before accuracy does.

Each item names the corpus file that answers it (``source``) and a short phrase that should occur
there (``evidence``). ``answerability()`` checks the phrase against the corpus actually on disk;
measure_adapter.py reports accuracy on all 30 items and on the answerable subset, so a missing
document (e.g. ICAO parts not fetched yet) cannot be mistaken for a failed adapter.

The four check-digit items are computed with ``step1_data_generation.lib.mrz.check_digit`` on
invented strings (no real document numbers).
"""
from __future__ import annotations

import random
import re
from pathlib import Path

from step1_data_generation.lib.mrz import check_digit

PROMPT = "Question: {q}\nAnswer:"


def _cd_items() -> list[dict]:
    rng = random.Random("probe-check-digits")
    out = []
    for i, s in enumerate(["K4Q72190", "ZT0581336", "940217", "310829"]):
        right = check_digit(s)
        wrong = rng.sample([d for d in "0123456789" if d != right], 3)
        opts = [right] + wrong
        rng.shuffle(opts)
        out.append({"id": f"mrz_cd_{i + 1}", "topic": "mrz",
                    "question": f"Using the ICAO 9303 check digit method (weights 7, 3, 1; letters A=10 to Z=35; "
                                f"the filler counts as 0), the check digit for the MRZ field '{s}' is",
                    "options": opts, "answer": opts.index(right), "source": "icao9303_p3", "evidence": "check digit"})
    return out


_ITEMS = [
    # ---- MRZ (ICAO 9303) ------------------------------------------------------
    ("mrz_filler", "mrz", "In an ICAO 9303 machine readable zone, unused character positions are filled with the character",
     ["<", "#", "0", "*"], 0, "icao9303_p3", "filler"),
    ("mrz_td3_shape", "mrz", "The machine readable zone of a TD3-size passport consists of",
     ["two lines of 44 characters", "three lines of 30 characters", "two lines of 36 characters",
      "one line of 90 characters"], 0, "icao9303_p4", "44"),
    ("mrz_td1_shape", "mrz", "The machine readable zone of a TD1-size identity card consists of",
     ["three lines of 30 characters", "two lines of 44 characters", "two lines of 36 characters",
      "four lines of 22 characters"], 0, "icao9303_p5", "30"),
    ("mrz_date", "mrz", "In the machine readable zone, a date of birth is written in the format",
     ["YYMMDD", "DDMMYY", "MMDDYY", "DD.MM.YYYY"], 0, "icao9303_p3", "YYMMDD"),
    ("mrz_weights", "mrz", "The weighting factors used to compute an ICAO 9303 check digit repeat in the sequence",
     ["7, 3, 1", "1, 2, 1", "3, 1", "9, 7, 3"], 0, "icao9303_p3", "7, 3, 1"),
    ("mrz_name_sep", "mrz", "In the name field of the machine readable zone, the primary identifier (surname) is "
     "separated from the secondary identifier (given names) by",
     ["two filler characters (<<)", "a comma", "a single space", "a hyphen"], 0, "icao9303_p3", "<<"),
    # ---- PEP / CDD ----------------------------------------------------------------
    ("pep_rec12", "pep", "FATF Recommendation 12 sets out the measures financial institutions must apply to",
     ["politically exposed persons", "wire transfers", "correspondent banking", "record keeping"], 0,
     "fatf_recommendations", "Politically exposed persons"),
    ("pep_foreign_measures", "pep", "For a customer who is a foreign politically exposed person, the FATF "
     "Recommendations require, among other measures,",
     ["senior management approval for establishing the business relationship", "automatic refusal of the customer",
      "no measures beyond standard due diligence", "a court order before opening the account"], 0,
     "fatf_recommendations", "senior management approval"),
    ("pep_family", "pep", "The FATF requirements for politically exposed persons also apply to",
     ["family members and close associates of such persons", "all civil servants regardless of seniority",
      "only the person holding office, never relatives", "any customer from a high-income country"], 0,
     "fatf_pep_guidance_2013", "close associates"),
    # reworded 2026-10-17: the original stem appeared verbatim in the FATF Recommendations text added to the
    # corpus, so it tested string recall rather than knowledge (test_probe_not_in_corpus caught it)
    ("pep_intl_org", "pep", "Under FATF terms, a senior manager of a body such as a UN agency or a development bank "
     "(someone holding a leading role there now or in the past) is treated as",
     ["a politically exposed person", "a sanctioned person", "a low-risk customer by definition",
      "outside the scope of customer due diligence"], 0, "fatf_pep_guidance_2013", "international organisation"),
    ("pep_not_criminal", "pep", "Under the FATF and Wolfsberg guidance, the fact that a customer is a politically "
     "exposed person",
     ["does not by itself suggest involvement in criminal activity", "is sufficient grounds to reject the customer",
      "must be reported to the authorities as suspicious", "means the customer is on a sanctions list"], 0,
     "wolfsberg_pep_guidance_2017", "PEP"),
    ("cdd_rec10", "pep", "FATF Recommendation 10 covers",
     ["customer due diligence", "politically exposed persons", "new technologies", "targeted financial sanctions"],
     0, "fatf_recommendations", "Customer due diligence"),
    ("cdd_threshold", "pep", "Under the FinCEN customer due diligence rule, the ownership prong identifies each "
     "individual who directly or indirectly owns at least",
     ["25 percent of the equity interests of a legal entity customer", "10 percent of the equity interests",
      "50 percent of the equity interests", "5 percent of the equity interests"], 0,
     "fincen_cdd_final_rule_2016", "25 percent"),
    ("cdd_control", "pep", "Under the FinCEN customer due diligence rule, the control prong requires identifying",
     ["a single individual with significant responsibility to control, manage, or direct the legal entity",
      "every director on the board", "the entity's external auditor", "all employees with signing authority"], 0,
     "fincen_cdd_final_rule_2016", "significant responsibility to control"),
    ("cdd_nature", "pep", "One element of customer due diligence made explicit by the FinCEN rule is",
     ["understanding the nature and purpose of customer relationships to develop a customer risk profile",
      "obtaining a credit score for every customer", "requiring two years of tax returns",
      "verifying the customer's social media accounts"], 0, "fincen_cdd_final_rule_2016",
     "nature and purpose of customer relationships"),
    ("cdd_monitoring", "pep", "The FinCEN customer due diligence rule also requires covered institutions to",
     ["conduct ongoing monitoring to identify and report suspicious transactions",
      "close all accounts of foreign nationals", "screen customers only once, at account opening",
      "share customer files with other banks"], 0, "fincen_cdd_final_rule_2016", "ongoing monitoring"),
    # ---- lists, aliases, screening -------------------------------------------------
    ("alias_weak", "alias", "In the FollowTheMoney data model used for sanctions data, a low-quality or very broad "
     "alias of a person is stored in the property",
     ["weakAlias", "alias", "previousName", "firstName"], 0, "sanctions_list_structure", "weakAlias"),
    ("alias_previous", "alias", "In the FollowTheMoney data model, a name a person used before (for example a "
     "maiden name) is stored in the property",
     ["previousName", "weakAlias", "alias", "middleName"], 0, "sanctions_list_structure", "previousName"),
    ("alias_lastname", "alias", "In the FollowTheMoney Person schema, a person's family name is stored in the property",
     ["lastName", "weakAlias", "nameSuffix", "previousName"], 0, "sanctions_list_structure", "lastName"),
    ("alias_sanction_schema", "alias", "In the FollowTheMoney data model, the designation of a person under a sanctions "
     "programme is represented by the schema",
     ["Sanction", "Passport", "Address", "Identification"], 0, "sanctions_list_structure",
     "FollowTheMoney schema: Sanction"),
    ("screen_fuzzy", "alias", "Sanctions screening systems commonly use fuzzy matching in order to",
     ["detect names that differ through spelling variations, transliteration or typing errors",
      "speed up exact matching only", "avoid screening aliases", "automatically clear every alert"], 0,
     "wolfsberg_sanctions_screening_2019", "fuzzy"),
    ("screen_translit", "alias", "A single Arabic or Cyrillic name can appear in Latin script in several spellings "
     "because",
     ["different transliteration systems romanise the same characters differently",
      "the person has changed their name each time", "screening vendors invent spellings",
      "Latin script cannot represent vowels"], 0, "wolfsberg_sanctions_screening_2019", "transliteration"),
    ("addr_de", "alias", "In a German postal address, the house number is written",
     ["after the street name", "before the street name", "on a separate line above the street",
      "after the city name"], 0, "address_formats", "{{{hamlet}}} {{/first}} {{{house_number}}}"),
    ("addr_us", "alias", "In a United States postal address, the house number is written",
     ["before the street name", "after the street name", "after the ZIP code", "on the last line"], 0,
     "address_formats", "{{{house_number}}} {{{road}}}"),
    ("addr_cn", "alias", "When a Chinese address is written in Chinese characters, the components run",
     ["from the largest unit (province, city) down to the street and number", "from the house number up to the country",
      "in alphabetical order", "with the postcode last"], 0, "address_formats", "CN: address_template: | {{{postcode}}} {{{country}}}"),
    ("addr_postcode_varies", "alias", "Postcode formats",
     ["differ from country to country, so validation rules are country-specific",
      "are five digits in every country", "are always letters only", "are never used outside Europe"], 0,
     "address_formats", "postcode format validation"),
]


def items() -> list[dict]:
    out = _cd_items()
    for i, topic, q, opts, ans, src, ev in _ITEMS:
        out.append({"id": i, "topic": topic, "question": q, "options": list(opts), "answer": ans, "source": src,
                    "evidence": ev})
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).casefold()


def answerability(corpus_dir: str | Path) -> dict[str, bool]:
    """item id -> True if its source file is present and contains its evidence phrase."""
    d = Path(corpus_dir)
    cache: dict[str, str | None] = {}
    out = {}
    for it in items():
        if it["source"] not in cache:
            p = d / f"{it['source']}.txt"
            cache[it["source"]] = _norm(p.read_text(encoding="utf-8", errors="replace")) if p.exists() else None
        txt = cache[it["source"]]
        out[it["id"]] = bool(txt) and _norm(it["evidence"]) in txt
    return out


# --------------------------------------------------------------------------
# scoring (torch only inside)
# --------------------------------------------------------------------------
def option_logprobs(model, tok, prompt: str, options: list[str]) -> list[float]:
    """Mean per-token log-prob of each ' <option>' continuation after the prompt."""
    import torch

    dev = next(model.parameters()).device
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    out = []
    for o in options:
        o_ids = tok(" " + o, add_special_tokens=False)["input_ids"]
        ids = torch.tensor([p_ids + o_ids], device=dev)
        with torch.no_grad():
            logits = model(input_ids=ids).logits.float()
        lp = torch.log_softmax(logits[0, len(p_ids) - 1:-1], dim=-1)
        tgt = torch.tensor(o_ids, device=dev)
        out.append(lp.gather(1, tgt[:, None]).mean().item())
    return out


def scores(model, tok, its: list[dict] | None = None, answerable: dict[str, bool] | None = None) -> dict:
    its = its if its is not None else items()
    per = []
    for it in its:
        lps = option_logprobs(model, tok, PROMPT.format(q=it["question"]), it["options"])
        best_wrong = max(lp for j, lp in enumerate(lps) if j != it["answer"])
        pred = max(range(len(lps)), key=lps.__getitem__)
        per.append({"id": it["id"], "topic": it["topic"], "correct": pred == it["answer"],
                    "margin": lps[it["answer"]] - best_wrong,
                    "answerable": None if answerable is None else answerable.get(it["id"])})

    def agg(rows):
        return {"n": len(rows), "accuracy": sum(r["correct"] for r in rows) / len(rows) if rows else None,
                "mean_margin": sum(r["margin"] for r in rows) / len(rows) if rows else None}

    res = {"all": agg(per), "by_topic": {t: agg([r for r in per if r["topic"] == t])
                                         for t in sorted({r["topic"] for r in per})}, "items": per}
    if answerable is not None:
        res["answerable"] = agg([r for r in per if r["answerable"]])
    return res
