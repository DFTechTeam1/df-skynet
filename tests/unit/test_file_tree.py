import pytest
from unittest.mock import AsyncMock
import services.files as files
from services.dto.format_response import FolderAction, TreeFolder
from services.generations import reference_sections
from services.mysql.model.df_engine_generations import GenerationKinds
from services.mysql.model.df_engine_upload_files import UploadFileTypes

BASE = "storage/DF-Engine/Proj_abc"


def _upload(path, user_id=1, uid="u1"):
    return {
        "file_uid": uid,
        "name": path.rsplit("/", 1)[-1],
        "type": "image",
        "icon": "mdi-image",
        "color": "blue",
        "path": path,
        "url": f"https://x/{path}",
        "size": "1 KB",
        "created_at": "now",
        "creator": {"user_id": user_id, "image": None, "nickname": "n"},
    }


def _generated(path, uid="g1", kind="image_edit", user_id=1):
    return {
        "file_uid": uid,
        "name": path.rsplit("/", 1)[-1],
        "path": f"{files.UDIN_BASE_URL}/{path.replace(' ', '%20')}",
        "kind": kind,
        "icon": "mdi-image-edit",
        "color": "indigo",
        "size": "1 KB",
        "created_at": "now",
        "creator": {"user_id": user_id, "image": None, "nickname": "n"},
        "action": {
            "can_archieve": False,
            "can_unarchieve": False,
            "can_set_main": False,
            "can_favorited": True,
            "can_unfavorited": False,
            "can_download": True,
            "can_fetch_detail": True,
            "can_use_as_reference": True,
            "can_use_as_edit": True,
        },
    }


class TestFolderAction:
    def test_type_root_is_fixed_but_can_nest(self):
        """upload/<type> (depth 2) cannot be renamed/deleted/moved yet accepts subfolders and moves into it."""
        action = files.folder_action(2, 3)
        assert (action.can_create_subfolder, action.can_receive_move) == (True, True)
        assert (action.can_rename, action.can_delete, action.can_choose_to_move) == (False, False, False)

    def test_subfolder_is_actionable_and_stops_nesting_at_the_depth_limit(self):
        """A subfolder can be renamed/deleted/moved; once its chain reaches the limit it takes no more subfolders."""
        assert files.folder_action(3, 3).can_rename is True
        assert files.folder_action(5, 3).can_create_subfolder is False

    def test_project_level_folders_have_no_actions_but_nesting_is_off(self):
        """Folders above the type root (depth < 2) are not actionable and cannot receive subfolders."""
        assert files.folder_action(0, 3) == FolderAction()


class TestFormatFileTree:
    def test_empty_inputs_return_empty_dict(self):
        """No files at all means no project folder, so the result is `{}`."""
        assert files.format_file_tree([], [], 1, 3) == {}

    def test_nests_uploads_and_generated_files_under_one_root(self):
        """Uploads and generated files are nested by storage path under the single project root dict."""
        tree = files.format_file_tree(
            [_upload(f"{BASE}/upload/images/a.jpg")], [_generated(f"{BASE}/generated/images/b.png")], 1, 3
        )
        assert tree["path"] == BASE and tree["kind"] == "folder"
        assert [c["name"] for c in tree["children"]] == ["upload", "generated"]
        generated = tree["children"][1]["children"][0]["files"][0]
        assert generated["kind"] == "image_edit" and generated["url"].endswith("b.png")

    def test_generated_file_without_a_path_is_skipped(self):
        """A generation row with no stored path cannot be placed, so it is ignored."""
        row = _generated(f"{BASE}/generated/images/b.png")
        row["path"] = None
        assert files.format_file_tree([], [row], 1, 3) == {}

    def test_file_shallower_than_a_project_folder_is_ignored(self):
        """A path with fewer than the `storage/DF-Engine/<project>` levels has nowhere to live."""
        assert files.format_file_tree([_upload("storage/DF-Engine/lonely.jpg")], [], 1, 3) == {}

    def test_foreign_file_strips_actions_from_its_subfolder_only(self):
        """A subfolder that directly holds another user's file loses all actions; the shared type root keeps its own."""
        tree = files.format_file_tree([_upload(f"{BASE}/upload/images/sub/a.jpg", user_id=2)], [], 1, 3)
        images = tree["children"][0]["children"][0]
        sub = images["children"][0]
        assert sub["action"]["can_rename"] is False and sub["action"]["can_delete"] is False
        assert images["action"]["can_receive_move"] is True
        assert sub["files"][0]["action"]["can_delete"] is False

    def test_own_file_keeps_subfolder_actions(self):
        """When every file under a subfolder is the caller's, the subfolder stays actionable."""
        tree = files.format_file_tree([_upload(f"{BASE}/upload/images/sub/a.jpg")], [], 1, 3)
        sub = tree["children"][0]["children"][0]["children"][0]
        assert sub["action"]["can_rename"] is True
        assert sub["files"][0]["action"]["can_delete"] is True


