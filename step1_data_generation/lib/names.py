"""Synthetic name engine.

Fictional names across origins, with the spelling variation a screening
analyst actually sees:

* Arabic:   one name, many Latin spellings (Muhammad / Mohammed / Mukhammad),
            article variants (al- / el- / Al / none), q/k, ou/u, ee/i, dh/z.
* Cyrillic: names held in Cyrillic and romanized by several systems
            (ICAO 9303 2013, BGN/PCGN, GOST 7.79-B, German, French), with
            patronymics.
* Chinese:  names held as characters, rendered in Hanyu Pinyin, Wade-Giles
            (with and without diacritics) and Cantonese (Hong Kong) style,
            with surname-first / given-first ordering and hyphenation.
* Latin:    English, Spanish (two surnames), Portuguese, German, French, with
            diacritic stripping, dropped maternal surnames, middle initials and
            nicknames.
* Other:    Yoruba, Igbo, Indian (Hindi / South Indian initial style).

Surnames are mostly built from syllables, given names come from common
given-name pools, and every full name is checked against a blocklist of
public figures, so no generated identity is a real person. The pools are
small on purpose: we copy naming *conventions*, not people.

Every function takes an explicit ``random.Random`` so the generator stays
reproducible.
"""
from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass, field

ORIGINS = ("arabic", "cyrillic", "chinese", "latin_en", "latin_es", "latin_pt",
           "latin_de", "latin_fr", "yoruba", "igbo", "indian")

# Origin -> typical nationality codes used by the sampler (ISO alpha-3).
ORIGIN_NATIONALITIES = {
    "arabic": ["ARE", "SAU", "EGY", "JOR", "QAT"],
    "cyrillic": ["RUS", "UKR", "KAZ", "UZB", "BLR"],
    "chinese": ["CHN", "TWN", "HKG", "SGP"],
    "latin_en": ["GBR", "USA", "IRL", "CAN", "AUS"],
    "latin_es": ["ESP", "MEX", "COL", "ARG"],
    "latin_pt": ["BRA", "PRT"],
    "latin_de": ["DEU", "AUT", "CHE"],
    "latin_fr": ["FRA", "BEL", "CHE"],
    "yoruba": ["NGA"],
    "igbo": ["NGA"],
    "indian": ["IND"],
}


# ==========================================================================
# public-figure blocklist (full names and distinctive surnames, casefolded,
# diacritics stripped). Anything matching is resampled.
# ==========================================================================
_BLOCK_FULL = {
    "vladimir putin", "xi jinping", "joe biden", "donald trump", "barack obama",
    "emmanuel macron", "olaf scholz", "angela merkel", "narendra modi",
    "rishi sunak", "keir starmer", "boris johnson", "mohammed bin salman",
    "muhammad bin salman", "mohammed bin zayed", "bola tinubu",
    "muhammadu buhari", "luiz inacio lula da silva", "jair bolsonaro",
    "sergey lavrov", "dmitry medvedev", "volodymyr zelensky", "alexei navalny",
    "li qiang", "hu jintao", "wen jiabao", "li keqiang", "osama bin laden",
    "kim jong un", "recep tayyip erdogan", "bashar al assad",
    "aliko dangote", "mukesh ambani", "gautam adani", "elon musk",
}
_BLOCK_SURNAMES = {
    "putin", "medvedev", "lavrov", "navalny", "navalnyi", "shoigu", "zelensky",
    "zelenskyi", "lukashenko", "kadyrov", "prigozhin", "deripaska",
    "abramovich", "usmanov", "vekselberg", "rotenberg", "sechin", "timchenko",
    "jinping", "keqiang", "assad", "erdogan", "tinubu", "buhari", "dangote",
    "ambani", "adani", "bolsonaro", "trump", "biden", "obama", "macron",
}


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z ]", " ", s.lower()).split())


def is_blocked(full_name: str) -> bool:
    f = _fold(full_name)
    toks = set(f.split())
    if toks & _BLOCK_SURNAMES:
        return True
    return any(b == f or set(b.split()) <= toks for b in _BLOCK_FULL)


