class GenerationsMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "input_references_exceeded": "Kamu menambahkan terlalu banyak referensi untuk model ini.",
            "unsupported_generation_parameter": "Parameter ini tidak didukung oleh model yang dipilih.",
            "generation_parameters_invalid": "Beberapa parameter yang kamu kirim tidak didukung oleh model ini.",
            "generation_parameter_must_be_number": "Nilai ini harus berupa angka.",
            "generation_parameter_below_minimum": "Nilai ini terlalu kecil.",
            "generation_parameter_above_maximum": "Nilai ini terlalu besar.",
            "generation_parameter_not_in_enum": "Nilai ini bukan salah satu opsi yang diizinkan.",
            "generation_parameter_must_be_boolean": "Nilai ini harus true atau false.",
            "generation_parameter_required": "Parameter ini wajib diisi untuk model yang dipilih.",
            "references_invalid": "Ada referensi yang kamu kirim tidak valid.",
            "reference_format_udin_url_required": "Referensi DiVA ini belum memiliki URL file.",
            "reference_file_uid_required": "Referensi ini belum memiliki file.",
            "prompt_length_exceeded": "Prompt kamu {length} karakter, melebihi batas proyek ini yaitu {max_chars} karakter.",
            "feature_not_under_menu": "Ada fitur yang dipilih tidak termasuk dalam menu ini.",
            "generation_area_incomplete": "Untuk mengatur area fokus, x_min, x_max, y_min, dan y_max harus diisi semua.",
            "generation_area_image_edit_only": "Area fokus (x_min, x_max, y_min, y_max) hanya bisa diisi untuk image_edit.",
            "openrouter_generation_failed": "OpenRouter gagal membuat hasil ini. Silakan coba lagi nanti.",
            "api_key_token_usage_limit_exceeded": "API key ini sudah mencapai batas penggunaannya dan tidak bisa dipakai untuk generate lagi.",
        }
