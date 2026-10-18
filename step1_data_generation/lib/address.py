"""Address sampling and rendering for 10 countries, following national /
UPU postal conventions: US, GB, DE, FR, AE, RU, CN, IN, NG, BR.

Streets are fictional (compound names built from word pools). Cities and
regions are real places, paired with a plausible postcode prefix, since a
city is not personal data and a made-up city would itself be a red flag.

Also provides the two kinds of change a proof-of-address check must tell
apart:
* ``benign_variant``: the same address written differently (abbreviations,
  missing flat number, different line breaks, transliteration);
* ``contradicting_variant``: a genuinely different address (other street,
  house number, city or postcode).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, replace

COUNTRIES = ("US", "GB", "DE", "FR", "AE", "RU", "CN", "IN", "NG", "BR")
COUNTRY_NAMES = {"US": "United States", "GB": "United Kingdom", "DE": "Germany",
                 "FR": "France", "AE": "United Arab Emirates", "RU": "Russian Federation",
                 "CN": "China", "IN": "India", "NG": "Nigeria", "BR": "Brazil"}
ISO3 = {"US": "USA", "GB": "GBR", "DE": "DEU", "FR": "FRA", "AE": "ARE", "RU": "RUS",
        "CN": "CHN", "IN": "IND", "NG": "NGA", "BR": "BRA"}


# --------------------------------------------------------------------------
# per-country pools: (city, region, postcode prefix)
# --------------------------------------------------------------------------
CITIES = {
    "US": [("Columbus", "OH", "432"), ("Denver", "CO", "802"), ("Austin", "TX", "787"),
           ("Raleigh", "NC", "276"), ("Tucson", "AZ", "857"), ("Madison", "WI", "537"),
           ("Spokane", "WA", "992"), ("Omaha", "NE", "681")],
    "GB": [("Leeds", "", "LS"), ("Bristol", "", "BS"), ("Norwich", "", "NR"),
           ("Leicester", "", "LE"), ("Exeter", "", "EX"), ("York", "", "YO"),
           ("Cardiff", "", "CF"), ("Sheffield", "", "S")],
    "DE": [("Leipzig", "Sachsen", "04"), ("Bremen", "Bremen", "28"), ("Kassel", "Hessen", "34"),
           ("Freiburg im Breisgau", "Baden-Württemberg", "79"), ("Münster", "Nordrhein-Westfalen", "48"),
           ("Rostock", "Mecklenburg-Vorpommern", "18"), ("Augsburg", "Bayern", "86")],
    "FR": [("Lyon", "", "690"), ("Nantes", "", "440"), ("Toulouse", "", "310"),
           ("Lille", "", "590"), ("Rennes", "", "350"), ("Dijon", "", "210"),
           ("Grenoble", "", "380"), ("Montpellier", "", "340")],
    "AE": [("Dubai", "Dubai", ""), ("Abu Dhabi", "Abu Dhabi", ""), ("Sharjah", "Sharjah", ""),
           ("Ajman", "Ajman", ""), ("Ras Al Khaimah", "Ras Al Khaimah", "")],
    "RU": [("Kazan", "Respublika Tatarstan", "420"), ("Tver", "Tverskaya oblast", "170"),
           ("Samara", "Samarskaya oblast", "443"), ("Omsk", "Omskaya oblast", "644"),
           ("Yaroslavl", "Yaroslavskaya oblast", "150"), ("Perm", "Permskiy kray", "614")],
    "CN": [("Shenzhen", "Guangdong", "518"), ("Hangzhou", "Zhejiang", "310"),
           ("Chengdu", "Sichuan", "610"), ("Wuhan", "Hubei", "430"),
           ("Nanjing", "Jiangsu", "210"), ("Xi'an", "Shaanxi", "710")],
    "IN": [("Bengaluru", "Karnataka", "560"), ("Pune", "Maharashtra", "411"),
           ("Chennai", "Tamil Nadu", "600"), ("Hyderabad", "Telangana", "500"),
           ("Jaipur", "Rajasthan", "302"), ("Kochi", "Kerala", "682")],
    "NG": [("Ikeja", "Lagos State", "100"), ("Lekki", "Lagos State", "105"),
           ("Garki", "FCT Abuja", "900"), ("Ibadan", "Oyo State", "200"),
           ("Enugu", "Enugu State", "400"), ("Port Harcourt", "Rivers State", "500")],
    "BR": [("Campinas", "SP", "130"), ("Curitiba", "PR", "800"), ("Recife", "PE", "500"),
           ("Belo Horizonte", "MG", "301"), ("Porto Alegre", "RS", "900"),
           ("Fortaleza", "CE", "600")],
}
CN_NATIVE = {"Shenzhen": ("广东省", "深圳市"), "Hangzhou": ("浙江省", "杭州市"),
             "Chengdu": ("四川省", "成都市"), "Wuhan": ("湖北省", "武汉市"),
             "Nanjing": ("江苏省", "南京市"), "Xi'an": ("陕西省", "西安市")}
RU_NATIVE = {"Kazan": ("Республика Татарстан", "Казань"), "Tver": ("Тверская обл.", "Тверь"),
             "Samara": ("Самарская обл.", "Самара"), "Omsk": ("Омская обл.", "Омск"),
             "Yaroslavl": ("Ярославская обл.", "Ярославль"), "Perm": ("Пермский край", "Пермь")}

# fictional street morphemes
_EN_A = ["Copper", "Brindle", "Larks", "Heron", "Thistle", "Amber", "Willow", "Marl",
         "Fern", "Quill", "Hazel", "Juniper", "Wren", "Bramble", "Kestrel", "Sorrel"]
_EN_B = ["leaf", "wood", "spur", "brook", "gate", "field", "mere", "croft", "dale",
         "haven", "stone", "hollow", "ridge", "wick"]
US_TYPES = [("Street", "St"), ("Avenue", "Ave"), ("Road", "Rd"), ("Drive", "Dr"),
            ("Lane", "Ln"), ("Court", "Ct"), ("Boulevard", "Blvd"), ("Place", "Pl")]
GB_TYPES = [("Road", "Rd"), ("Lane", "Ln"), ("Close", "Cl"), ("Street", "St"),
            ("Gardens", "Gdns"), ("Crescent", "Cres"), ("Terrace", "Terr"), ("Way", "Way")]
_DE_A = ["Birken", "Eschen", "Holunder", "Lerchen", "Mohn", "Quitten", "Wachtel", "Distel",
         "Heide", "Kranich", "Mispel", "Schlehen", "Wiesel", "Ginster"]
DE_TYPES = [("straße", "str."), ("weg", "weg"), ("gasse", "g."), ("allee", "allee"), ("ring", "ring")]
_FR_B = ["des Glycines", "des Alouettes", "du Chardon", "des Mésanges", "de la Fougère",
         "des Peupliers Blancs", "du Moulin Vert", "des Coquelicots", "de l'Aubépine",
         "des Hérons", "du Pré Fleuri", "des Saules"]
FR_TYPES = [("rue", "r."), ("avenue", "av."), ("allée", "all."), ("impasse", "imp."),
            ("boulevard", "bd"), ("chemin", "ch.")]
_AE_AREA = ["Al Nahda", "Al Warqa", "Al Mizhar", "Al Rashidiya", "Al Barsha South",
            "Al Qusais", "Al Khawaneej", "Mirdif", "Al Jaddaf", "Al Reem"]
_RU_ST = [("Sirenevaya", "Сиреневая"), ("Lugovaya", "Луговая"), ("Ryabinovaya", "Рябиновая"),
          ("Zarechnaya", "Заречная"), ("Kedrovaya", "Кедровая"), ("Vishnevaya", "Вишнёвая"),
          ("Lesnaya Polyana", "Лесная Поляна"), ("Solnechnaya", "Солнечная")]
_CN_RD = [("Kejiyuan", "科技园"), ("Xinghe", "星河"), ("Qingshi", "青石"), ("Huayuan", "花园"),
          ("Jinxiu", "锦绣"), ("Baiyun", "白云"), ("Lanting", "兰亭"), ("Songbai", "松柏")]
_CN_DIST = {"Shenzhen": ("Nanshan", "南山区"), "Hangzhou": ("Xihu", "西湖区"),
            "Chengdu": ("Wuhou", "武侯区"), "Wuhan": ("Hongshan", "洪山区"),
            "Nanjing": ("Gulou", "鼓楼区"), "Xi'an": ("Yanta", "雁塔区")}
_IN_SOC = ["Sai Krupa", "Shanti Niketan", "Green Meadows", "Lakshmi Nivas", "Sunrise Enclave",
           "Ganga Vihar", "Silver Oak", "Tulsi Kunj"]
_IN_AREA = ["Indiranagar", "Kothrud", "Adyar", "Madhapur", "Malviya Nagar", "Kakkanad",
            "Jayanagar", "Banjara Hills"]
_NG_ST = ["Adeyemi Close", "Okonjo Crescent", "Bamgbose Street", "Ilori Avenue",
          "Nnadi Close", "Ajanaku Street", "Oyelaran Way", "Eze Udo Crescent"]
_NG_OFF = ["Allen Avenue", "Admiralty Way", "Aminu Kano Crescent", "Ring Road", "Ogui Road"]
_BR_ST = ["das Palmeiras Altas", "dos Ipês Roxos", "Sabiá-Laranjeira", "dos Jacarandás",
          "das Bromélias", "do Bem-te-vi", "das Orquídeas Brancas", "dos Cajueiros"]
_BR_BAIRRO = ["Jardim Esperança", "Vila Nova Aurora", "Parque das Flores", "Boa Vista",
              "Jardim Primavera", "Vila Serena"]
BR_TYPES = [("Rua", "R."), ("Avenida", "Av."), ("Travessa", "Tv."), ("Alameda", "Al.")]


@dataclass
class Address:
    country: str
    street: str                  # street name incl. type, full form
    number: str
    unit: str = ""               # flat / apt / room
    locality: str = ""           # district, neighbourhood, bairro, area
    city: str = ""
    region: str = ""
    postcode: str = ""
    extra: dict = field(default_factory=dict)  # abbreviations, native-script parts, PO box, landmark

    # identity for comparison: two renderings of the same Address are "consistent"
    def key(self) -> tuple:
        return (self.country, self.street.lower(), self.number, self.city.lower(),
                self.postcode.replace(" ", "").replace("-", "")[:5 if self.country == "US" else None],
                self.locality.lower() if self.country == "AE" else "")

    def render(self, style: str = "postal", abbreviate: bool = False) -> str:
        return _RENDER[self.country](self, style, abbreviate)

    def one_line(self, abbreviate: bool = False) -> str:
        return ", ".join(l.strip() for l in self.render("postal", abbreviate).splitlines() if l.strip())


# --------------------------------------------------------------------------
# sampling
# --------------------------------------------------------------------------
def _digits(rng, n):
    return "".join(rng.choice("0123456789") for _ in range(n))


def _gb_postcode(rng, area):
    letters = "ABDEFGHJLNPQRSTUWXYZ"
    return f"{area}{rng.randint(1, 19)} {rng.randint(0, 9)}{rng.choice(letters)}{rng.choice(letters)}"


def sample_address(rng: random.Random, country: str) -> Address:
    city, region, pc = rng.choice(CITIES[country])
    c = country
    if c in ("US", "GB"):
        types = US_TYPES if c == "US" else GB_TYPES
        t, ab = rng.choice(types)
        street = f"{rng.choice(_EN_A)}{rng.choice(_EN_B)} {t}"
        unit = rng.choice(["", "", f"Apt {rng.randint(1, 20)}{rng.choice('ABCD')}" if c == "US" else f"Flat {rng.randint(1, 12)}"])
        postcode = (pc + _digits(rng, 2)) if c == "US" else _gb_postcode(rng, pc)
        if c == "US" and rng.random() < 0.3:
            postcode += "-" + _digits(rng, 4)
        return Address(c, street, str(rng.randint(2, 9800) if c == "US" else rng.randint(1, 220)),
                       unit, "", city, region, postcode, {"abbr": (t, ab)})
    if c == "DE":
        t, ab = rng.choice(DE_TYPES)
        a = rng.choice(_DE_A)
        street = f"{a}{t}"
        return Address(c, street, f"{rng.randint(1, 140)}{rng.choice(['', '', 'a', 'b'])}",
                       rng.choice(["", "", f"{rng.randint(1, 5)}. OG"]), "", city, region,
                       pc + _digits(rng, 3), {"abbr": (street, f"{a}{ab}")})
    if c == "FR":
        t, ab = rng.choice(FR_TYPES)
        street = f"{t} {rng.choice(_FR_B)}"
        return Address(c, street, str(rng.randint(1, 160)) + rng.choice(["", "", " bis"]),
                       rng.choice(["", "", f"Bât. {rng.choice('ABC')}, Apt {rng.randint(1, 40)}"]),
                       "", city, region, pc + _digits(rng, 2), {"abbr": (t, ab)})
    if c == "AE":
        area = rng.choice(_AE_AREA)
        street = f"Street {rng.randint(1, 45)}"
        unit = rng.choice([f"Villa {rng.randint(1, 90)}", f"Flat {rng.randint(101, 2405)}"])
        bldg = rng.choice(["", f"{rng.choice(['Al Saqr', 'Palm View', 'Marina Crest', 'Al Noor', 'Sand Dune'])} Building"])
        return Address(c, street, "", unit, area, city, region, "",
                       {"po_box": f"P.O. Box {rng.randint(1000, 99999)}", "building": bldg,
                        "makani": _digits(rng, 10) if rng.random() < 0.3 else ""})
    if c == "RU":
        lat, cyr = rng.choice(_RU_ST)
        reg_cyr, city_cyr = RU_NATIVE[city]
        return Address(c, f"ul. {lat}", str(rng.randint(1, 120)),
                       f"kv. {rng.randint(1, 300)}" if rng.random() < 0.8 else "", "",
                       city, region, pc + _digits(rng, 3),
                       {"street_cyr": f"ул. {cyr}", "city_cyr": city_cyr, "region_cyr": reg_cyr,
                        "korpus": str(rng.randint(1, 4)) if rng.random() < 0.25 else ""})
    if c == "CN":
        rd_lat, rd_zh = rng.choice(_CN_RD)
        d_lat, d_zh = _CN_DIST[city]
        prov_zh, city_zh = CN_NATIVE[city]
        room = rng.randint(101, 2808)
        bldg = rng.randint(1, 12)
        return Address(c, f"{rd_lat} Road", str(rng.randint(1, 999)), f"Room {room}, Building {bldg}",
                       f"{d_lat} District", city, region, pc + _digits(rng, 3),
                       {"zh_prov": prov_zh, "zh_city": city_zh, "zh_dist": d_zh, "zh_rd": rd_zh,
                        "room": room, "bldg": bldg})
    if c == "IN":
        soc = rng.choice(_IN_SOC)
        area = rng.choice(_IN_AREA)
        cross = f"{rng.randint(1, 18)}th Cross" if rng.random() < 0.5 else f"{rng.randint(1, 9)}th Main Road"
        return Address(c, cross, str(rng.randint(1, 900)), f"Flat {rng.randint(101, 1204)}, {soc} Apartments",
                       area, city, region, pc + _digits(rng, 3),
                       {"landmark": rng.choice(["", "", f"Near {rng.choice(['Shiva Temple', 'Metro Station', 'Government School', 'Water Tank'])}"])})
    if c == "NG":
        st = rng.choice(_NG_ST)
        return Address(c, st, str(rng.randint(1, 60)), rng.choice(["", f"Flat {rng.randint(1, 8)}"]),
                       "", city, region, pc + _digits(rng, 3),
                       {"off": rng.choice(["", f"off {rng.choice(_NG_OFF)}"]),
                        "plot": rng.random() < 0.4})
    if c == "BR":
        t, ab = rng.choice(BR_TYPES)
        street = f"{t} {rng.choice(_BR_ST)}"
        return Address(c, street, str(rng.randint(10, 4800)),
                       rng.choice(["", f"Apto {rng.randint(11, 1504)}", f"Casa {rng.randint(1, 4)}"]),
                       rng.choice(_BR_BAIRRO), city, region, f"{pc}{_digits(rng, 2)}-{_digits(rng, 3)}",
                       {"abbr": (t, ab)})
    raise ValueError(country)


# --------------------------------------------------------------------------
# renderers: each returns multi-line text; style in {postal, single_line, native}
# --------------------------------------------------------------------------
def _abbr(a: Address, abbreviate: bool) -> str:
    if abbreviate and "abbr" in a.extra:
        full, short = a.extra["abbr"]
        return a.street.replace(full, short)
    return a.street


def _join(lines: list[str], style: str) -> str:
    lines = [l for l in lines if l and l.strip()]
    return ", ".join(lines) if style == "single_line" else "\n".join(lines)


def _us(a, style, ab):
    l1 = f"{a.number} {_abbr(a, ab)}" + (f" {a.unit}" if a.unit and ab else "")
    l2 = a.unit if a.unit and not ab else ""
    last = f"{a.city.upper()} {a.region} {a.postcode}" if ab else f"{a.city}, {a.region} {a.postcode}"
    return _join([l1, l2, last], style)


def _gb(a, style, ab):
    l1 = f"{a.unit}, {a.number} {_abbr(a, ab)}" if a.unit else f"{a.number} {_abbr(a, ab)}"
    return _join([l1, a.city.upper(), a.postcode], style)


def _de(a, style, ab):
    l1 = f"{_abbr(a, ab)} {a.number}"
    return _join([l1, a.unit, f"{a.postcode} {a.city}"], style)


def _fr(a, style, ab):
    st = _abbr(a, ab)
    l1 = f"{a.number}, {st}" if ab else f"{a.number} {st}"
    return _join([a.unit, l1, f"{a.postcode} {a.city.upper()}"], style)


def _ae(a, style, ab):
    b = a.extra.get("building", "")
    l1 = ", ".join(x for x in [a.unit, b] if x)
    lines = [l1, f"{a.street}, {a.locality}", a.extra.get("po_box", ""), a.city.upper() if ab else a.city]
    if a.extra.get("makani"):
        lines.insert(2, f"Makani {a.extra['makani']}")
    return _join(lines, style)


def _ru(a, style, ab):
    x = a.extra
    if style == "native":
        house = f"д. {a.number}" + (f", корп. {x['korpus']}" if x.get("korpus") else "")
        flat = a.unit.replace("kv.", "кв.") if a.unit else ""
        return "\n".join(l for l in [", ".join(p for p in [x["street_cyr"], house, flat] if p),
                                      f"г. {x['city_cyr']}", x["region_cyr"], a.postcode] if l)
    house = f"d. {a.number}" + (f", korp. {x['korpus']}" if x.get("korpus") else "")
    l1 = ", ".join(p for p in [a.street, house, a.unit] if p)
    return _join([l1, f"g. {a.city}", a.region, a.postcode], style)


def _cn(a, style, ab):
    if style == "native":
        x = a.extra
        return (f"{x['zh_prov']}{x['zh_city']}{x['zh_dist']}{x['zh_rd']}路{a.number}号"
                f"{x['bldg']}栋{x['room']}室\n{a.postcode}")
    l1 = f"{a.unit}, No. {a.number} {a.street}" if a.unit else f"No. {a.number} {a.street}"
    return _join([l1, a.locality, f"{a.city}, {a.region} {a.postcode}"], style)


def _in(a, style, ab):
    lm = a.extra.get("landmark", "")
    return _join([a.unit, f"{a.number}, {a.street}", a.locality, lm,
                  f"{a.city} - {a.postcode}, {a.region}" if ab else f"{a.city}, {a.region} {a.postcode}"], style)


def _ng(a, style, ab):
    num = f"Plot {a.number}" if a.extra.get("plot") else f"No. {a.number}"
    l1 = ", ".join(p for p in [a.unit, f"{num} {a.street}", a.extra.get("off", "")] if p)
    return _join([l1, f"{a.city}, {a.region}", a.postcode], style)


def _br(a, style, ab):
    l1 = ", ".join(p for p in [_abbr(a, ab), a.number, a.unit] if p)
    return _join([l1, a.locality, f"{a.city} - {a.region}", a.postcode], style)


_RENDER = {"US": _us, "GB": _gb, "DE": _de, "FR": _fr, "AE": _ae, "RU": _ru,
           "CN": _cn, "IN": _in, "NG": _ng, "BR": _br}


# --------------------------------------------------------------------------
# variants for proof-of-address checks
# --------------------------------------------------------------------------
def render_variant(a: Address, rng: random.Random) -> str:
    """Same address, written differently (benign)."""
    styles = ["postal", "single_line"]
    if a.country in ("RU", "CN"):
        styles.append("native")
    style = rng.choice(styles)
    text = a.render(style, abbreviate=rng.random() < 0.5)
    if a.unit and rng.random() < 0.2 and style != "native":
        text = text.replace(a.unit + ", ", "").replace(a.unit + "\n", "").replace(" " + a.unit, "")
    return text


def benign_variant(a: Address, rng: random.Random) -> Address:
    """A copy with only cosmetic differences (dropped unit, extra fields)."""
    b = replace(a, extra=dict(a.extra))
    if b.unit and rng.random() < 0.3:
        b.unit = ""
    if b.country == "US" and "-" not in b.postcode and rng.random() < 0.3:
        b.postcode += "-" + _digits(rng, 4)
    return b


CONTRADICTIONS = ("street", "number", "city", "postcode", "whole")
_STREET_KEYS = ("abbr", "street_cyr", "zh_rd")
_CITY_KEYS = ("city_cyr", "region_cyr", "zh_prov", "zh_city", "zh_dist")


def contradicting_variant(a: Address, rng: random.Random, kind: str | None = None) -> tuple[Address, str]:
    """A materially different address. Returns (address, what_changed).

    For AE, which has no postcodes, 'postcode' changes the area instead.
    """
    kind = kind or rng.choice(CONTRADICTIONS)
    for _ in range(50):
        other = sample_address(rng, a.country)
        b = replace(a, extra=dict(a.extra))
        if kind == "street":
            b.street = other.street
            b.extra.update({k: other.extra[k] for k in _STREET_KEYS if k in other.extra})
        elif kind == "number":
            digits = "".join(ch for ch in a.number if ch.isdigit())
            b.number = str(int(digits or "1") + rng.randint(1, 40)) if a.number else str(rng.randint(1, 90))
        elif kind == "city":
            if other.city == a.city:
                continue
            b.city, b.region, b.postcode, b.locality = other.city, other.region, other.postcode, other.locality
            b.extra.update({k: other.extra[k] for k in _CITY_KEYS if k in other.extra})
        elif kind == "postcode":
            if a.country == "AE":
                b.locality = other.locality
                b.extra["po_box"] = other.extra["po_box"]
            else:
                b.postcode = other.postcode
        else:
            b = other
        if b.key() != a.key():
            return b, kind
    raise RuntimeError("could not build a contradicting address")
