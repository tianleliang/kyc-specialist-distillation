"""Latent truth: the hidden facts behind one KYC case.

PROVISIONAL (overnight draft). The fields here are *facts about the world*
(who the applicant really is, what was printed on the document and why,
which screening hits are really the same person), not answers. Nothing in
this module knows about any output schema or decision policy:
``step1_data_generation/project.py`` maps truth -> expected output, and ``step1_data_generation/render.py`` maps
truth -> packet text.

Everything serializes to plain JSON via ``to_dict``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date
from typing import Any

from step1_data_generation.lib.address import Address
from step1_data_generation.lib.names import PersonName

GENERATOR_VERSION = "v1.0-wave2"


@dataclass
class Context:
    onboarding_country: str          # ISO2 where the account is opened
    product: str                     # current_account | savings | business_account | crypto_wallet | remittance | premium_card | brokerage
    channel: str                     # online | mobile_app | branch | introducer
    application_date: date           # when the applicant submitted
    case_ref: str
    as_of_date: date | None = None   # review "as of" date, printed in CTX; expiry and PoA recency are judged against it

    def __post_init__(self):
        if self.as_of_date is None:
            self.as_of_date = self.application_date


@dataclass
class Person:
    """Who the applicant really is."""
    name: PersonName
    sex: str
    dob: date
    nationality: str                 # ISO3
    address: Address                 # where they really live


@dataclass
class Application:
    """What the applicant typed into the onboarding form."""
    full_name: str
    name_system: str | None          # romanization / spelling system used
    name_order: str                  # given_first | surname_first | surname_comma
    name_relation: str               # identical | transliteration | reordered | different_name
    dob: date
    dob_relation: str                # same | typo_digit | day_month_swapped | different
    nationality: str
    address: Address
    address_relation: str            # same (declared = true address)
    occupation: str
    employer: str
    source_of_funds: str
    expected_monthly_volume: int     # in onboarding-country currency units
    expected_activity: str
    currency: str
    address_abbreviated: bool = False   # declared address typed with street-type abbreviations (St, str., Av.)


@dataclass
class DocDefect:
    kind: str        # ocr_glyph | ocr_digit_lookalike | ocr_unreadable | tamper | expired
    field: str       # surname | given_names | doc_number | birth_date | expiry_date | mrz | address | name | issue_date
    zone: str        # viz | mrz | both | doc
    detail: str = ""


@dataclass
class IdDocument:
    kind: str                         # passport | national_id | driving_licence
    mrz_format: str | None            # TD3 | TD1 | None (no MRZ)
    issuing_state: str                # ISO3
    genuine: dict                     # the values as originally issued (before any tampering)
    viz: dict                         # visual-zone values as printed/OCR'd (strings; '' = illegible)
    mrz_lines: list[str] | None       # MRZ as printed/OCR'd
    name_system: str | None
    issue_date: date
    ocr_level: float                  # background OCR noise rate applied at render time
    defects: list[DocDefect] = field(default_factory=list)
    tamper: dict | None = None        # step1_data_generation.lib.ocr.TamperRecord as dict
    mrz_check: str = "none"           # valid | ocr_repairable | invalid | unreadable | none (from step1_data_generation.lib.ocr.explain_mrz)


@dataclass
class ProofOfAddress:
    present: bool
    kind: str = ""                    # utility_bill | bank_statement | council_tax | tenancy_agreement | telecom_bill | government_letter
    issuer: str = ""
    issue_date: date | None = None
    name_on_doc: str = ""
    name_relation: str = "same"       # same | variant | different
    address: Address | None = None
    address_relation: str = "same"    # same | benign_variant | contradicts
    contradiction: str = ""           # street | number | city | postcode | whole
    render_style: str = "postal"      # how the address is laid out on the PoA
    legible: bool = True
    ocr_level: float = 0.0
    abbreviated: bool = False         # PoA prints street-type abbreviations; only True when that changes the text


@dataclass
class HitTruth:
    hit_id: str
    list_type: str                    # sanctions | pep | adverse_media
    entry: dict                       # step1_data_generation.lib.watchlist.Entry.to_dict() (listed data as the vendor shows it)
    score: int                        # vendor similarity 0-100
    matched_on: str
    same_person: bool | None          # latent: is the listed person the applicant? None = unknowable by construction
    pep_relation: str | None = None   # self | family | close_associate (PEP / RCA hits)
    dob_comparison: str = "unknown"   # step1_data_generation.lib.matching.compare_dob result vs the applicant's true DOB
    nationality_match: bool | None = None
    discriminators: list[str] = field(default_factory=list)   # extra listed facts that confirm/refute (e.g. 'occupation_matches', 'age_conflicts')
    media_category: str | None = None


@dataclass
class Injection:
    present: bool
    location: str = ""                # occupation | employer | poa_notes | id_ocr | hit_remarks | expected_activity | applicant_note
    technique: str = ""               # direct_instruction | fake_system_message | fake_analyst_override | json_payload | polite_request
    text: str = ""
    target: str = ""                  # what it tries to get: approve | clear_hits | low_risk | skip_checks


@dataclass
class RiskFacts:
    occupation_risk: str              # low | medium | high (cash-intensive, high-value dealers...)
    sof_consistent: bool              # declared source of funds plausible for the occupation
    activity_consistent: bool         # expected volume plausible for the occupation / income
    cross_border: bool                # nationality and residence differ from onboarding country
    product_risk: str                 # low | medium | high
    non_face_to_face: bool


@dataclass
class CaseTruth:
    case_id: str
    seed: int
    generator_version: str
    scenarios: list[str]              # difficulty items this case exercises
    context: Context
    person: Person
    application: Application
    id_doc: IdDocument
    poa: ProofOfAddress
    hits: list[HitTruth]
    injection: Injection
    risk: RiskFacts
    ambiguity: list[str] = field(default_factory=list)   # deliberate gaps where evidence can't settle the question
    notes: list[str] = field(default_factory=list)
    split: str = "draft"              # train | dev | eval_id | eval_ood_template | pilot | draft
    config_id: str = ""
    # Knob vector: every sampling choice that shapes difficulty or surface
    # (scenarios, document kind, noise levels, layout style, switches, origin
    # of twins/knockouts). Used to slice results and to resample failures.
    knobs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _jsonable(self)


def _jsonable(o: Any) -> Any:
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, PersonName):
        return {"origin": o.origin, "sex": o.sex, "given": o.given, "surname": o.surname,
                "patronymic": o.patronymic, "ar_article": o.ar_article, "canonical": o.canonical}
    if isinstance(o, Address):
        d = {k: _jsonable(v) for k, v in asdict(o).items()}
        d["one_line"] = o.one_line()
        return d
    if is_dataclass(o):
        return {k: _jsonable(getattr(o, k)) for k in o.__dataclass_fields__}
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    return o
