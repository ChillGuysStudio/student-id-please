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

The [Compose configuration](../../compose.yaml) publishes only the gateway's public listener on `127.0.0.1:8080` and the Discord DMs WebSocket listener on `127.0.0.1:8009`. Clients reach every other service through the gateway. The standalone ports apply when a service runs outside Compose. Databases and RabbitMQ stay on the container network.

All client-to-service REST uses the shared Go gateway's public listener, and all service-to-service REST uses its internal listener. Realtime negotiation and chat-ticket REST use the gateway. After negotiation, clients connect directly to Discord DMs for the WebSocket upgrade and frames. Broker events and service-owned storage connections are not REST paths. The gateway owns no domain data. The [interaction map](../architecture.md#communication) records these routes, and [gateway authorization](../architecture.md#gateway-authorization) describes identity checks and service permissions. The [architecture diagram](../diagrams/architecture.mmd) shows these routes and the broker connections.
