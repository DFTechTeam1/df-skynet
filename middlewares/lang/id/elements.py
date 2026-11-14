class ElementsMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "element_created": "Elemen berhasil dibuat.",
            "elements_fetched": "Elemen berhasil diambil.",
            "element_fetched": "Elemen berhasil diambil.",
            "element_not_found": "Elemen tidak ditemukan.",
            "element_updated": "Elemen berhasil diperbarui.",
            "element_deleted": "Elemen berhasil dihapus.",
            "element_file_renamed": "File berhasil diubah namanya.",
            "element_file_not_found": "File tidak ditemukan.",
            "element_file_not_creator": "Hanya pengunggah file ini yang dapat mengubah namanya.",
            "element_uploaded": "Gambar berhasil diunggah.",
            "element_upload_no_files": "Lampirkan minimal satu gambar.",
            "element_upload_image_only": "Hanya gambar JPG, JPEG atau PNG yang dapat diunggah.",
            "element_upload_timeout": "Pengunggahan terlalu lama. Silakan coba lagi.",
            "element_has_generations": "Elemen tidak dapat dihapus karena sudah memiliki generasi.",
            "element_action_not_permitted": "Anda tidak memiliki izin untuk mengubah elemen ini.",
        }
