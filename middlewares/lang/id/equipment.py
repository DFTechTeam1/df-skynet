class EquipmentMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {"stock_exceeded": "Jumlah yang diminta melebihi stok yang tersedia."}
