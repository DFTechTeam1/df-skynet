from services.files import format_file_tree_refactored


def test_empty_tree_returns_placeholder_skeleton():
    root = "storage/DF-Engine-DEV/Wedding_7b804b30"
    tree = format_file_tree_refactored([], [], 3, root)
    assert tree["path"] == root and tree["files"] == []
    paths = {c["path"]: c for c in tree["children"]}
    assert set(paths) == {f"{root}/upload", f"{root}/generated"}
    kinds = {g["name"] for c in paths.values() for g in c["children"]}
    assert kinds == {"images", "videos"}
    assert paths[f"{root}/upload"]["children"][0]["action"]["can_upload_file"] is True


def test_empty_tree_without_root_stays_empty():
    assert format_file_tree_refactored([], [], 3) == {}


def test_tree_order_is_fixed_whichever_side_has_data():
    """`generated` used to come first when only generations existed and `upload` first once something was uploaded."""
    from services.files import UDIN_BASE_URL

    root = "storage/DF-Engine-DEV/Wedding_7b804b30"
    base = {
        "kind": "image",
        "icon": "i",
        "color": "c",
        "size": "1 KB",
        "created_at": "2026-01-01T00:00:00",
        "creator": None,
    }
    gen = {
        **base,
        "id": 1,
        "file_uid": "g",
        "name": "g.png",
        "path": f"{UDIN_BASE_URL}/{root}/generated/videos/g.png",
        "action": {"can_rename": False, "can_move": False, "can_delete": False, "can_download": True},
    }
    up_file = {**base, "id": 2, "file_uid": "u", "name": "u.png", "url": "x", "path": f"{root}/upload/videos/u.png"}
    folder = {"kind": "folder", "path": f"{root}/upload/videos/sub", "action": {}}
    cases = [([], [gen]), ([folder], []), ([], [])]
    for uploaded, generated in cases:
        tree = format_file_tree_refactored(uploaded, generated, 3, root)
        assert [c["name"] for c in tree["children"]] == ["generated", "upload"]
        for child in tree["children"]:
            assert [g["name"] for g in child["children"]] == ["images", "videos"]


def test_flash_files_flags_path_down_to_folders_holding_files():
    from services.files import UDIN_BASE_URL

    root = "storage/DF-Engine-DEV/Wedding_7b804b30"
    gen = {
        "kind": "image",
        "icon": "i",
        "color": "c",
        "size": "1 KB",
        "created_at": "2026-01-01T00:00:00",
        "creator": None,
        "id": 1,
        "file_uid": "g",
        "name": "g.png",
        "path": f"{UDIN_BASE_URL}/{root}/generated/images/g.png",
        "action": {"can_rename": False, "can_move": False, "can_delete": False, "can_download": True},
    }

    def flags(tree, acc=None):
        acc = {} if acc is None else acc
        acc[tree["path"]] = tree["set_flash"]
        for c in tree["children"]:
            flags(c, acc)
        return acc

    assert not any(flags(format_file_tree_refactored([], [gen], 3, root)).values())
    flashed = {p for p, v in flags(format_file_tree_refactored([], [gen], 3, root, flash_files=True)).items() if v}
    assert flashed == {root, f"{root}/generated", f"{root}/generated/images"}  # root -> folder holding the file
