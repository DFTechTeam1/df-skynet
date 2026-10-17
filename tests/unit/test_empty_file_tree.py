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
