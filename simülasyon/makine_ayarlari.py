# Her makine için saniyede 10 ölçüm
OLCUM_ARALIGI = 0.1

# Fiziksel kesme gücü (kW)
NORMAL_KESME_GUCU = 11.52
ARIZALI_KESME_GUCU = 16.128

MAKINELER = [
    {
        "makine_id": "M1",
        "makine_adi": "15 Yıllık Torna",
        "bosta_guc": 3.2,
        "verim": 0.72,
        "bosta_gurultu": 0.25,
        "normal_gurultu": 0.60,
        "arizali_gurultu": 0.78,
        "kesme_suresi": 157.08,
    },
    {
        "makine_id": "M2",
        "makine_adi": "Eco CNC",
        "bosta_guc": 1.1,
        "verim": 0.90,
        "bosta_gurultu": 0.05,
        "normal_gurultu": 0.13,
        "arizali_gurultu": 0.17,
        "kesme_suresi": 157.08,
    },
    {
        "makine_id": "M3",
        "makine_adi": "Çift Aynalı CNC",
        "bosta_guc": 4.2,
        "verim": 0.86,
        "bosta_gurultu": 0.15,
        "normal_gurultu": 0.35,
        "arizali_gurultu": 0.43,
        "kesme_suresi": 78.54,
    },
]

# Her makinenin izleyeceği aşamalar
# Kesme sürelerini ilgili makinenin ayarından alacağız.
FAZLAR = [
    {"ad": "baslangic_bosta", "sure": 15.0, "durum": "idle"},
    {"ad": "normal_kesme", "sure": None, "durum": "working"},
    {"ad": "ara_bosta", "sure": 15.0, "durum": "idle"},
    {"ad": "arizali_kesme", "sure": None, "durum": "working"},
    {"ad": "bitis_bosta", "sure": 15.0, "durum": "idle"},
]

