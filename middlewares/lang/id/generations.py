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
        }
