import contextlib
import io
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import remove_annotations


class FakeClient:
    def __init__(self, *args):
        self.deleted = []

    def check_connection(self):
        return {"id": "user123", "login": "tester"}

    def slides(self, destination):
        self.destination = destination
        return [SimpleNamespace(id="slide1"), SimpleNamespace(id="slide2")]

    def annotations(self, item_id):
        return {
            "slide1": [
                {"_id": "ann1", "annotation": {"name": "Tumor"}},
                {"_id": "ann2", "annotation": {"name": "Stroma"}},
                {"annotation": {"name": "Missing ID"}},
            ],
            "slide2": [
                {"_id": "ann1", "annotation": {"name": "Duplicate ID"}},
                {"_id": "ann3", "annotation": {"name": ""}, "_active": False},
            ],
        }[item_id]

    def delete_annotation(self, annotation_id):
        self.deleted.append(annotation_id)


class RemoveAnnotationsTests(unittest.TestCase):
    def run_main(self, argv):
        stdout = io.StringIO()
        client = FakeClient()
        with patch.object(sys, "argv", ["remove_annotations.py", *argv]), \
             patch.object(remove_annotations, "api_key", return_value="test-key"), \
             patch.object(remove_annotations, "AthenaClient", return_value=client), \
             contextlib.redirect_stdout(stdout):
            status = remove_annotations.main()
        return status, stdout.getvalue(), client

    def test_default_destination_is_provided_collection_and_preview_keeps_annotations(self):
        status, output, client = self.run_main([])
        self.assertEqual(status, 0)
        self.assertEqual(client.destination, remove_annotations.DEFAULT_DESTINATION)
        self.assertEqual(client.deleted, [])
        self.assertIn("WSI items: 2; annotations found: 2", output)
        self.assertIn("Preview only", output)

    def test_destination_argument_and_apply_delete_every_unique_annotation(self):
        destination = "https://athena.rc.ufl.edu/#collection/123"
        status, output, client = self.run_main([destination, "--apply"])
        self.assertEqual(status, 0)
        self.assertEqual(client.destination, destination)
        self.assertEqual(client.deleted, ["ann1", "ann2"])
        self.assertIn("Deleted: 2; failed: 0", output)


if __name__ == "__main__":
    unittest.main()
