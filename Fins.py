from __future__ import annotations

import json
import socket
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class FinsError(Exception):
    """Base exception for FINS communication errors."""


class FinsResponseError(FinsError):
    def __init__(self, end_code: int):
        super().__init__(f"FINS response end code: 0x{end_code:04X}")
        self.end_code = end_code


MEMORY_AREA_CODES = {
    ("CIO", "word"): 0xB0,
    ("CIO", "bit"): 0x30,
    ("WR", "word"): 0xB1,
    ("WR", "bit"): 0x31,
    ("HR", "word"): 0xB2,
    ("HR", "bit"): 0x32,
    ("AR", "word"): 0xB3,
    ("AR", "bit"): 0x33,
    ("DM", "word"): 0x82,
    ("DM", "bit"): 0x02,
    ("EM", "word"): 0xA0,
}


@dataclass
class FinsUdpConfig:
    host: str
    port: int = 9600
    timeout_sec: float = 1.0
    source_network: int = 0
    source_node: int = 10
    source_unit: int = 0
    destination_network: int = 0
    destination_node: int = 1
    destination_unit: int = 0
    service_id: int = 1

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FinsUdpConfig":
        return cls(
            host=str(data.get("host", "192.168.250.1")),
            port=int(data.get("port", 9600)),
            timeout_sec=float(data.get("timeout_sec", 1.0)),
            source_network=int(data.get("source_network", 0)),
            source_node=int(data.get("source_node", 10)),
            source_unit=int(data.get("source_unit", 0)),
            destination_network=int(data.get("destination_network", 0)),
            destination_node=int(data.get("destination_node", 1)),
            destination_unit=int(data.get("destination_unit", 0)),
            service_id=int(data.get("service_id", 1)),
        )


class FinsUdpClient:
    def __init__(self, config: FinsUdpConfig):
        self.config = config
        self.sock: Optional[socket.socket] = None
        self.service_id = config.service_id & 0xFF

    @classmethod
    def from_config(cls, plc_config: Dict[str, Any]) -> "FinsUdpClient":
        return cls(FinsUdpConfig.from_dict(plc_config))

    def __enter__(self) -> "FinsUdpClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def connect(self) -> None:
        if self.sock is not None:
            return
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(self.config.timeout_sec)
        self.sock.connect((self.config.host, self.config.port))

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def request(self, command: bytes) -> bytes:
        self.connect()
        sid = self._next_service_id()
        frame = self._header(sid) + command
        assert self.sock is not None
        self.sock.send(frame)
        response = self.sock.recv(4096)

        if len(response) < 14:
            raise FinsError(f"FINS response too short: {len(response)} bytes")
        if response[9] != sid:
            raise FinsError(f"FINS service id mismatch: sent {sid}, got {response[9]}")

        end_code = int.from_bytes(response[12:14], "big")
        if end_code != 0:
            raise FinsResponseError(end_code)
        return response

    def read_words(self, area: str, address: int, count: int, bit: int = 0) -> List[int]:
        area_code = memory_area_code(area, "word")
        command = bytes([0x01, 0x01, area_code]) + encode_address(address, bit) + count.to_bytes(2, "big")
        response = self.request(command)
        data = response[14:]
        expected = count * 2
        if len(data) < expected:
            raise FinsError(f"FINS word read expected {expected} bytes, got {len(data)}")
        return list(struct.unpack(f">{count}H", data[:expected]))

    def write_words(self, area: str, address: int, values: Iterable[int], bit: int = 0) -> None:
        value_list = [int(value) & 0xFFFF for value in values]
        area_code = memory_area_code(area, "word")
        payload = b"".join(value.to_bytes(2, "big") for value in value_list)
        command = (
            bytes([0x01, 0x02, area_code])
            + encode_address(address, bit)
            + len(value_list).to_bytes(2, "big")
            + payload
        )
        self.request(command)

    def read_bits(self, area: str, address: int, bit: int = 0, count: int = 1) -> List[bool]:
        area_code = memory_area_code(area, "bit")
        command = bytes([0x01, 0x01, area_code]) + encode_address(address, bit) + count.to_bytes(2, "big")
        response = self.request(command)
        data = response[14:]
        if len(data) < count:
            raise FinsError(f"FINS bit read expected {count} bytes, got {len(data)}")
        return [value != 0 for value in data[:count]]

    def write_bits(self, area: str, address: int, values: Iterable[bool], bit: int = 0) -> None:
        value_list = [1 if value else 0 for value in values]
        area_code = memory_area_code(area, "bit")
        command = (
            bytes([0x01, 0x02, area_code])
            + encode_address(address, bit)
            + len(value_list).to_bytes(2, "big")
            + bytes(value_list)
        )
        self.request(command)

    def read_config_address(self, address_config: Dict[str, Any]) -> Any:
        data_type = str(address_config.get("type", "word")).lower()
        area = str(address_config.get("area", "DM"))
        address = int(address_config.get("address", 0))
        bit = int(address_config.get("bit", 0))
        words = int(address_config.get("words", 1))

        if data_type == "bit":
            return self.read_bits(area, address, bit, 1)[0]
        if data_type == "string":
            return words_to_string(self.read_words(area, address, words))
        if data_type == "float":
            return words_to_float(self.read_words(area, address, 2), address_config.get("word_order", "big"))
        return self.read_words(area, address, words)

    def write_config_address(self, address_config: Dict[str, Any], value: Any) -> None:
        data_type = str(address_config.get("type", "word")).lower()
        area = str(address_config.get("area", "DM"))
        address = int(address_config.get("address", 0))
        bit = int(address_config.get("bit", 0))

        if data_type == "bit":
            self.write_bits(area, address, [bool(value)], bit)
        elif data_type == "float":
            self.write_words(area, address, float_to_words(float(value), address_config.get("word_order", "big")))
        elif data_type == "string":
            self.write_words(area, address, string_to_words(str(value), int(address_config.get("words", 10))))
        else:
            values = value if isinstance(value, (list, tuple)) else [value]
            self.write_words(area, address, values)

    def _header(self, service_id: int) -> bytes:
        return bytes(
            [
                0x80,
                0x00,
                0x02,
                self.config.destination_network & 0xFF,
                self.config.destination_node & 0xFF,
                self.config.destination_unit & 0xFF,
                self.config.source_network & 0xFF,
                self.config.source_node & 0xFF,
                self.config.source_unit & 0xFF,
                service_id & 0xFF,
            ]
        )

    def _next_service_id(self) -> int:
        sid = self.service_id & 0xFF
        self.service_id = (self.service_id + 1) & 0xFF
        if self.service_id == 0:
            self.service_id = 1
        return sid