# ==========================================================================
# Arabic
# ==========================================================================
# canonical key -> spellings (first is the most common English-press form)
ARABIC_GIVEN_M = {
    "muhammad": ["Muhammad", "Mohammed", "Mohamed", "Mohammad", "Muhammed", "Mukhammad", "Mohamad", "Mehmet"],
    "ahmad": ["Ahmad", "Ahmed", "Akhmad", "Ahmet"],
    "ali": ["Ali", "Aly", "Alee"],
    "hassan": ["Hassan", "Hasan", "Khasan", "Hassen"],
    "hussein": ["Hussein", "Husayn", "Hussain", "Hosein", "Husein", "Khusein"],
    "omar": ["Omar", "Umar", "Omer"],
    "khalid": ["Khalid", "Khaled", "Halid", "Chaled"],
    "yusuf": ["Yusuf", "Youssef", "Yousef", "Yussuf", "Iosif", "Yousif"],
    "ibrahim": ["Ibrahim", "Ebrahim", "Ibraheem", "Ibragim"],
    "abdullah": ["Abdullah", "Abdallah", "Abd Allah", "Abdulla", "Abdoullah"],
    "abdulrahman": ["Abdulrahman", "Abdul Rahman", "Abd al-Rahman", "Abdelrahman", "Abdurakhman"],
    "mustafa": ["Mustafa", "Moustafa", "Mostafa", "Mustapha"],
    "tariq": ["Tariq", "Tarek", "Tareq", "Tarik"],
    "karim": ["Karim", "Kareem", "Kerim"],
    "faisal": ["Faisal", "Faysal", "Feisal", "Faycal"],
    "nasser": ["Nasser", "Nasir", "Naser", "Nassir"],
    "hamza": ["Hamza", "Hamzah", "Khamza"],
    "walid": ["Walid", "Waleed", "Oualid"],
    "saeed": ["Saeed", "Said", "Saied", "Sayed"],
    "jamal": ["Jamal", "Gamal", "Djamal", "Jamaal"],
}
ARABIC_GIVEN_F = {
    "fatima": ["Fatima", "Fatimah", "Fatma", "Fatemeh"],
    "aisha": ["Aisha", "Aishah", "Ayesha", "Aicha", "Ayşe"],
    "maryam": ["Maryam", "Mariam", "Meryem", "Mariyam"],
    "layla": ["Layla", "Leila", "Laila", "Leyla"],
    "nour": ["Nour", "Noor", "Nur"],
    "huda": ["Huda", "Houda", "Hoda"],
    "salma": ["Salma", "Selma", "Salmah"],
    "zainab": ["Zainab", "Zaynab", "Zeinab", "Zeynep"],
    "amina": ["Amina", "Aminah", "Emine", "Ameena"],
    "khadija": ["Khadija", "Khadijah", "Hatice", "Khadeeja"],
    "rania": ["Rania", "Ranya", "Raniya"],
    "yasmin": ["Yasmin", "Yasmeen", "Jasmin", "Yasmine"],
}
_AR_SUR_ONSET = ["Q", "R", "H", "S", "Z", "B", "T", "N", "J", "F", "M", "D", "K", "Sh", "Kh", "Gh"]
_AR_SUR_V1 = ["a", "u", "i", "aa"]
_AR_SUR_MID = ["s", "sh", "h", "l", "r", "m", "n", "d", "b", "f", "j", "q", "t", "z", "dh", "kh"]
_AR_SUR_END = ["imi", "ani", "ari", "awi", "iri", "uni", "adi", "ami", "uli", "ashi", "abi"]
ARABIC_GIVEN = {**ARABIC_GIVEN_M, **ARABIC_GIVEN_F}

# Rule-based respelling applied to synthetic Arabic surnames.
_AR_RULES = [
    (r"q", "k"), (r"aa", "a"), (r"u", "ou"), (r"i(?=[^aeiou]|$)", "ee"),
    (r"dh", "z"), (r"kh", "h"), (r"sh", "ch"), (r"j", "dj"), (r"ani$", "any"),
    (r"awi$", "aoui"), (r"([bdfhjklmnrstz])\1", r"\1"),
]


def _ar_respell(stem: str, rng: random.Random, p: float = 0.35) -> str:
    s = stem.lower()
    for pat, rep in _AR_RULES:
        if rng.random() < p:
            s = re.sub(pat, rep, s, count=1)
    return s[:1].upper() + s[1:]


def _ar_article(stem: str, style: str) -> str:
    return {"al-": f"al-{stem}", "Al-": f"Al-{stem}", "el-": f"el-{stem}",
            "Al ": f"Al {stem}", "": stem, "Al": f"Al{stem.lower()}"}[style]


