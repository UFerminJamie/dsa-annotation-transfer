import unittest
import json
import tempfile
from pathlib import Path

from download_dsa_annotations import GirderClient, download


class FolderTraversalTests(unittest.TestCase):
    def test_collection_walk_uses_girder_list_endpoints(self):
        client = GirderClient.__new__(GirderClient)
        calls = []
        responses = {
            ("/folder", "collection", "collection1"): [{"_id": "root"}],
            ("/folder", "folder", "root"): [{"_id": "nested"}],
            ("/folder", "folder", "nested"): [],
            ("/item", None, "root"): [{"_id": "item1"}],
            ("/item", None, "nested"): [{"_id": "item2"}],
        }

        def paged(path, *, params=None):
            params = params or {}
            calls.append((path, params.copy()))
            return responses[(path, params.get("parentType"),
                              params.get("parentId", params.get("folderId")))]

        client.paged = paged
        items = client.items_in_folder_tree("collection1", None)

        self.assertEqual(items, [{"_id": "item1"}, {"_id": "item2"}])
        self.assertEqual(calls[0], (
            "/folder", {"parentType": "collection", "parentId": "collection1"}))
        self.assertIn(("/folder", {"parentType": "folder", "parentId": "root"}), calls)
        self.assertIn(("/item", {"folderId": "root"}), calls)
        self.assertNotIn("/folder/root/folders", [path for path, _ in calls])

    def test_folder_walk_does_not_require_collection_id(self):
        client = GirderClient.__new__(GirderClient)
        calls = []

        def paged(path, *, params=None):
            calls.append((path, params or {}))
            if path == "/folder":
                return []
            return [{"_id": "item1"}]

        client.paged = paged
        items = client.items_in_folder_tree(None, "folder1")

        self.assertEqual(items, [{"_id": "item1"}])
        self.assertEqual(calls, [
            ("/folder", {"parentType": "folder", "parentId": "folder1"}),
            ("/item", {"folderId": "folder1"}),
        ])

    def test_download_selects_leading_space_name_and_preserves_it(self):
        summary = {"_id": "ann1", "annotation": {"name": " tubules"}}
        full = {"_id": "ann1", "annotation": {"name": " tubules", "elements": []}}

        class Client:
            def annotations_for_item(self, item_id):
                self.item_id = item_id
                return [summary]

            def full_annotation(self, annotation_id):
                self.annotation_id = annotation_id
                return full

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            stats = download(Client(), [{"_id": "item1", "name": "Sample.svs"}], output, False)
            self.assertEqual(stats["downloaded"], 1)
            saved = json.loads(next(output.glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(saved["annotation"]["name"], " tubules")


if __name__ == "__main__":
    unittest.main()
