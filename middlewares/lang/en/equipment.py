class EquipmentMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {"stock_exceeded": "The requested quantity exceeds the available stock."}