# ==========================================================================
# Cyrillic
# ==========================================================================
CYR_GIVEN_M = ["Дмитрий", "Алексей", "Сергей", "Андрей", "Николай", "Юрий",
               "Евгений", "Михаил", "Илья", "Фёдор", "Григорий", "Иван",
               "Мухаммад", "Рустам", "Тимур", "Фарход", "Алишер", "Шамиль",
               "Ахмед", "Олег", "Вадим", "Артём"]
CYR_GIVEN_F = ["Юлия", "Екатерина", "Наталья", "Ольга", "Татьяна", "Ксения",
               "Анастасия", "Елена", "Дарья", "Дилноза", "Гульнара", "Мадина",
               "Яна", "Светлана", "Алёна"]
CYR_FATHERS = ["Дмитрий", "Сергей", "Николай", "Андрей", "Иван", "Борис",
               "Олег", "Виктор", "Рустам", "Тимур", "Алексей", "Геннадий",
               "Василий", "Анатолий", "Юрий", "Аркадий"]
_CYR_SYL_ON = ["Б", "В", "Г", "Д", "Ж", "З", "К", "Л", "М", "Н", "П", "Р", "С", "Т", "Х", "Ц", "Ч", "Ш"]
_CYR_SYL_V = ["а", "о", "е", "и", "у", "я", "ю", "ы"]
_CYR_SYL_C = ["б", "в", "г", "д", "ж", "з", "к", "л", "м", "н", "р", "с", "т", "х", "ч", "ш", "ст", "рт", "лк", "рш"]
_CYR_SUFFIX = [("ов", "ова"), ("ев", "ева"), ("ин", "ина"), ("ский", "ская"),
               ("енко", "енко"), ("ук", "ук"), ("ович", "ович"), ("цев", "цева")]


def patronymic(father: str, sex: str) -> str:
    m = sex != "F"
    if father.endswith("ий"):
        return father[:-2] + ("иевич" if m else "иевна")
    if father.endswith("ей"):
        return father[:-2] + ("еевич" if m else "еевна")
    if father.endswith("ай"):
        return father[:-2] + ("аевич" if m else "аевна")
    if father.endswith(("й", "ь", "а", "я")):
        return father[:-1] + ("евич" if m else "евна")
    return father + ("ович" if m else "овна")


_CYR_VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
_CYR_SIGNS = set("ъьЪЬ")

# lowercase tables; uppercase handled generically
_ROMAN_BASE = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "ie", "ы": "y", "ь": "", "э": "e", "ю": "iu", "я": "ia",
}
ROMANIZATION_SYSTEMS = {
    # ICAO Doc 9303 (7th ed.) table, used in Russian passports since 2013
    "icao": dict(_ROMAN_BASE),
    # BGN/PCGN 1947 (diacritics/apostrophes dropped, as in most databases)
    "bgn_pcgn": {**_ROMAN_BASE, "ё": "yo", "й": "y", "ъ": "", "ю": "yu", "я": "ya",
                 "_e_initial": "ye"},
    # GOST 7.79-2000 system B (apostrophes dropped)
    "gost_b": {**_ROMAN_BASE, "ё": "yo", "й": "j", "х": "x", "ц": "cz", "щ": "shh",
               "ъ": "", "ы": "y", "э": "e", "ю": "yu", "я": "ya"},
    # German (Duden-style)
    "german": {**_ROMAN_BASE, "в": "w", "ж": "sch", "з": "s", "й": "i", "х": "ch",
               "ц": "z", "ч": "tsch", "ш": "sch", "щ": "schtsch", "ъ": "", "ю": "ju",
               "я": "ja", "ё": "jo", "с": "s", "_e_initial": "je"},
    # French
    "french": {**_ROMAN_BASE, "ж": "j", "й": "i", "х": "kh", "ч": "tch", "ш": "ch",
               "щ": "chtch", "у": "ou", "ъ": "", "ю": "iou", "я": "ia", "ё": "io",
               "_e_initial": "ie"},
    # pre-2013 Russian passport practice (French-influenced, simplified)
    "legacy_passport": {**_ROMAN_BASE, "й": "y", "х": "kh", "ю": "yu", "я": "ya",
                        "ё": "e", "ъ": "", "ы": "y"},
}


