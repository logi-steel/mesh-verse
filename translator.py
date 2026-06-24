"""
Meshtastic ↔ MeshCore Protocol Translator
Allows messages to be sent to both mesh clients from a central server.
"""

import asyncio
import logging
import struct
from dataclasses import dataclass
from typing import Dict, Optional, Callable
from enum import IntEnum

# Meshtastic imports
import meshtastic
import meshtastic.serial_interface
from meshtastic.protobuf import mesh_pb2, portnums_pb2

# MeshCore imports
from meshcore import MeshCore, EventType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# MESSAGE TYPE DEFINITIONS
# ============================================================================

class MeshCorePayloadType(IntEnum):
    """MeshCore payload type constants"""
    PAYLOAD_TYPE_REQ = 0
    PAYLOAD_TYPE_TXT_MSG = 1
    PAYLOAD_TYPE_ADVERT = 2
    PAYLOAD_TYPE_PATH = 3
    PAYLOAD_TYPE_ACK = 4
    PAYLOAD_TYPE_CONTROL = 5


class MeshCoreRouteType(IntEnum):
    """MeshCore route type constants"""
    ROUTE_FLOOD = 0
    ROUTE_DIRECT = 1
    ROUTE_TRANSPORT_FLOOD = 2
    ROUTE_TRANSPORT_DIRECT = 3


@dataclass
class TranslatedMessage:
    """Standard message format for translation"""
    source_id: int
    dest_id: int
    message_type: str  # 'text', 'position', 'telemetry', etc.
    payload: bytes
    text: Optional[str] = None
    timestamp: int = 0
    hop_limit: int = 3


# ============================================================================
# MESHTASTIC TO MESHCORE TRANSLATOR
# ============================================================================

class MeshtasticToMeshCore:
    """Converts Meshtastic protobuf packets to MeshCore binary format"""

    @staticmethod
    def translate_packet(meshtastic_packet: Dict) -> Optional[bytes]:
        """
        Convert a Meshtastic packet dictionary to MeshCore binary format.

        Args:
            meshtastic_packet: Dictionary representation of MeshPacket

        Returns:
            MeshCore binary-encoded packet or None if unsupported
        """
        try:
            source_id = meshtastic_packet.get("from", 0)
            dest_id = meshtastic_packet.get("to", 0)

            # Extract message content
            decoded = meshtastic_packet.get("decoded", {})
            portnum = decoded.get("portnum", "UNKNOWN_APP")

            # Handle text messages
            if portnum == "TEXT_MESSAGE_APP" or portnum == 1:
                text = decoded.get("text", "")
                return MeshtasticToMeshCore._build_meshcore_text_message(
                    source_id, dest_id, text
                )

            # Handle position/telemetry data
            elif portnum in ["POSITION_APP", "TELEMETRY_APP"] or portnum in [2, 67]:
                payload = decoded.get("payload", b"")
                return MeshtasticToMeshCore._build_meshcore_data_message(
                    source_id, dest_id, payload
                )

            else:
                logger.debug(f"Unsupported Meshtastic portnum: {portnum}")
                return None

        except Exception as e:
            logger.error(f"Error translating Meshtastic packet: {e}")
            return None

    @staticmethod
    def _build_meshcore_text_message(
        source_id: int, dest_id: int, text: str
    ) -> bytes:
        """Build a MeshCore text message packet"""
        # MeshCore header: VVPPPPRR
        # Version=0, PayloadType=TEXT_MSG(1), RouteType=DIRECT(1)
        header = 0x01  # 00_0001_01 = V:0, Type:1(TEXT), Route:1(DIRECT)

        # Convert text to UTF-8 bytes
        text_bytes = text.encode("utf-8")[:184]  # Max 184 bytes payload

        # Build packet: [header][source][dest][payload_len][text]
        packet = struct.pack(
            "<BII", header, source_id, dest_id
        ) + struct.pack("<B", len(text_bytes)) + text_bytes

        return packet

    @staticmethod
    def _build_meshcore_data_message(
        source_id: int, dest_id: int, payload: bytes
    ) -> bytes:
        """Build a MeshCore data message packet"""
        # Header: Data message type
        header = 0x05  # 00_0101_01 = V:0, Type:5(DATA), Route:1(DIRECT)

        payload = payload[:184]  # Max 184 bytes

        # Build packet
        packet = struct.pack(
            "<BII", header, source_id, dest_id
        ) + struct.pack("<B", len(payload)) + payload

        return packet


