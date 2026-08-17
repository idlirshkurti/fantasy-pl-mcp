import unittest
from server import allowed, token_ok
class GatewaySecurityTests(unittest.TestCase):
 def test_token(self):
  self.assertTrue(token_ok("Bearer secret","secret")); self.assertFalse(token_ok("Bearer wrong","secret"))
 def test_credential_update_is_blocked(self):
  self.assertFalse(allowed("update_fpl_credentials")); self.assertTrue(allowed("get_gameweek_status"))
if __name__=="__main__": unittest.main()