def romanize(text: str, system: str = "icao") -> str:
    table = ROMANIZATION_SYSTEMS[system]
    e_init = table.get("_e_initial")
    out = []
    prev = " "
    for ch in text:
        low = ch.lower()
        if low in table:
            if low == "е" and e_init and (not prev.strip() or prev in _CYR_VOWELS or prev in _CYR_SIGNS or prev == "-"):
                r = e_init
            else:
                r = table[low]
            if ch.isupper() and r:
                r = r[0].upper() + r[1:]
            out.append(r)
        else:
            out.append(ch)
        prev = ch
    return "".join(out)


# ==========================================================================
# Chinese: char -> (pinyin, Wade-Giles, Cantonese/Jyutping-ish HK style)
# ==========================================================================
ZH_SURNAMES = {
    "王": ("Wang", "Wang", "Wong"), "李": ("Li", "Li", "Lee"),
    "张": ("Zhang", "Chang", "Cheung"), "刘": ("Liu", "Liu", "Lau"),
    "陈": ("Chen", "Ch'en", "Chan"), "杨": ("Yang", "Yang", "Yeung"),
    "黄": ("Huang", "Huang", "Wong"), "赵": ("Zhao", "Chao", "Chiu"),
    "吴": ("Wu", "Wu", "Ng"), "周": ("Zhou", "Chou", "Chow"),
    "徐": ("Xu", "Hsü", "Tsui"), "孙": ("Sun", "Sun", "Suen"),
    "朱": ("Zhu", "Chu", "Chu"), "胡": ("Hu", "Hu", "Wu"),
    "郭": ("Guo", "Kuo", "Kwok"), "何": ("He", "Ho", "Ho"),
    "林": ("Lin", "Lin", "Lam"), "高": ("Gao", "Kao", "Ko"),
    "梁": ("Liang", "Liang", "Leung"), "郑": ("Zheng", "Cheng", "Cheng"),
    "谢": ("Xie", "Hsieh", "Tse"), "罗": ("Luo", "Lo", "Law"),
    "宋": ("Song", "Sung", "Sung"), "唐": ("Tang", "T'ang", "Tong"),
    "冯": ("Feng", "Feng", "Fung"), "邓": ("Deng", "Teng", "Tang"),
    "许": ("Xu", "Hsü", "Hui"), "韩": ("Han", "Han", "Hon"),
    "曹": ("Cao", "Ts'ao", "Cho"), "蔡": ("Cai", "Ts'ai", "Choi"),
}
ZH_GIVEN = {
    "明": ("ming", "ming", "ming"), "伟": ("wei", "wei", "wai"),
    "华": ("hua", "hua", "wah"), "文": ("wen", "wen", "man"),
    "国": ("guo", "kuo", "kwok"), "建": ("jian", "chien", "kin"),
    "志": ("zhi", "chih", "chi"), "强": ("qiang", "ch'iang", "keung"),
    "军": ("jun", "chün", "kwan"), "平": ("ping", "p'ing", "ping"),
    "杰": ("jie", "chieh", "kit"), "丽": ("li", "li", "lai"),
    "芳": ("fang", "fang", "fong"), "静": ("jing", "ching", "ching"),
    "婷": ("ting", "t'ing", "ting"), "敏": ("min", "min", "man"),
    "霞": ("xia", "hsia", "ha"), "雪": ("xue", "hsüeh", "suet"),
    "玲": ("ling", "ling", "ling"), "晓": ("xiao", "hsiao", "hiu"),
    "欣": ("xin", "hsin", "yan"), "怡": ("yi", "i", "yi"),
    "嘉": ("jia", "chia", "ka"), "俊": ("jun", "chün", "chun"),
    "浩": ("hao", "hao", "ho"), "宇": ("yu", "yü", "yu"),
    "海": ("hai", "hai", "hoi"), "东": ("dong", "tung", "tung"),
    "峰": ("feng", "feng", "fung"), "宁": ("ning", "ning", "ning"),
    "安": ("an", "an", "on"), "永": ("yong", "yung", "wing"),
    "德": ("de", "te", "tak"), "成": ("cheng", "ch'eng", "shing"),
    "涛": ("tao", "t'ao", "to"), "鹏": ("peng", "p'eng", "pang"),
    "磊": ("lei", "lei", "lui"), "慧": ("hui", "hui", "wai"),
    "红": ("hong", "hung", "hung"), "梅": ("mei", "mei", "mui"),
}
ZH_SYSTEMS = ("pinyin", "pinyin_hyphen", "pinyin_space", "wade_giles",
              "wade_giles_plain", "cantonese")