# ============================================================================
# MESHCORE TO MESHTASTIC TRANSLATOR
# ============================================================================

class MeshCoreToMeshtastic:
    """Converts MeshCore binary packets to Meshtastic protobuf format"""

    @staticmethod
    def parse_meshcore_packet(data: bytes) -> Optional[TranslatedMessage]:
        """
        Parse a MeshCore binary packet into a TranslatedMessage.

        Args:
            data: Raw MeshCore binary packet

        Returns:
            TranslatedMessage or None if parsing fails
        """
        try:
            if len(data) < 10:
                logger.warning("MeshCore packet too short")
                return None

            # Parse header byte: VVPPPPRR
            header = data[0]
            version = (header >> 6) & 0x3
            payload_type = (header >> 2) & 0xF
            route_type = header & 0x3

            # Parse IDs (little-endian)
            source_id = struct.unpack("<I", data[1:5])[0]
            dest_id = struct.unpack("<I", data[5:9])[0]
            payload_len = data[9]

            if len(data) < 10 + payload_len:
                logger.warning("MeshCore packet payload truncated")
                return None

            payload = data[10 : 10 + payload_len]

            # Determine message type
            message_type = "data"
            text = None

            if payload_type == MeshCorePayloadType.PAYLOAD_TYPE_TXT_MSG:
                message_type = "text"
                try:
                    text = payload.decode("utf-8")
                except UnicodeDecodeError:
                    text = None

            return TranslatedMessage(
                source_id=source_id,
                dest_id=dest_id,
                message_type=message_type,
                payload=payload,
                text=text,
            )

        except Exception as e:
            logger.error(f"Error parsing MeshCore packet: {e}")
            return None

    @staticmethod
    def to_meshtastic_dict(msg: TranslatedMessage) -> Dict:
        """Convert TranslatedMessage to Meshtastic packet dictionary"""
        packet = {
            "from": msg.source_id,
            "to": msg.dest_id,
            "decoded": {
                "portnum": "TEXT_MESSAGE_APP" if msg.message_type == "text" else "DATA_PACKET",
            },
        }

        if msg.text:
            packet["decoded"]["text"] = msg.text
        else:
            packet["decoded"]["payload"] = msg.payload

        return packet


# ============================================================================
# DUAL-PROTOCOL GATEWAY SERVER
# ============================================================================