def memory_area_code(area: str, data_type: str = "word") -> int:
    key = (area.upper(), data_type.lower())
    if key not in MEMORY_AREA_CODES:
        raise FinsError(f"Unsupported FINS memory area: {area}/{data_type}")
    return MEMORY_AREA_CODES[key]


def encode_address(address: int, bit: int = 0) -> bytes:
    if not 0 <= int(address) <= 0xFFFF:
        raise ValueError("FINS address must be between 0 and 65535")
    if not 0 <= int(bit) <= 15:
        raise ValueError("FINS bit must be between 0 and 15")
    return int(address).to_bytes(2, "big") + bytes([int(bit)])


def words_to_string(words: Iterable[int], encoding: str = "gbk") -> str:
    data = b"".join((int(word) & 0xFFFF).to_bytes(2, "big") for word in words)
    return data.rstrip(b"\x00 ").decode(encoding, errors="ignore")


def string_to_words(text: str, word_count: int, encoding: str = "gbk") -> List[int]:
    data = text.encode(encoding, errors="ignore")[: word_count * 2]
    data = data.ljust(word_count * 2, b"\x00")
    return [int.from_bytes(data[index : index + 2], "big") for index in range(0, len(data), 2)]


def words_to_float(words: Iterable[int], word_order: str = "big") -> float:
    word_list = list(words)
    if len(word_list) < 2:
        raise ValueError("float requires 2 words")
    selected = word_list[:2]
    if str(word_order).lower() in {"little", "swap", "low_high"}:
        selected = [selected[1], selected[0]]
    data = b"".join((int(word) & 0xFFFF).to_bytes(2, "big") for word in selected)
    return struct.unpack(">f", data)[0]


def float_to_words(value: float, word_order: str = "big") -> List[int]:
    data = struct.pack(">f", float(value))
    words = [int.from_bytes(data[0:2], "big"), int.from_bytes(data[2:4], "big")]
    if str(word_order).lower() in {"little", "swap", "low_high"}:
        words = [words[1], words[0]]
    return words


def load_plc_config(config_path: str = "config.json") -> Dict[str, Any]:
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    return config.get("plc", {})


if __name__ == "__main__":
    plc = load_plc_config()
    client = FinsUdpClient.from_config(plc)
    addresses = plc.get("addresses", {})
    print(f"FINS UDP target: {client.config.host}:{client.config.port}")
    print(f"Configured PLC addresses: {', '.join(addresses.keys())}")
