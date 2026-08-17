class AuthMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "invalid_credential": "Email atau kata sandi yang Anda masukkan tidak sesuai. Silakan periksa kembali dan coba lagi.",
            "auth_not_configured": "Layanan autentikasi belum dikonfigurasi. Silakan hubungi administrator Anda.",
            "auth_unauthenticated": "Anda belum terautentikasi. Silakan login dan coba lagi",
            "permission_denied": "Anda tidak memiliki izin untuk mengakses fitur ini.",
            "no_permissions_found": "Akun Anda belum memiliki hak akses yang diberikan. Silakan hubungi administrator untuk mendapatkan akses.",
            "no_roles_found": "Akun Anda belum memiliki peran apa pun. Silakan hubungi administrator untuk pengaturan akses.",
            "role_not_authorized": "Peran Anda saat ini tidak memiliki akses ke fitur ini. Silakan hubungi administrator jika Anda merasa ini adalah kesalahan.",
        }
