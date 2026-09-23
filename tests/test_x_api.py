from __future__ import annotations

import unittest

from feed_forge.x_api import (
    ApiResponse,
    ResponseStructureError,
    parse_x_response,
    public_api_errors,
)


def response(body: object, status: int = 200) -> ApiResponse:
    return ApiResponse(status=status, body=body, headers={}, duration_ms=1)


class XApiResponseTests(unittest.TestCase):
    def test_parses_documented_single_resource_envelope(self) -> None:
        envelope = parse_x_response(
            response({"data": {"id": "1", "username": "person"}}),
            data_kind="object",
        )
        self.assertEqual("1", envelope.data["id"])
        self.assertEqual((), envelope.errors)

    def test_parses_documented_collection_with_partial_errors(self) -> None:
        envelope = parse_x_response(
            response(
                {
                    "data": [{"id": "1"}],
                    "errors": [
                        {
                            "status": 404,
                            "title": "Not Found Error",
                            "resource_id": "2",
                            "detail": "Could not find user.",
                        }
                    ],
                }
            ),
            data_kind="array",
        )
        self.assertEqual(1, len(envelope.data))
        self.assertEqual(1, len(public_api_errors(envelope.errors)))

    def test_normalizes_documented_empty_collection(self) -> None:
        envelope = parse_x_response(
            response({"meta": {"result_count": 0}}),
            data_kind="array",
        )
        self.assertEqual((), envelope.data)

    def test_accepts_errors_only_collection_for_batch_lookup(self) -> None:
        envelope = parse_x_response(
            response({"errors": [{"status": 404, "resource_id": "2"}]}),
            data_kind="array",
        )
        self.assertEqual((), envelope.data)
        self.assertEqual(1, len(envelope.errors))

    def test_rejects_malformed_success_instead_of_treating_it_as_empty(self) -> None:
        with self.assertRaisesRegex(ResponseStructureError, "must contain"):
            parse_x_response(response({}), data_kind="array")

    def test_rejects_wrong_data_shape(self) -> None:
        with self.assertRaisesRegex(ResponseStructureError, "JSON array"):
            parse_x_response(response({"data": {"id": "1"}}), data_kind="array")

    def test_rejects_invalid_ancillary_structures(self) -> None:
        with self.assertRaisesRegex(ResponseStructureError, "errors"):
            parse_x_response(
                response({"data": [], "errors": {"title": "wrong shape"}}),
                data_kind="array",
            )

    def test_rejects_non_successful_response(self) -> None:
        with self.assertRaisesRegex(ResponseStructureError, "non-successful"):
            parse_x_response(
                response({"title": "Forbidden"}, status=403),
                data_kind="object",
            )


if __name__ == "__main__":
    unittest.main()
