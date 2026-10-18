# Reader bench: `step7_serving/prechecks.py`

Sources: reader_dev, dev; 300 cases per family; seed 0. Cell = coverage (share not n/d); **Nx** = N wrong values.

## Fuzz families

| set | dropped | as_of | mrz | expiry | expired | poa_date | poa_window | integ_date_of_birth | integ_document_number | integ_expiry | integ_overall | wrong |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| F-kv | 0 | 62% | 100% | 96% | 61% | 0% | 0% | 0% | 1% | 0% | 0% | 0 |
| F-prose | 0 | 21% | 100% | 91% | 19% | 2% | 0% | 0% | 0% | 0% | 0% | 0 |
| F-email | 0 | 44% | 100% | 93% | 41% | 3% | 1% | 0% | 5% | 1% | 0% | 0 |
| F-table | 0 | 29% | 100% | 91% | 28% | 5% | 2% | 0% | 0% | 0% | 0% | 0 |
| F-json | 0 | 0% | 100% | 91% | 0% | 0% | 0% | 0% | 0% | 0% | 0% | 0 |
| F-bullets | 0 | 58% | 100% | 91% | 53% | 2% **1x** | 2% **1x** | 2% | 4% | 1% | 1% | 2 |
| F-nolabel | 0 | 15% | 100% | 92% | 14% | 2% **2x** | 1% **1x** | 0% | 0% | 0% | 0% | 3 |
| F-noisy | 0 | 31% | 92% | 85% | 27% | 3% **1x** | 1% | 0% | 1% | 0% | 0% | 1 |
| F-heldout | 0 | 0% | 100% | 92% | 0% | 0% | 0% | 0% | 0% | 0% | 0% | 0 |

## Original packets per generator style

| set | dropped | as_of | mrz | expiry | expired | poa_date | poa_window | integ_date_of_birth | integ_document_number | integ_expiry | integ_overall | wrong |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| reader_dev/email | 0 | 100% | 100% | 96% | 96% | 88% | 88% | 97% | 100% | 98% | 97% | 0 |
| reader_dev/form | 0 | 100% | 100% | 97% | 97% | 87% | 87% | 95% | 100% | 96% | 95% | 0 |
| reader_dev/kv | 0 | 100% | 100% | 92% | 92% | 90% | 90% | 96% | 100% | 96% | 93% | 0 |
| reader_dev/mixed | 0 | 100% | 100% | 94% | 94% | 98% | 98% | 97% | 99% | 96% | 95% | 0 |
| reader_dev/ocr_dump | 0 | 100% | 100% | 91% | 91% | 0% | 0% | 0% | 0% | 0% | 0% | 0 |
| reader_dev/prose | 0 | 100% | 100% | 99% | 99% | 91% | 91% | 97% | 100% | 97% | 97% | 0 |
| dev/form | 0 | 100% | 100% | 98% | 98% | 88% | 88% | 100% | 100% | 100% | 100% | 0 |
| dev/kv | 0 | 100% | 100% | 86% | 86% | 84% | 84% | 95% | 100% | 97% | 95% | 0 |
| dev/mixed | 0 | 100% | 100% | 95% | 95% | 95% | 95% | 95% | 100% | 95% | 95% | 0 |
| dev/prose | 0 | 100% | 100% | 96% | 96% | 89% | 89% | 100% | 100% | 96% | 96% | 0 |

### WRONG F-bullets poa_date trn-1500000-000417: reader=1991-12-04 truth=2026-07-04
```
* Document: Council tax bill


Name screening hits
H1: UN-SC-CONSOLIDATED-SYN (sanctions) - listed name Paula LOUELA MONILLO, listed DOB 1991-12-04, nationality ESP, match score 85


## Customer details
- Residential address: 167 Kestrelhollow Street, LEEDS, LS10 3JD
```

### WRONG F-bullets poa_window trn-1500000-000417: reader=OLDER THAN 90 DAYS truth=WITHIN 90 DAYS
```
Request:
• Case ID: KYC-2608-124510
• Booking country: GB
• Account type: business_account
• Channel: mobile app
• Application date: AUGUST 19th, 2026
• Assessed as of: 19 aug 2026

POA:
* Customer name: Paula Aluela Verondo
* From: Municipal Revenue Office
*  Correspondence  address:   167   Kestrelhollow   Street,  LEEDS,   LS10 3JD
* Statement date: [smudged]
* Document: Council tax bill


Name screening hits
H1: UN-SC-CONSOLIDATED-SYN (sanctions) - listed name Paula LOUELA MONILLO, listed DOB 1991-12-04, nationality ESP, match score 85


## Customer details
- Residential address: 167 Kestrelhollow Street, LEEDS, LS10 3JD
- Source of funds: savings
- Born: 02.03.1974

- Citizenship: MEX
- Occupation: Restaurant owner
- Expected turnover / month: 7900 GBP
- Employer: Silverpine Holdings

```

### WRONG F-nolabel poa_date trn-1500000-000579: reader=1982-03-10 truth=2026-03-24
```
• Data: 8 April 2026

## Customer  details
* Line: Flat 2176, Marina Crest Building, Street 6, Al Mizhar, Makani 6141326447, P.O. Box 22689, Ras Al Khaimah
* Info: MARCH 10th, 1982
* Occupation: Used car dealer
* Item: Ali Kajashi
* business_income
* Employed by: Quillstone Partners
```

### WRONG F-nolabel poa_date trn-1500000-000524: reader=1989-06-16 truth=2025-12-31
```
- Item: Flat 236, Ganga Vihar Apartments, 499, 15th Cross, Jayanagar, Near Metro Station, Pune, Maharashtra 411397


Screening
H1: PEP-DB-SYN (pep) - listed name Alejandro Jose Verondo Veruela, listed DOB 1989-06-16, nationality ARE, match score 84

```

### WRONG F-nolabel poa_window trn-1500000-000524: reader=OLDER THAN 90 DAYS truth=WITHIN 90 DAYS
```
##  Jurisdiction  and  product
  - Review date (as of): 26th february 2026
    -  Product  requested: crypto_wallet
  - Field: KYC-2602-917590
  - Channel: mobile app
  - Attr: IN
  - Box: 26/02/26


Customer:
* Line: Luis Verondo Veruela
* Born: 29 Aug 2002
* Citizenship: MEX
* Home address: Flat 236, Ganga Vihar Apartments, 499, 15th Cross, Jayanagar, Near Metro Station, Pune, Maharashtra 411397
* Profession: Registered nurse
Confidential - for compliance use only.
* Employed by: Harrowfield Clinic
* savings
* Expected   turnover /   month:   369500   INR

Page 1 of 5

•   Entry: PASSPORT
• MEX
• Note: Verondo Veruela
• Forenames: Luis
• MEX
• 28 jul 2004
• 5 JANUARY 2026
• Info: 04-JAN-2036
•  Document number:  L93667178
• Sexe: M
• Ministry of Foreign Affairs
• Columbus
P<MEXVERONDO<VE
```

### WRONG F-noisy poa_date trn-1500000-000319: reader=2025-06-16 truth=2026-01-01
```
info is given as department of residcncy services.

CHEERS,
ONBOARDING OPS
Downloaded 2025-06-16

```

