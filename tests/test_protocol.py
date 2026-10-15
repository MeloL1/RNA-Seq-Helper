import json
import unittest

from rnaseq_helper.domain.models import RJobRequest
from rnaseq_helper.r_bridge.protocol import decode_response, encode_request


class ProtocolTests(unittest.TestCase):
  def test_json_lines_roundtrip(self):
    request = RJobRequest("request-1", "ping", {"x": 1})
    encoded = encode_request(request)
    self.assertEqual(json.loads(encoded)["request_id"], "request-1")
    response = decode_response('{"request_id":"request-1","ok":true,"result":{"status":"ready"}}')
    self.assertTrue(response.ok)
    self.assertEqual(response.result["status"], "ready")
