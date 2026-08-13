class AuthMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "invalid_credential": "Email atau kata sandi yang Anda masukkan tidak sesuai. Silakan periksa kembali dan coba lagi."
        }