def _wg_plain(s: str) -> str:
    return s.replace("'", "").replace("ü", "u").replace("Ü", "U")


def zh_render_parts(sur_char: str, given_chars: str, system: str) -> tuple[str, str]:
    idx = {"pinyin": 0, "pinyin_hyphen": 0, "pinyin_space": 0,
           "wade_giles": 1, "wade_giles_plain": 1, "cantonese": 2}[system]
    sur = ZH_SURNAMES[sur_char][idx]
    syl = [ZH_GIVEN[c][idx] for c in given_chars]
    if system == "pinyin":
        # pinyin apostrophe before a/o/e-initial syllable (Xi'an rule)
        g = syl[0] + "".join(("'" + s if s[0] in "aoe" else s) for s in syl[1:])
    elif system == "pinyin_space" or system == "cantonese":
        g = " ".join(syl)
    else:
        g = "-".join(syl)
    g = g[:1].upper() + g[1:]
    if system == "pinyin_space" or system == "cantonese":
        g = " ".join(w[:1].upper() + w[1:] for w in g.split())
    if system == "wade_giles_plain":
        sur, g = _wg_plain(sur), _wg_plain(g)
    return sur, g


# ==========================================================================
# Latin and other pools
# ==========================================================================
LATIN = {
    "latin_en": {
        "M": ["James", "William", "Oliver", "Thomas", "Daniel", "Matthew", "Robert", "Edward", "Henry", "Samuel", "Joseph", "Christopher"],
        "F": ["Emily", "Charlotte", "Sophie", "Hannah", "Olivia", "Elizabeth", "Margaret", "Rebecca", "Catherine", "Abigail"],
        "sur_on": ["Ash", "Brad", "Carr", "Dun", "Fair", "Gold", "Hal", "Kel", "Lang", "Mor", "Pen", "Red", "Stan", "Thorn", "Whit", "Wex", "Brack", "Hollo"],
        "sur_end": ["ford", "ley", "ton", "well", "wick", "by", "more", "field", "worth", "combe", "ridge", "shaw"],
    },
    "latin_es": {
        "M": ["José", "Juan", "Luis", "Carlos", "Javier", "Andrés", "Fernando", "Alejandro", "Diego", "Miguel", "Francisco"],
        "F": ["María", "Lucía", "Carmen", "Sofía", "Isabel", "Valentina", "Paula", "Elena", "Mónica", "Inés"],
        "sur_on": ["Al", "Bar", "Cas", "Fer", "Gal", "Iba", "Lo", "Mon", "Or", "Quin", "San", "Ver", "Zu", "Pe"],
        "sur_end": ["ández", "erra", "ondo", "ares", "edo", "uela", "ales", "illo", "ero", "ánchez", "ago", "oya"],
    },
    "latin_pt": {
        "M": ["João", "Pedro", "Tiago", "Rafael", "Gonçalo", "Lucas", "Mateus", "André", "Rodrigo", "Vinícius"],
        "F": ["Ana", "Beatriz", "Mariana", "Inês", "Larissa", "Juliana", "Camila", "Fernanda", "Leonor"],
        "sur_on": ["Al", "Bran", "Car", "Fon", "Gui", "Lo", "Mo", "Pe", "Ri", "Sal", "Tei", "Va"],
        "sur_end": ["eira", "ães", "inho", "anha", "ares", "edo", "ado", "ões", "ela", "eiro"],
    },
    "latin_de": {
        "M": ["Jürgen", "Lukas", "Maximilian", "Stefan", "Tobias", "Felix", "Matthias", "Florian", "Jörg", "Klaus"],
        "F": ["Anna", "Katharina", "Lena", "Sabine", "Johanna", "Ursula", "Jana", "Lea", "Mareike", "Jutta"],
        "sur_on": ["Brau", "Eich", "Fass", "Hof", "Kirch", "Lind", "Mühl", "Schw", "Stein", "Wald", "Wei", "Zim", "Bött", "Grün"],
        "sur_end": ["mann", "berger", "hauser", "ner", "ler", "bach", "dorf", "inger", "meier", "rath", "ecker"],
    },
    "latin_fr": {
        "M": ["Jean", "Pierre", "Luc", "François", "Mathieu", "Étienne", "Julien", "Benoît", "Antoine", "Rémi"],
        "F": ["Marie", "Camille", "Élodie", "Chloé", "Margaux", "Hélène", "Céline", "Sandrine", "Aurélie"],
        "sur_on": ["Beau", "Char", "Dal", "Four", "Gil", "Lam", "Mar", "Per", "Rou", "Ver", "Bon", "Cha", "Duf"],
        "sur_end": ["champ", "nier", "lier", "bert", "ault", "eau", "ière", "ard", "elle", "ot", "and"],
    },
    "yoruba": {
        "M": ["Oluwaseun", "Adebayo", "Babatunde", "Olumide", "Ayodele", "Oluwafemi", "Tunde", "Kayode", "Akinwale"],
        "F": ["Folasade", "Oluwakemi", "Adeola", "Titilayo", "Funmilayo", "Yetunde", "Abimbola", "Omolara"],
        "sur_on": ["Ade", "Ola", "Oyel", "Aki", "Ogun", "Bab", "Fol", "Ige", "Ojo", "Ade"],
        "sur_end": ["wale", "yemi", "kunle", "sanmi", "tola", "bisi", "doyin", "lowo", "toye"],
    },
    "igbo": {
        "M": ["Chukwuemeka", "Chinedu", "Obinna", "Ikenna", "Nnamdi", "Emeka", "Uchenna", "Chibuike", "Kelechi"],
        "F": ["Chiamaka", "Ngozi", "Adaeze", "Nkechi", "Chinwe", "Ifeoma", "Uchechi", "Amarachi"],
        "sur_on": ["Okon", "Eze", "Nwa", "Obi", "Okafor", "Uzo", "Anye", "Ibe", "Onu"],
        "sur_end": ["kwo", "chukwu", "nna", "ike", "dike", "gwu", "eme", "ora"],
    },
    "indian": {
        "M": ["Rajesh", "Suresh", "Arjun", "Vikram", "Rahul", "Anil", "Sanjay", "Karthik", "Venkatesh", "Mohammed"],
        "F": ["Lakshmi", "Priya", "Anjali", "Deepika", "Kavitha", "Sunita", "Meenakshi", "Pooja", "Divya"],
        "sur_on": ["Ra", "Kri", "Sri", "Su", "Ven", "Ba", "Na", "Pad", "Go", "Shan", "Mu", "Cha"],
        "sur_end": ["mani", "nathan", "swamy", "varma", "kumar", "nivasan", "rao", "reddy", "pillai", "dev", "shetty"],
    },
}
NICKNAMES = {
    "William": ["Will", "Bill"], "Robert": ["Rob", "Bob"], "Edward": ["Ed", "Ted"],
    "Thomas": ["Tom"], "Daniel": ["Dan"], "Matthew": ["Matt"], "Samuel": ["Sam"],
    "Joseph": ["Joe"], "Christopher": ["Chris"], "Elizabeth": ["Liz", "Beth"],
    "Margaret": ["Maggie", "Peggy"], "Rebecca": ["Becky"], "Catherine": ["Kate", "Cathy"],
    "Abigail": ["Abby"], "Henry": ["Harry"], "José": ["Pepe"], "Francisco": ["Paco"],
    "Alejandro": ["Alex"], "Oluwaseun": ["Seun"], "Oluwafemi": ["Femi"],
    "Babatunde": ["Tunde"], "Chukwuemeka": ["Emeka"], "Oluwakemi": ["Kemi"],
    "Folasade": ["Sade"], "Funmilayo": ["Funmi"], "Abimbola": ["Bimbo"],
}
INDIAN_RESPELL = [("Lakshmi", "Laxmi"), ("Srinivasan", "Shrinivasan"), ("sh", "s"),
                  ("Venkatesh", "Venkatesan"), ("ee", "i"), ("Mohammed", "Mohd."),
                  ("kumar", " Kumar"), ("th", "t")]


