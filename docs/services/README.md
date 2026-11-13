# Service references

| Service | Public image | Standalone port | Reference |
| --- | --- | --- | --- |
| Player | `tirppy/student-id-player-service` | `8001` | [Player](README.player.md) |
| Session | `tirppy/student-id-session-service` | `8002` | [Session](README.session.md) |
| Applicant | `mcittkmims/applicant-service` | `8081` | [Applicant](README.applicant.md) |
| Credential | `mcittkmims/credential-service` | `8082` | [Credential](README.credential.md) |
| Server Rules | `maxnoragami/server-rules-service` | `8005` | [Server Rules](README.server-rules.md) |
| University Record | `maxnoragami/university-record-service` | `8006` | [University Record](README.university-records.md) |
| Moderation | `sentientmoss/pad-moderation-service` | `8008` | [Moderation](README.moderation.md) |
| Discord DMs | `sentientmoss/pad-discord-dms-service` | `8009` | [Discord DMs](README.discord-dms.md) |

The [Compose configuration](../../compose.yaml) publishes only the gateway's public listener on `127.0.0.1:8080` and the WebSocket listeners of `discord-dms-1` and `discord-dms-2` on `127.0.0.1:8009` and `127.0.0.1:8010`. The Message Broker has no host port. Clients reach every other service through the gateway. The standalone ports apply when a service runs outside Compose. Databases, including `broker-db`, stay on the container network.

All client-to-service REST uses the shared Go gateway's public listener. The gateway sends each request to the shared Go Message Broker, which delivers it to one ready replica. All service-to-service REST goes to the Broker. Realtime negotiation and chat-ticket REST use the gateway. After negotiation, clients connect directly to Discord DMs for the WebSocket upgrade and frames. Producers publish domain events to the Broker by topic, and the Broker delivers them to each subscribing service. Service-owned storage connections do not pass through the gateway or the Broker. The gateway and the Broker own no domain data. The [interaction map](../architecture.md#communication) records these routes, and [gateway authorization](../architecture.md#gateway-authorization) describes identity checks and service permissions. The [architecture diagram](../diagrams/architecture.mmd) shows these routes and the topic connections.

The Message Broker has the public image `maxnoragami/message-broker-service` and runs in Compose as `message-broker`. Each domain service sets `BROKER_URL` and `BROKER_SERVICE_TOKEN` for its peer calls and `BROKER_HOP_TOKEN` and the Broker key for the requests it receives. [Message Broker](../architecture.md#message-broker) describes its connections and boundaries.