class TestFindFolder:
    TREE = {"path": "a", "children": [{"path": "a/b", "children": [{"path": "a/b/c"}]}, {"path": "a/d"}]}

    def test_matches_root(self):
        """The root itself is a valid target."""
        assert files.find_folder(self.TREE, "a") is self.TREE

    def test_matches_deeply_nested(self):
        """A nested folder is found by walking `children`."""
        assert files.find_folder(self.TREE, "a/b/c") == {"path": "a/b/c"}

    def test_unknown_path_is_none(self):
        """A path absent from the tree returns None."""
        assert files.find_folder(self.TREE, "a/x") is None
        assert files.find_folder({"path": "a"}, "a/x") is None


class TestBuildFileTree:
    @pytest.mark.parametrize(
        "is_song,upload_kwargs", [(False, {"task_id": 7, "song_id": None}), (True, {"task_id": None, "song_id": 7})]
    )
    async def test_scopes_uploads_by_task_or_song_and_my_task(self, monkeypatch, is_song, upload_kwargs):
        """Uploads are queried by task_id or song_id; `my_task` narrows them to the caller while generated files do not follow it."""
        get_uploads = AsyncMock(return_value=[])
        monkeypatch.setattr(files, "get_user_uploaded_files", get_uploads)
        monkeypatch.setattr(files, "get_generation_main_files", AsyncMock(return_value=[]))
        monkeypatch.setattr(files, "get_admin_settings", AsyncMock(return_value={"folder_depth_limit": 3}))

        tree = await files.build_file_tree(object(), {"id": 7, "is_song": is_song}, 5, my_task=True)
        assert tree == {}
        get_uploads.assert_awaited_once_with(unittest_any(), user_id=5, **upload_kwargs)

    async def test_falls_back_to_the_default_depth_limit_when_settings_are_unsaved(self, monkeypatch):
        """Missing admin settings (no `folder_depth_limit` key) must not crash the tree, the payload default (4) applies."""
        seen = {}
        monkeypatch.setattr(files, "get_user_uploaded_files", AsyncMock(return_value=[]))
        monkeypatch.setattr(files, "get_generation_main_files", AsyncMock(return_value=[]))
        monkeypatch.setattr(files, "get_admin_settings", AsyncMock(return_value={}))
        monkeypatch.setattr(
            files, "format_file_tree", lambda up, gen, user_id, limit: seen.setdefault("limit", limit) and {}
        )

        await files.build_file_tree(object(), {"id": 1, "is_song": False}, 1)
        assert seen["limit"] == 4


def unittest_any():
    from unittest.mock import ANY

    return ANY


