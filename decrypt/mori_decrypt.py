import base64
from decrypt.base_decrypt import BaseDecrypt


class Decrypt(BaseDecrypt):
    def decrypt(self, resp):
        return base64.b64decode(resp).decode('utf-8')