def strip_diacritics(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


# ==========================================================================
# data model
# ==========================================================================
@dataclass
class PersonName:
    """A fictional person's name in a script-neutral canonical form.

    ``given``/``surname`` hold canonical tokens: Arabic keys or literal
    stems, Cyrillic strings, Chinese characters, or Latin spellings.
    """
    origin: str
    sex: str
    given: list[str]
    surname: list[str]
    patronymic: str | None = None
    ar_article: str = "al-"
    meta: dict = field(default_factory=dict)

    # ---- rendering --------------------------------------------------------
    def systems(self) -> list[str]:
        if self.origin == "cyrillic":
            return list(ROMANIZATION_SYSTEMS)
        if self.origin == "chinese":
            return list(ZH_SYSTEMS)
        if self.origin == "arabic":
            return ["standard", "variant"]
        return ["standard", "ascii"]

    def parts(self, system: str | None = None, rng: random.Random | None = None,
              with_patronymic: bool = False) -> tuple[str, str]:
        """(given_names, surname) as strings under a spelling system.

        For Arabic and the 'variant' system, ``rng`` picks among spellings;
        without it the first (standard) spelling is used.
        """
        o = self.origin
        if o == "cyrillic":
            sys_ = system or "icao"
            g = [romanize(t, sys_) for t in self.given]
            if with_patronymic and self.patronymic:
                g.append(romanize(self.patronymic, sys_))
            return " ".join(g), " ".join(romanize(t, sys_) for t in self.surname)
        if o == "chinese":
            sur, g = zh_render_parts(self.surname[0], "".join(self.given), system or "pinyin")
            return g, sur
        if o == "arabic":
            vary = system == "variant" and rng is not None
            g = []
            for t in self.given:
                opts = ARABIC_GIVEN.get(t, [t])
                g.append(rng.choice(opts) if vary else opts[0])
            stem = self.surname[0]
            if vary:
                stem = _ar_respell(stem, rng)
                art = rng.choice(["al-", "Al-", "el-", "Al ", "", "Al"])
            else:
                art = self.ar_article
            return " ".join(g), _ar_article(stem, art)
        g, s = " ".join(self.given), " ".join(self.surname)
        if system == "ascii":
            g, s = strip_diacritics(g), strip_diacritics(s)
        return g, s

    def full(self, system: str | None = None, order: str = "given_first",
             rng: random.Random | None = None, with_patronymic: bool | None = None,
             upper_surname: bool = False) -> str:
        if with_patronymic is None:
            with_patronymic = self.origin == "cyrillic"
        g, s = self.parts(system, rng, with_patronymic)
        if upper_surname:
            s = s.upper()
        if order == "surname_first":
            return f"{s} {g}".strip()
        if order == "surname_comma":
            return f"{s}, {g}".strip(", ")
        return f"{g} {s}".strip()

    @property
    def canonical(self) -> str:
        order = "surname_first" if self.origin == "chinese" else "given_first"
        return self.full(order=order)

    def mrz_parts(self, system: str | None = None) -> tuple[str, str]:
        """(surname, given) as printed on a passport for this origin."""
        if system is None:
            system = {"cyrillic": "icao", "chinese": "pinyin"}.get(self.origin, "ascii")
            if self.origin == "arabic":
                system = "standard"
        g, s = self.parts(system, with_patronymic=False)
        if self.origin == "chinese":
            g = g.replace("'", "")
        return s, g


# ==========================================================================
# sampling
# ==========================================================================
def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _cyr_surname(rng: random.Random, sex: str) -> str:
    stem = rng.choice(_CYR_SYL_ON) + rng.choice(_CYR_SYL_V) + rng.choice(_CYR_SYL_C)
    if rng.random() < 0.4:
        stem += rng.choice(_CYR_SYL_V) + rng.choice(_CYR_SYL_C)
    m, f = rng.choice(_CYR_SUFFIX)
    # avoid vowel clashes like '...аов'
    return stem + (f if sex == "F" else m)


def _ar_surname(rng: random.Random) -> str:
    return (rng.choice(_AR_SUR_ONSET) + rng.choice(_AR_SUR_V1)
            + rng.choice(_AR_SUR_MID) + rng.choice(_AR_SUR_END))


def _latin_surname(rng: random.Random, pool: dict) -> str:
    return rng.choice(pool["sur_on"]) + rng.choice(pool["sur_end"])


def sample_name(rng: random.Random, origin: str | None = None,
                sex: str | None = None, max_tries: int = 50) -> PersonName:
    origin = origin or rng.choice(ORIGINS)
    sex = sex or rng.choice("MF")
    for _ in range(max_tries):
        n = _sample_once(rng, origin, sex)
        if not any(is_blocked(n.full(system=s)) for s in n.systems()[:2]):
            return n
    raise RuntimeError("could not sample a non-blocked name")


def _sample_once(rng: random.Random, origin: str, sex: str) -> PersonName:
    if origin == "arabic":
        pool = ARABIC_GIVEN_F if sex == "F" else ARABIC_GIVEN_M
        given = [rng.choice(list(pool))]
        if rng.random() < 0.5:  # father's name as second given (nasab-style)
            given.append(rng.choice(list(ARABIC_GIVEN_M)))
        return PersonName(origin, sex, given, [_ar_surname(rng)],
                          ar_article=rng.choice(["al-", "Al-", "Al ", ""]))
    if origin == "cyrillic":
        given = [rng.choice(CYR_GIVEN_F if sex == "F" else CYR_GIVEN_M)]
        return PersonName(origin, sex, given, [_cyr_surname(rng, sex)],
                          patronymic=patronymic(rng.choice(CYR_FATHERS), sex))
    if origin == "chinese":
        sur = rng.choice(list(ZH_SURNAMES))
        k = 1 if rng.random() < 0.3 else 2
        chars = rng.sample(list(ZH_GIVEN), k)
        return PersonName(origin, sex, chars, [sur])
    pool = LATIN[origin]
    given = [rng.choice(pool[sex])]
    if rng.random() < 0.3:
        extra = rng.choice(pool[sex])
        if extra != given[0]:
            given.append(extra)
    sur = [_latin_surname(rng, pool)]
    if origin in ("latin_es", "latin_pt") or (origin == "latin_en" and rng.random() < 0.05):
        sur.append(_latin_surname(rng, pool))
    return PersonName(origin, sex, given, sur)


# ==========================================================================
# variants and aliases
# ==========================================================================
def spelling_variants(name: PersonName, rng: random.Random, k: int = 5) -> list[str]:
    """Up to ``k`` distinct given-first spellings of the same person."""
    seen: dict[str, None] = {}
    target = name.full()
    systems = name.systems()
    for _ in range(k * 8):
        if len(seen) >= k:
            break
        s = rng.choice(systems)
        v = name.full(system=s, rng=rng,
                      with_patronymic=name.origin == "cyrillic" and rng.random() < 0.5)
        if name.origin in ("indian",) and rng.random() < 0.5:
            a, b = rng.choice(INDIAN_RESPELL)
            v = v.replace(a, b)
        if v != target:
            seen.setdefault(v)
    return list(seen)


def reorderings(name: PersonName, system: str | None = None) -> list[str]:
    g, s = name.parts(system)
    out = [f"{g} {s}", f"{s} {g}", f"{s.upper()}, {g}", f"{s.upper()} {g}"]
    toks = g.split()
    if len(toks) > 1:
        out.append(f"{toks[0]} {s}")                       # dropped middle name
        out.append(f"{toks[0]} {toks[1][0]}. {s}")         # middle initial
    if name.origin in ("latin_es", "latin_pt") and len(name.surname) > 1:
        out.append(f"{g} {name.surname[0]}")               # dropped maternal surname
        out.append(f"{g} {'-'.join(name.surname)}")
    if name.origin == "indian":
        out.append(f"{s[0]}. {g}")                         # South Indian initial style
    return list(dict.fromkeys(o.strip() for o in out))


def aliases(name: PersonName, rng: random.Random, k: int = 4) -> list[str]:
    """Watchlist-style a.k.a. list: spelling variants, reorderings, nicknames,
    and (Arabic) kunya-style 'Abu X' aliases."""
    pool = spelling_variants(name, rng, k=k + 2) + reorderings(name, rng.choice(name.systems()))
    g, s = name.parts()
    for t in name.given:
        for nick in NICKNAMES.get(t, []):
            pool.append(f"{nick} {s}")
    if name.origin == "arabic" and name.sex == "M":
        son = rng.choice(list(ARABIC_GIVEN_M))
        pool.append(f"Abu {ARABIC_GIVEN_M[son][0]}")
    pool = [p for p in dict.fromkeys(pool) if p != name.full()]
    rng.shuffle(pool)
    return pool[:k]


def similar_other_person(name: PersonName, rng: random.Random) -> PersonName:
    """A *different* fictional person whose name is confusably close
    (same surname, different given name, or same given name, different
    surname). Used to build false-positive screening hits."""
    other = sample_name(rng, name.origin, name.sex)
    if rng.random() < 0.5:
        other.surname = list(name.surname)
        other.ar_article = name.ar_article
    else:
        other.given = list(name.given)
    if other.full() == name.full():
        return similar_other_person(name, rng)
    return other
