import json
import os
import socket
import struct
import threading
import time
import unittest
from unittest import mock

from services import ocr_socket_message_utils
from services import socket_message_utils
from services.ipc_codec import decode_message, encode_message


class SocketMessageUtilsTests(unittest.TestCase):
    def _socketpair(self):
        if not hasattr(socket, "socketpair"):
            self.skipTest("socketpair unavailable")
        return socket.socketpair()

    def test_recv_message_bytes_with_status_round_trip(self):
        sender, receiver = self._socketpair()
        try:
            payload = {"type": "signal", "name": "ping", "args": [1, 2, 3]}

            self.assertTrue(
                socket_message_utils.send_message(
                    sender,
                    payload,
                    max_message_bytes=1024 * 1024,
                )
            )

            raw_payload, status = socket_message_utils.recv_message_bytes_with_status(
                receiver,
                timeout=1.0,
                max_message_bytes=1024 * 1024,
            )

            self.assertEqual(status, "ok")
            self.assertEqual(decode_message(raw_payload), payload)
        finally:
            sender.close()
            receiver.close()

    def test_ocr_send_message_rejects_oversized_payload(self):
        sender, receiver = self._socketpair()
        try:
            payload = {"data": "x" * (5 * 1024 * 1024)}
            logger = mock.Mock()

            with mock.patch.object(
                ocr_socket_message_utils,
                "MAX_OCR_SOCKET_MESSAGE_BYTES",
                4 * 1024 * 1024,
            ):
                result = ocr_socket_message_utils.send_message(
                    sender,
                    payload,
                    logger=logger,
                )

            self.assertFalse(result)
            logger.error.assert_called_once()
        finally:
            sender.close()
            receiver.close()

    def test_ocr_recv_message_uses_shared_message_reader(self):
        sender, receiver = self._socketpair()
        try:
            payload = {"type": "ocr", "text": "ok"}
            self.assertTrue(
                socket_message_utils.send_message(
                    sender,
                    payload,
                    max_message_bytes=1024 * 1024,
                )
            )

            result = ocr_socket_message_utils.recv_message(receiver, timeout=1.0)

            self.assertEqual(result, payload)
        finally:
            sender.close()
            receiver.close()

    def test_invalid_message_limit_environment_is_rejected(self):
        with mock.patch.dict(os.environ, {"TEST_SOCKET_MAX_MB": "invalid"}):
            with self.assertRaises(ValueError):
                socket_message_utils.read_socket_max_message_bytes(
                    "TEST_SOCKET_MAX_MB",
                    default_mb=64,
                    min_mb=8,
                    max_mb=512,
                )

        with mock.patch.dict(os.environ, {"TEST_SOCKET_MAX_MB": "1"}):
            with self.assertRaises(ValueError):
                socket_message_utils.read_socket_max_message_bytes(
                    "TEST_SOCKET_MAX_MB",
                    default_mb=64,
                    min_mb=8,
                    max_mb=512,
                )

    def test_clean_timeout_preserves_socket_timeout(self):
        sender, receiver = self._socketpair()
        try:
            receiver.settimeout(2.5)
            payload, status = socket_message_utils.recv_message_bytes_with_status(
                receiver,
                timeout=0.03,
                max_message_bytes=1024,
            )

            self.assertIsNone(payload)
            self.assertEqual(status, "timeout")
            self.assertEqual(receiver.gettimeout(), 2.5)
        finally:
            sender.close()
            receiver.close()

    def test_receive_wait_does_not_change_shared_socket_timeout(self):
        sender, receiver = self._socketpair()
        result = []
        try:
            receiver.settimeout(2.5)

            thread = threading.Thread(
                target=lambda: result.append(
                    socket_message_utils.recv_message(receiver, timeout=0.2)
                )
            )
            thread.start()
            time.sleep(0.03)

            self.assertEqual(receiver.gettimeout(), 2.5)
            self.assertTrue(
                socket_message_utils.send_message(sender, {"type": "ready"})
            )
            thread.join(1.0)

            self.assertFalse(thread.is_alive())
            self.assertEqual(result, [{"type": "ready"}])
            self.assertEqual(receiver.gettimeout(), 2.5)
        finally:
            sender.close()
            receiver.close()

    def test_fragmented_message_uses_inactivity_timeout(self):
        sender, receiver = self._socketpair()
        payload = {"data": "x" * 256}
        encoded = encode_message(payload)
        packet = struct.pack("!I", len(encoded)) + encoded

        def _send_fragments():
            for offset in range(0, len(packet), 8):
                sender.sendall(packet[offset:offset + 8])
                time.sleep(0.01)

        thread = threading.Thread(target=_send_fragments)
        try:
            thread.start()
            result = socket_message_utils.recv_message(receiver, timeout=0.03)
            thread.join(1.0)

            self.assertFalse(thread.is_alive())
            self.assertEqual(result, payload)
        finally:
            sender.close()
            receiver.close()

    def test_partial_header_timeout_aborts_connection(self):
        sender, receiver = self._socketpair()
        try:
            sender.sendall(b"\x00\x00")
            payload, status = socket_message_utils.recv_message_bytes_with_status(
                receiver,
                timeout=0.03,
                max_message_bytes=1024,
            )

            self.assertIsNone(payload)
            self.assertEqual(status, "partial_timeout")
            self.assertEqual(receiver.fileno(), -1)
        finally:
            sender.close()
            receiver.close()

    def test_truncated_payload_aborts_connection(self):
        sender, receiver = self._socketpair()
        try:
            sender.sendall(struct.pack("!I", 8) + b"xx")
            sender.shutdown(socket.SHUT_WR)
            payload, status = socket_message_utils.recv_message_bytes_with_status(
                receiver,
                timeout=1.0,
                max_message_bytes=1024,
            )

            self.assertIsNone(payload)
            self.assertEqual(status, "truncated")
            self.assertEqual(receiver.fileno(), -1)
        finally:
            sender.close()
            receiver.close()

    def test_non_dictionary_payload_aborts_connection_and_raises(self):
        sender, receiver = self._socketpair()
        try:
            payload = json.dumps(
                {
                    "protocol": "lca-worker-ipc",
                    "version": 1,
                    "payload": ["not", "a", "dictionary"],
                }
            ).encode("utf-8")
            sender.sendall(struct.pack("!I", len(payload)) + payload)

            with self.assertRaises(socket_message_utils.SocketMessageError) as raised:
                socket_message_utils.recv_message(
                    receiver,
                    timeout=1.0,
                    max_message_bytes=1024,
                )

            self.assertEqual(raised.exception.status, "invalid_payload")
            self.assertEqual(receiver.fileno(), -1)
        finally:
            sender.close()
            receiver.close()

    def test_ocr_adapter_propagates_protocol_error(self):
        sender, receiver = self._socketpair()
        try:
            logger = mock.Mock()
            payload = json.dumps(
                {
                    "protocol": "lca-worker-ipc",
                    "version": 1,
                    "payload": ["invalid"],
                }
            ).encode("utf-8")
            sender.sendall(struct.pack("!I", len(payload)) + payload)

            with self.assertRaises(socket_message_utils.SocketMessageError) as raised:
                ocr_socket_message_utils.recv_message(
                    receiver,
                    timeout=1.0,
                    logger=logger,
                )

            self.assertEqual(raised.exception.status, "invalid_payload")
            logger.error.assert_called_once()
            self.assertEqual(logger.error.call_args.args[-1], "invalid_payload")
        finally:
            sender.close()
            receiver.close()


if __name__ == "__main__":
    unittest.main()
