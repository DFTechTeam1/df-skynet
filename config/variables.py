from decimal import Decimal

USD_TO_IDR_RATE = Decimal("16000")

# Roles that may rename / move / delete / image-edit files they did not create (backup when the creator is unavailable).
OVERRIDE_FILE_ROLES = [
    "root",
    "director",
    "project manager",
    "project manager admin",
    "project manager entertainment",
    "lead modeller",
]
