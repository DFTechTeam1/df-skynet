from services.files import FilesService
from services.mysql.model.df_engine_upload_files import UploadFileTypes

service = FilesService()


class TestBaseOf:
    def test_strips_from_upload_marker(self):
        """Everything from `/upload/` onward is stripped."""
        assert service.base_of("storage/DF-Engine/proj/upload/images/a.png") == "storage/DF-Engine/proj"

    def test_strips_from_generated_marker(self):
        """Everything from `/generated/` onward is stripped."""
        assert service.base_of("storage/DF-Engine/proj/generated/videos/a.mp4") == "storage/DF-Engine/proj"

    def test_no_marker_returns_path_unchanged(self):
        """A path with neither marker is returned as-is."""
        assert service.base_of("storage/DF-Engine/proj/other/a.png") == "storage/DF-Engine/proj/other/a.png"


class TestTypeRootOf:
    def test_matches_the_root_itself(self):
        """The type root path itself is recognized."""
        assert service.type_root_of("proj/upload/images") == "proj/upload/images"

    def test_matches_a_path_nested_under_the_root(self):
        """A folder nested under a type root resolves to that root."""
        assert service.type_root_of("proj/upload/images/2024/sub") == "proj/upload/images"

    def test_generated_videos_root(self):
        """The generated/videos root is also recognized."""
        assert service.type_root_of("proj/generated/videos/clip") == "proj/generated/videos"

    def test_outside_any_root_returns_none(self):
        """A path outside all four type roots returns None."""
        assert service.type_root_of("proj/other/images") is None


class TestRawPathFileUrlRoundTrip:
    def test_file_url_then_raw_path_recovers_original(self):
        """file_url() -> raw_path() round-trips back to the original storage path."""
        path = "storage/DF-Engine/proj/upload/images/my file.png"
        assert service.raw_path(service.file_url(path)) == path

    def test_raw_path_passes_through_a_non_prefixed_url_unchanged(self):
        """A URL not carrying the udin base prefix is decoded but otherwise passed through."""
        assert service.raw_path("some/other/path%20here") == "some/other/path here"


class TestBuildFileTree:
    def _file(self, path, uid="f1", created_by=1):
        return {
            "uid": uid,
            "name": path.rsplit("/", 1)[-1],
            "path": path,
            "size": 10,
            "md5": None,
            "created_by": created_by,
            "created_by_user": None,
            "updated_by_user": None,
        }

    def _type_root_node(self, tree):
        """Descend proj -> upload -> images to the type-root node every test file lands in."""
        return tree[0]["childs"][0]["childs"][0]

    def test_empty_input_returns_empty_tree(self):
        """No files produces an empty tree."""
        assert service.build_file_tree([], user_id=1) == []

    def test_nests_folders_by_path_segments(self):
        """A file one level under a type root nests one extra folder below it."""
        files = [self._file("proj/upload/images/2024/a.png")]
        tree = service.build_file_tree(files, user_id=1)
        root_node = self._type_root_node(tree)
        assert root_node["folder"] == "proj/upload/images"
        assert root_node["childs"][0]["folder"] == "proj/upload/images/2024"
        assert root_node["childs"][0]["files"][0]["uid"] == "f1"

    def test_owner_can_rename_and_delete_own_file(self):
        """The uploading user's own file allows rename/delete."""
        files = [self._file("proj/upload/images/a.png", created_by=1)]
        tree = service.build_file_tree(files, user_id=1)
        actions = self._type_root_node(tree)["files"][0]["actions"]
        assert actions["can_rename"] is True
        assert actions["can_delete"] is True

    def test_non_owner_cannot_modify_file(self):
        """A file created by someone else denies rename/delete for the current user."""
        files = [self._file("proj/upload/images/a.png", created_by=2)]
        tree = service.build_file_tree(files, user_id=1)
        actions = self._type_root_node(tree)["files"][0]["actions"]
        assert actions["can_rename"] is False
        assert actions["can_delete"] is False

    def test_generated_file_can_never_be_deleted(self):
        """A generated file is never deletable, even by its own creator."""
        files = [self._file("proj/generated/images/a.png", created_by=1)]
        tree = service.build_file_tree(files, user_id=1)
        assert self._type_root_node(tree)["files"][0]["actions"]["can_delete"] is False

    def test_bare_folder_row_appears_with_no_files(self):
        """A type=folder row (created empty, no file inside it) still produces a folder node,
        identified by its own path so it can be targeted by delete/rename/move."""
        folder_row = {**self._file("proj/upload/images/empty_sub", uid="folder-1"), "type": UploadFileTypes.folder}
        tree = service.build_file_tree([folder_row], user_id=1)
        root_node = self._type_root_node(tree)
        assert root_node["childs"][0]["folder"] == "proj/upload/images/empty_sub"
        assert root_node["childs"][0]["files"] == []
        assert root_node["childs"][0]["childs"] == []

    def test_folder_node_type_is_folder(self):
        """Every folder node (type-root or nested) carries type="folder"."""
        files = [self._file("proj/upload/images/a.png")]
        tree = service.build_file_tree(files, user_id=1)
        assert self._type_root_node(tree)["type"] == "folder"

    def test_file_node_type_matches_images_or_videos_segment(self):
        """A file's type is derived from whether it sits under an images/ or videos/ path."""
        files = [
            self._file("proj/upload/images/a.png", uid="f1"),
            self._file("proj/upload/videos/b.mp4", uid="f2"),
        ]
        tree = service.build_file_tree(files, user_id=1)
        assert tree[0]["childs"][0]["childs"][0]["files"][0]["type"] == "image"
        assert tree[0]["childs"][0]["childs"][1]["files"][0]["type"] == "video"

    def test_folder_action_requires_every_nested_file_to_be_owned(self):
        """A folder holding another user's file loses folder-level actions, even for the current user's own files in it."""
        files = [
            self._file("proj/upload/images/a.png", uid="f1", created_by=1),
            self._file("proj/upload/images/b.png", uid="f2", created_by=2),
        ]
        tree = service.build_file_tree(files, user_id=1)
        root_node = self._type_root_node(tree)
        assert root_node["actions"]["can_rename"] is False
        assert root_node["actions"]["can_delete"] is False
