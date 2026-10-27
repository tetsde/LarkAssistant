import sys, os
sys.path.insert(0, os.path.abspath("."))
import asyncio
from services.knowledge.docreader_client import docreader_service

async def test():
    dummy_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xdc\xccY\xe7\x00\x00\x00\x00IEND\xaeB`\x82'
    res = await docreader_service.read(dummy_png, 'test.png')
    print('DocReader result:', res.success, res.markdown_content, res.error)

asyncio.run(test())
