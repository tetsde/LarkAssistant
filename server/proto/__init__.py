import os
import sys

# Ensure proto directory is in sys.path so docreader_pb2_grpc can import docreader_pb2
PROTO_DIR = os.path.dirname(os.path.abspath(__file__))
if PROTO_DIR not in sys.path:
    sys.path.insert(0, PROTO_DIR)