class MeshGateway:
    """
    Bidirectional gateway that bridges Meshtastic and MeshCore networks.
    Allows users to send messages to both mesh types from a single interface.
    """

    def __init__(
        self,
        meshtastic_port: str = "/dev/ttyUSB0",
        meshcore_serial_port: str = "/dev/ttyUSB1",
    ):
        """
        Initialize the gateway.

        Args:
            meshtastic_port: Serial port for Meshtastic device
            meshcore_serial_port: Serial port for MeshCore device
        """
        self.meshtastic_port = meshtastic_port
        self.meshcore_serial_port = meshcore_serial_port

        self.meshtastic_iface = None
        self.meshcore = None

        # Message routing callbacks
        self.on_meshtastic_message: Optional[Callable] = None
        self.on_meshcore_message: Optional[Callable] = None

    async def connect(self) -> bool:
        """Connect to both mesh networks"""
        try:
            # Connect to Meshtastic
            logger.info(f"Connecting to Meshtastic on {self.meshtastic_port}...")
            self.meshtastic_iface = meshtastic.serial_interface.SerialInterface(
                devPath=self.meshtastic_port
            )
            logger.info("Meshtastic connected")

            # Connect to MeshCore
            logger.info(f"Connecting to MeshCore on {self.meshcore_serial_port}...")
            self.meshcore = await MeshCore.create_serial(self.meshcore_serial_port)
            logger.info("MeshCore connected")

            # Subscribe to message events
            self._setup_meshtastic_listeners()
            await self._setup_meshcore_listeners()

            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    def _setup_meshtastic_listeners(self):
        """Set up Meshtastic message listeners"""
        from pubsub import pub

        def on_meshtastic_receive(packet):
            """Handle incoming Meshtastic message"""
            asyncio.create_task(self._handle_meshtastic_message(packet))

        pub.subscribe(on_meshtastic_receive, "meshtastic.receive.text")
        logger.info("Meshtastic listeners configured")

    async def _setup_meshcore_listeners(self):
        """Set up MeshCore message listeners"""
        # Subscribe to MeshCore text messages
        # (Implementation depends on MeshCore async API)
        logger.info("MeshCore listeners configured")

    async def _handle_meshtastic_message(self, packet: Dict):
        """
        Handle a message received from Meshtastic.
        Forward to MeshCore if configured.
        """
        logger.info(f"Meshtastic message from {packet.get('from')}: {packet}")

        # Translate to MeshCore
        meshcore_packet = MeshtasticToMeshCore.translate_packet(packet)
        if meshcore_packet and self.meshcore:
            try:
                await self.meshcore.commands.send_raw(meshcore_packet)
                logger.info(f"Forwarded to MeshCore: {len(meshcore_packet)} bytes")
            except Exception as e:
                logger.error(f"Failed to forward to MeshCore: {e}")

        # Trigger callback
        if self.on_meshtastic_message:
            self.on_meshtastic_message(packet)

    async def _handle_meshcore_message(self, data: bytes):
        """
        Handle a message received from MeshCore.
        Forward to Meshtastic if configured.
        """
        msg = MeshCoreToMeshtastic.parse_meshcore_packet(data)
        if not msg:
            return

        logger.info(f"MeshCore message from {msg.source_id}: {msg.text or msg.payload}")

        # Translate to Meshtastic
        meshtastic_packet = MeshCoreToMeshtastic.to_meshtastic_dict(msg)

        if self.meshtastic_iface:
            try:
                if msg.text:
                    self.meshtastic_iface.sendText(
                        msg.text,
                        destinationId=msg.dest_id,
                        wantAck=True,
                    )
                else:
                    self.meshtastic_iface.sendData(
                        msg.payload,
                        destinationId=msg.dest_id,
                        wantAck=True,
                    )
                logger.info(f"Forwarded to Meshtastic: to {msg.dest_id}")
            except Exception as e:
                logger.error(f"Failed to forward to Meshtastic: {e}")

        # Trigger callback
        if self.on_meshcore_message:
            self.on_meshcore_message(meshtastic_packet)

    async def send_to_both(
        self,
        message: str,
        dest_id: int,
        meshtastic_enabled: bool = True,
        meshcore_enabled: bool = True,
    ):
        """
        Send a message to both networks simultaneously.

        Args:
            message: Text message to send
            dest_id: Destination node ID
            meshtastic_enabled: Whether to send via Meshtastic
            meshcore_enabled: Whether to send via MeshCore
        """
        if meshtastic_enabled and self.meshtastic_iface:
            try:
                self.meshtastic_iface.sendText(message, destinationId=dest_id)
                logger.info(f"Sent to Meshtastic: {dest_id} - {message}")
            except Exception as e:
                logger.error(f"Failed to send via Meshtastic: {e}")

        if meshcore_enabled and self.meshcore:
            try:
                meshcore_packet = MeshtasticToMeshCore._build_meshcore_text_message(
                    0, dest_id, message
                )
                await self.meshcore.commands.send_raw(meshcore_packet)
                logger.info(f"Sent to MeshCore: {dest_id} - {message}")
            except Exception as e:
                logger.error(f"Failed to send via MeshCore: {e}")

    async def close(self):
        """Close all connections"""
        if self.meshtastic_iface:
            self.meshtastic_iface.close()
        if self.meshcore:
            await self.meshcore.disconnect()
        logger.info("Gateway closed")


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

async def main():
    """Example: Start the dual-network gateway"""
    gateway = MeshGateway(
        meshtastic_port="/dev/ttyUSB0",
        meshcore_serial_port="/dev/ttyUSB1",
    )

    if await gateway.connect():
        logger.info("Gateway online and bridging both networks")

        try:
            # Example: Send a message to both networks
            await gateway.send_to_both(
                message="Hello from translator!",
                dest_id=12345,
                meshtastic_enabled=True,
                meshcore_enabled=True,
            )

            # Keep running
            while True:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            logger.info("Shutdown requested")
        finally:
            await gateway.close()
    else:
        logger.error("Failed to connect to mesh networks")


if __name__ == "__main__":
    asyncio.run(main())
