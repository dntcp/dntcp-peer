# Importing Required Libraries and Modules
import asyncio
import aiohttp
from aiohttp import web 
from aiohttp.client_exceptions import ClientConnectorError
import json
import base64
import time
import hashlib
from getmac import get_mac_address as gma


# Define Node Class From Specification
class Node:
    def __init__(self, name, exposed, address, public_key):
        self.peer_name = name
        self.unique_id = self.generate_unique_id()
        self.exposed = exposed
        self.address = address
        self.created = time.time()
        self.public_key = public_key
        self.ttl = float('inf')
        self.peers = {}  # stores the nodes this node can directly contact
        self.offers = {}  # stores the ConnectOffers by source_id
        self.bootstrap_nodes = ["http://peer1_address", "http://peer2_address"]  # predefined list of bootstrap nodes


    def generate_unique_id(self):
        mac_address = gma()
        node_name = self.peer_name
        identity_string = f"{mac_address}|{node_name}"
        hashed_identity_string = hashlib.sha256(identity_string.encode('utf-8')).hexdigest()
        return hashed_identity_string

    # function to register new peer
    def register_peer(self, data):
        print(f'Registering new peer {data["unique_id"]}')
        new_peer = Node(data["peer_name"], data["unique_id"], data["exposed"], data["address"], data["public_key"])
        new_peer.set_ttl(data["ttl"])
        self.peers[new_peer.unique_id] = new_peer

    # function to get peers details
    def get_peers_data(self):
        return list(map(lambda x: x.__dict__, self.peers.values()))
    
    # Update to handle_packet function to add TTL checking
    def handle_packet(self, packet):
        packet_obj = ContentPacket(packet['source_id'], packet['destination_id'], packet['protocol'], packet['payload'])
        # check if packet TTL has expired
        if packet_obj.ttl <= 0:
            print("Packet TTL has expired. Skipping...")
            return
        # check if this node is the destination 
        if packet_obj.destination_id == self.unique_id:
            self.receive_content(packet_obj)
        else:
            packet_obj.decrease_ttl()
            asyncio.create_task(self.forward_packet(packet_obj))
            asyncio.create_task(self.forward_packet(packet_obj))

        
    # Update to handle_offer function to add TTL checking
    def handle_offer(self, offer):
        co = ConnectOffer(offer['source_id'], offer['destination_id'], offer['turn_server'], offer['sdp_offer'])
        # check if offer TTL has expired 
        if co.ttl <= 0:
            print("Offer TTL has expired. Skipping...")
            return
        self.offers[co.source_id] = co
        asyncio.create_task(self.forward_offer(co))

    # Update to handle_connect function to add TTL checking
    def handle_connect(self, response):
        cr = ConnectResponse(response['source_id'], response['destination_id'], response['turn_server'], response['sdp_answer'])
        # check if response TTL has expired
        if cr.ttl <= 0:
            print("Connect response TTL has expired. Skipping...")
            return
        asyncio.create_task(self.forward_connect(cr))
    
    # logic to forward a packet to all peers
    async def forward_packet(self, packet_obj):
        for peer in self.peers.values():
            session = aiohttp.ClientSession()
            await session.post(f'{peer.address}/api/v1/packet_send', json=packet_obj.__dict__)

    # function to forward an offer 
    async def forward_offer(self, co):
        for peer in self.peers.values():
            session = aiohttp.ClientSession()
            await session.post(f'{peer.address}/api/v1/offer', json=co.__dict__)

    # function to forward a connect response 
    async def forward_connect(self, cr):
        for peer in self.peers.values():
            session = aiohttp.ClientSession()
            await session.post(f'{peer.address}/api/v1/connect', json=cr.__dict__)
  
    # Bootstrapping the Node
    def bootstrap(self):
        for node_address in self.bootstrap_nodes:
            asyncio.create_task(self.register_with(node_address))

    # Attempt to register with a bootstrap node
    async def register_with(self, address):
        data = {
            "peer_name": self.peer_name,
            "unique_id": self.unique_id,
            "exposed": self.exposed,
            "address": self.address, 
            "created": self.created,
            "public_key": self.public_key,
            "ttl": self.ttl
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{address}/api/v1/peer", json=data) as resp:
                    if resp.status == 200:
                        print(f"Registered with bootstrap node {address}")
        except ClientConnectorError:
            print(f"Failed to connect to bootstrap node at address {address}")


# Define ContentPacket Class as per specification
class ContentPacket:
  
    def __init__(self, source_id, destination_id, protocol, payload):
        self.source_id = source_id
        self.destination_id = destination_id
        self.protocol = protocol
        self.payload = base64.b64encode(payload.encode())
        self.ttl = float('inf')

    # function to decrease ttl by 1
    def decrease_ttl(self):
        self.ttl -= 1
        return self

# Define ConnectOffer Class as per specification
class ConnectOffer:
  
    def __init__(self, source_id, destination_id, turn_server, sdp_offer):
        self.source_id = source_id
        self.destination_id = destination_id
        self.turn_server = turn_server
        self.sdp_offer = sdp_offer
        self.created = time.time()
        self.ttl = float('inf')

# Define ConnectResponse class as per specification
class ConnectResponse:

    def __init__(self, source_id, destination_id, turn_server, sdp_answer):
        self.source_id = source_id
        self.destination_id = destination_id
        self.turn_server = turn_server
        self.sdp_answer = sdp_answer
        self.created = time.time()
        self.ttl = float('inf')

# Initialize the Node
node = Node("node1", "1", False, "address", "public_key")

# Define API Endpoints
routes = web.RouteTableDef()

# Route for registering peers
@routes.post('/api/v1/peer')
async def handle_peer(request):
    data = await request.json()
    node.register_peer(data)
    return web.Response()

# Route for peers listing
@routes.get('/api/v1/peers')
async def handle_get_peers(request):
    peers = node.get_peers_data()
    return web.json_response({"peers": peers})

# Route to forward packet to peers or ingest it 
@routes.post('/api/v1/packet_send')
async def handle_packet(request):
    data = await request.json()
    node.handle_packet(data)
    return web.Response()

# Endpoint for handling a new offer
@routes.post('/api/v1/offer')
async def handle_offer(request):
    data = await request.json()
    node.handle_offer(data)
    return web.Response()

# Endpoint for handling a new connection
@routes.post('/api/v1/connect')
async def handle_connect(request):
    data = await request.json()
    node.handle_connect(data)
    return web.Response()

# Initialise aiohttp Application and add routes
app = web.Application()
app.add_routes(routes)

# Run the aiohttp Application and start the registration process
web.run_app(app)

# Start the bootstrapping process
node.bootstrap()