class TestReferenceSections:
    def test_always_returns_the_three_sections_in_order(self):
        """With no rows the payload still lists Image Uploads, Image Generations and Elements with total 0."""
        assert reference_sections([], []) == [
            {"type": "Image Uploads", "total_data": 0, "files": []},
            {"type": "Image Generations", "total_data": 0, "files": []},
            {"type": "Elements", "total_data": 0, "files": []},
        ]

    def test_routes_rows_and_drops_unsupported_kinds(self):
        """Image uploads and image/element generations are kept; video uploads and video/other generations are dropped."""
        sections = reference_sections(
            [{"kind": UploadFileTypes.image, "file": "u-img"}, {"kind": UploadFileTypes.video, "file": "u-vid"}],
            [
                {"kind": GenerationKinds.image, "file": "g-img"},
                {"kind": GenerationKinds.element, "file": "g-el"},
                {"kind": GenerationKinds.video, "file": "g-vid"},
                {"kind": GenerationKinds.image_edit, "file": "g-edit"},
            ],
        )
        by_type = {s["type"]: s for s in sections}
        assert by_type["Image Uploads"]["files"] == ["u-img"]
        assert by_type["Image Generations"]["files"] == ["g-img"]
        assert by_type["Elements"]["files"] == ["g-el"] and by_type["Elements"]["total_data"] == 1


def test_tree_folder_defaults_identify_it_as_a_folder():
    """Every TreeFolder carries kind=folder plus the shared folder icon and colour."""
    folder = TreeFolder(name="x", path="a/x", action=FolderAction()).model_dump(mode="json")
    assert (folder["kind"], folder["icon"], folder["color"]) == ("folder", "mdi-folder", "amber")


class TestGlobalReferenceSections:
    @staticmethod
    def _row(kind, project_id, task_id, file, project_name="P", task_name="T"):
        return {
            "kind": kind,
            "project_id": project_id,
            "project_name": f"{project_name}{project_id}",
            "task_id": task_id,
            "task_name": f"{task_name}{task_id}",
            "file": file,
        }

    def test_always_returns_the_three_sections_with_no_projects(self):
        """With no rows each section is still listed, empty, with total 0."""
        from services.generations import global_reference_sections

        assert global_reference_sections([], []) == [
            {"type": "Image Uploads", "total_data": 0, "projects": []},
            {"type": "Image Generations", "total_data": 0, "projects": []},
            {"type": "Elements", "total_data": 0, "projects": []},
        ]

    def test_groups_files_by_project_then_task_in_first_seen_order(self):
        """Files land under their project and task; both keep the order they first appear in, and totals count files."""
        from services.generations import global_reference_sections

        image = UploadFileTypes.image
        sections = global_reference_sections(
            [
                self._row(image, 2, 20, "a"),
                self._row(image, 1, 10, "b"),
                self._row(image, 2, 21, "c"),
                self._row(image, 2, 20, "d"),
            ],
            [],
        )
        uploads = sections[0]
        assert uploads["total_data"] == 4
        assert [p["id"] for p in uploads["projects"]] == [2, 1]
        project2 = uploads["projects"][0]
        assert project2["name"] == "P2"
        assert [t["id"] for t in project2["tasks"]] == [20, 21]
        assert project2["tasks"][0] == {"id": 20, "name": "T20", "files": ["a", "d"]}

    def test_routes_kinds_and_drops_unsupported_ones(self):
        """Image uploads, image and element generations are kept; video uploads and other kinds are dropped."""
        from services.generations import global_reference_sections

        sections = {
            s["type"]: s
            for s in global_reference_sections(
                [self._row(UploadFileTypes.video, 1, 1, "u-vid"), self._row(UploadFileTypes.image, 1, 1, "u-img")],
                [
                    self._row(GenerationKinds.image, 1, 1, "g-img"),
                    self._row(GenerationKinds.element, 3, 4, "g-el"),
                    self._row(GenerationKinds.video, 1, 1, "g-vid"),
                    self._row(GenerationKinds.image_edit, 1, 1, "g-edit"),
                ],
            )
        }
        assert sections["Image Uploads"]["projects"][0]["tasks"][0]["files"] == ["u-img"]
        assert sections["Image Generations"]["total_data"] == 1
        assert sections["Elements"]["projects"][0]["tasks"][0]["id"] == 4
